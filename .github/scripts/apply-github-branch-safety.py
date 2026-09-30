#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

RULESET_NAME = "Protect main"
RULESET_RULE_TYPES = ("deletion", "non_fast_forward")


class BranchSafetyError(RuntimeError):
    pass


def run_gh(args, input_text=None):
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        raise BranchSafetyError("GH_TOKEN is required for branch-safety reads/writes")
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
        raise BranchSafetyError(details or f"gh command failed with exit code {result.returncode}")
    return result.stdout.strip()


def desired_ruleset():
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "exclude": [],
                "include": ["~DEFAULT_BRANCH"],
            }
        },
        "rules": [{"type": rule_type} for rule_type in RULESET_RULE_TYPES],
        "bypass_actors": [],
    }


def normalize_ruleset(raw):
    return {
        "name": raw.get("name"),
        "target": raw.get("target"),
        "enforcement": raw.get("enforcement"),
        "conditions": {
            "ref_name": {
                "exclude": list(raw.get("conditions", {}).get("ref_name", {}).get("exclude", [])),
                "include": list(raw.get("conditions", {}).get("ref_name", {}).get("include", [])),
            }
        },
        "rules": sorted(
            [{"type": item.get("type")} for item in raw.get("rules", [])],
            key=lambda item: item["type"] or "",
        ),
        "bypass_actors": list(raw.get("bypass_actors", [])),
    }


def ruleset_matches(raw):
    return normalize_ruleset(raw) == normalize_ruleset(desired_ruleset())


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema_version") != 1:
        raise BranchSafetyError("Unsupported or missing schema_version; expected 1")
    owner = cfg.get("owner")
    repositories = cfg.get("repositories")
    if not isinstance(owner, str) or not owner:
        raise BranchSafetyError("Invalid owner")
    if not isinstance(repositories, list) or not repositories:
        raise BranchSafetyError("repositories must be a non-empty list")
    names = []
    for item in repositories:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            raise BranchSafetyError("Invalid repository entry")
        names.append(name)
    if len(names) != len(set(names)):
        raise BranchSafetyError("Duplicate repository entry")
    return cfg


def api_json(path, method="GET", payload=None, runner=run_gh):
    args = ["api", path]
    input_text = None
    if method != "GET":
        args.extend(["--method", method, "--input", "-"])
        input_text = json.dumps(payload, separators=(",", ":"))
    raw = runner(args, input_text=input_text)
    return json.loads(raw) if raw else None


def repo_info(owner, name, runner=run_gh):
    return api_json(f"repos/{owner}/{name}", runner=runner)


def list_rulesets(owner, name, runner=run_gh):
    return api_json(f"repos/{owner}/{name}/rulesets", runner=runner) or []


def get_ruleset(owner, name, ruleset_id, runner=run_gh):
    return api_json(f"repos/{owner}/{name}/rulesets/{ruleset_id}", runner=runner)


def create_ruleset(owner, name, runner=run_gh):
    return api_json(
        f"repos/{owner}/{name}/rulesets",
        method="POST",
        payload=desired_ruleset(),
        runner=runner,
    )


def delete_ruleset(owner, name, ruleset_id, runner=run_gh):
    api_json(
        f"repos/{owner}/{name}/rulesets/{ruleset_id}",
        method="DELETE",
        payload=None,
        runner=runner,
    )


def plan(cfg, runner=run_gh):
    owner = cfg["owner"]
    items = []
    for item in cfg["repositories"]:
        name = item["name"]
        info = repo_info(owner, name, runner=runner)
        visibility = info.get("visibility")
        archived = bool(info.get("archived"))

        if archived:
            items.append({"repo": f"{owner}/{name}", "action": "skip_archived"})
            continue
        if visibility != "public":
            items.append({"repo": f"{owner}/{name}", "action": "skip_non_public", "visibility": visibility})
            continue

        rulesets = list_rulesets(owner, name, runner=runner)
        named = [r for r in rulesets if r.get("name") == RULESET_NAME]
        if not named:
            items.append({"repo": f"{owner}/{name}", "action": "create"})
            continue
        if len(named) > 1:
            raise BranchSafetyError(f"Multiple {RULESET_NAME!r} rulesets on {owner}/{name}")

        full = get_ruleset(owner, name, named[0]["id"], runner=runner)
        if ruleset_matches(full):
            items.append({"repo": f"{owner}/{name}", "action": "no_change", "ruleset_id": named[0]["id"]})
        else:
            raise BranchSafetyError(
                f"Existing {RULESET_NAME!r} ruleset differs on {owner}/{name}; refusing overwrite"
            )
    return items


def apply(cfg, dry_run=False, runner=run_gh):
    items = plan(cfg, runner=runner)
    if dry_run:
        return {"dry_run": True, "plan": items}

    owner = cfg["owner"]
    created = []
    rollback_errors = []

    try:
        for item in items:
            if item["action"] != "create":
                continue
            name = item["repo"].split("/", 1)[1]
            result = create_ruleset(owner, name, runner=runner)
            ruleset_id = result.get("id")
            if not ruleset_id:
                raise BranchSafetyError(f"Ruleset creation returned no id for {item['repo']}")
            created.append({"repo": item["repo"], "ruleset_id": ruleset_id})

            verify = get_ruleset(owner, name, ruleset_id, runner=runner)
            if not ruleset_matches(verify):
                raise BranchSafetyError(f"Ruleset readback mismatch for {item['repo']}")
    except Exception as original_error:
        for created_item in reversed(created):
            repo = created_item["repo"]
            name = repo.split("/", 1)[1]
            ruleset_id = created_item["ruleset_id"]
            try:
                delete_ruleset(owner, name, ruleset_id, runner=runner)
                remaining = list_rulesets(owner, name, runner=runner)
                if any(item.get("id") == ruleset_id for item in remaining):
                    rollback_errors.append(f"{repo}: ruleset {ruleset_id} still present")
            except Exception as rollback_error:
                rollback_errors.append(f"{repo}: {rollback_error}")

        if rollback_errors:
            raise BranchSafetyError(
                f"{original_error}; rollback incomplete: " + "; ".join(rollback_errors)
            ) from original_error
        raise

    return {"dry_run": False, "created": created, "plan": items}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        if args.validate_only:
            print("Branch-safety configuration valid.")
            return 0
        result = apply(cfg, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BranchSafetyError, json.JSONDecodeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
