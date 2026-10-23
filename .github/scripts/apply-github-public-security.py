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
        if any(value not in ("enabled", "disabled") for value in current.values()):
            raise PublicSecurityError(
                f"Cannot verify complete security baseline for {repo}; refusing writes"
            )
        if (
            current["secret_scanning"] == "enabled"
            and current["secret_scanning_push_protection"] == "enabled"
        ):
            items.append({"repo": repo, "action": "no_change", "current": current})
        else:
            items.append({"repo": repo, "action": "enable", "current": current})
    return items


def apply(cfg, dry_run=False, runner=run_gh):
    # Plan must resolve every public repository and both security statuses
    # before making the first write. Unknown API fields fail closed.
    items = plan(cfg, runner=runner)
    if dry_run:
        return {"dry_run": True, "plan": items}

    attempted = []
    changed = []
    target = {"secret_scanning": "enabled", "secret_scanning_push_protection": "enabled"}

    try:
        for item in items:
            if item["action"] != "enable":
                continue
            repo = item["repo"]
            current_info = api_json(f"repos/{repo}", runner=runner) or {}
            actual = security_status(current_info)
            if (current_info.get("visibility") != "public"
                    or bool(current_info.get("archived"))
                    or actual != item["current"]):
                raise PublicSecurityError(f"Stale security baseline for {repo}; refusing write")

            # Register the attempt BEFORE PATCH, so an uncertain API outcome
            # is reconciled and rolled back rather than silently ignored.
            attempted.append(item)
            api_json(f"repos/{repo}", method="PATCH", payload=desired_payload(), runner=runner)
            verify = api_json(f"repos/{repo}", runner=runner) or {}
            if security_status(verify) != target:
                raise PublicSecurityError(f"Security readback mismatch for {repo}")
            changed.append(repo)

    except Exception as original_error:
        rollback_errors = []
        for item in reversed(attempted):
            repo = item["repo"]
            previous = item["current"]
            try:
                observed = security_status(api_json(f"repos/{repo}", runner=runner) or {})
                if observed == previous:
                    continue
                if observed != target:
                    raise PublicSecurityError(
                        f"Ambiguous security state for {repo}; manual reconciliation required"
                    )
                restore_payload = {
                    "security_and_analysis": {
                        field: {"status": previous[field]}
                        for field in ("secret_scanning", "secret_scanning_push_protection")
                    }
                }
                api_json(f"repos/{repo}", method="PATCH", payload=restore_payload, runner=runner)
                restored = security_status(api_json(f"repos/{repo}", runner=runner) or {})
                if restored != previous:
                    raise PublicSecurityError(f"Rollback readback mismatch for {repo}")
            except Exception as rollback_error:
                rollback_errors.append(f"{repo}: {rollback_error}")

        if rollback_errors:
            raise PublicSecurityError(
                f"{original_error}; rollback incomplete: " + "; ".join(rollback_errors)
            ) from original_error
        raise

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
