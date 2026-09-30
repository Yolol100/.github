#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class PublicSecurityError(RuntimeError):
    pass


def run_gh(args, input_text=None):
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        raise PublicSecurityError("GH_TOKEN is required for public security reads/writes")
    result = subprocess.run(
        ["gh", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise PublicSecurityError(details or f"gh command failed with exit code {result.returncode}")
    return result.stdout.strip()


def api_json(path, method="GET", payload=None, runner=run_gh):
    args = ["api", path]
    input_text = None
    if method != "GET":
        args.extend(["--method", method, "--input", "-"])
        input_text = json.dumps(payload, separators=(",", ":"))
    raw = runner(args, input_text=input_text)
    return json.loads(raw) if raw else None


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema_version") != 1:
        raise PublicSecurityError("Unsupported or missing schema_version; expected 1")
    owner = cfg.get("owner")
    repos = cfg.get("repositories")
    if not isinstance(owner, str) or not owner:
        raise PublicSecurityError("Invalid owner")
    if not isinstance(repos, list) or not repos:
        raise PublicSecurityError("repositories must be a non-empty list")
    names = [item.get("name") if isinstance(item, dict) else None for item in repos]
    if any(not isinstance(name, str) or not name for name in names):
        raise PublicSecurityError("Invalid repository entry")
    if len(names) != len(set(names)):
        raise PublicSecurityError("Duplicate repository entry")
    return cfg


def security_status(info):
    sec = info.get("security_and_analysis") or {}

    def status(name):
        value = sec.get(name)
        if not isinstance(value, dict):
            return None
        return value.get("status")

    return {
        "secret_scanning": status("secret_scanning"),
        "secret_scanning_push_protection": status("secret_scanning_push_protection"),
    }


def desired_payload():
    return {
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }
    }


def plan(cfg, runner=run_gh):
    owner = cfg["owner"]
    items = []
    for item in cfg["repositories"]:
        name = item["name"]
        repo = f"{owner}/{name}"
        info = api_json(f"repos/{repo}", runner=runner) or {}
        visibility = info.get("visibility")
        archived = bool(info.get("archived"))

        if archived:
            items.append({"repo": repo, "action": "skip_archived"})
            continue
        if visibility != "public":
            items.append({
                "repo": repo,
                "action": "skip_non_public",
                "visibility": visibility,
            })
            continue

        current = security_status(info)
        if (
            current["secret_scanning"] == "enabled"
            and current["secret_scanning_push_protection"] == "enabled"
        ):
            items.append({"repo": repo, "action": "no_change", "current": current})
        else:
            items.append({"repo": repo, "action": "enable", "current": current})
    return items


def apply(cfg, dry_run=False, runner=run_gh):
    items = plan(cfg, runner=runner)
    if dry_run:
        return {"dry_run": True, "plan": items}

    owner = cfg["owner"]
    changed = []

    for item in items:
        if item["action"] != "enable":
            continue
        name = item["repo"].split("/", 1)[1]
        api_json(
            f"repos/{owner}/{name}",
            method="PATCH",
            payload=desired_payload(),
            runner=runner,
        )
        verify = api_json(f"repos/{owner}/{name}", runner=runner) or {}
        state = security_status(verify)
        if (
            state["secret_scanning"] != "enabled"
            or state["secret_scanning_push_protection"] != "enabled"
        ):
            raise PublicSecurityError(f"Security readback mismatch for {item['repo']}")
        changed.append(item["repo"])

    return {"dry_run": False, "changed": changed, "plan": items}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        if args.validate_only:
            print("Public security configuration valid.")
            return 0
        result = apply(cfg, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PublicSecurityError, json.JSONDecodeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
