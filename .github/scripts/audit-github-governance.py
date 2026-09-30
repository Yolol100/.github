#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class AuditError(RuntimeError):
    pass


def run_gh(args):
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        raise AuditError("GH_TOKEN is required for governance audit")
    result = subprocess.run(
        ["gh", *args],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode != 0:
        raise AuditError((result.stderr or result.stdout or "").strip())
    return result.stdout.strip()


def api_json(path, runner=run_gh):
    raw = runner(["api", path])
    return json.loads(raw) if raw else None


def optional_api_json(path, runner=run_gh):
    try:
        return api_json(path, runner)
    except AuditError as exc:
        message = str(exc)
        if "HTTP 404" in message or "Not Found" in message:
            return None
        if "HTTP 403" in message or "Resource not accessible" in message or "Upgrade to GitHub Pro" in message:
            return {"_access_error": message}
        raise


def protection_summary(raw):
    if isinstance(raw, dict) and raw.get("_access_error"):
        return {
            "access": "blocked",
            "access_error": raw["_access_error"],
            "protected": None,
            "pull_request_reviews": None,
            "required_status_checks": [],
            "conversation_resolution": None,
            "force_pushes_allowed": None,
            "deletions_allowed": None,
            "enforce_admins": None,
        }

    if not raw:
        return {
            "access": "available",
            "access_error": "",
            "protected": False,
            "pull_request_reviews": False,
            "required_status_checks": [],
            "conversation_resolution": False,
            "force_pushes_allowed": None,
            "deletions_allowed": None,
            "enforce_admins": False,
        }

    checks = raw.get("required_status_checks") or {}
    contexts = checks.get("contexts") or []
    named_checks = [
        item.get("context")
        for item in (checks.get("checks") or [])
        if isinstance(item, dict) and item.get("context")
    ]

    return {
        "access": "available",
        "access_error": "",
        "protected": True,
        "pull_request_reviews": bool(raw.get("required_pull_request_reviews")),
        "required_status_checks": sorted(set(contexts + named_checks)),
        "conversation_resolution": bool(
            (raw.get("required_conversation_resolution") or {}).get("enabled")
        ),
        "force_pushes_allowed": (raw.get("allow_force_pushes") or {}).get("enabled"),
        "deletions_allowed": (raw.get("allow_deletions") or {}).get("enabled"),
        "enforce_admins": bool((raw.get("enforce_admins") or {}).get("enabled")),
    }


def security_summary(raw):
    sec = raw.get("security_and_analysis") or {}

    def status(name):
        value = sec.get(name)
        if not isinstance(value, dict):
            return None
        return value.get("status")

    return {
        "secret_scanning": status("secret_scanning"),
        "secret_scanning_push_protection": status("secret_scanning_push_protection"),
        "dependabot_security_updates": status("dependabot_security_updates"),
        "advanced_security": status("advanced_security"),
    }


def audit_repository(owner, name, runner=run_gh):
    repo = f"{owner}/{name}"
    metadata = api_json(f"repos/{repo}", runner) or {}
    default_branch = metadata.get("default_branch") or "main"

    branch_raw = optional_api_json(f"repos/{repo}/branches/{default_branch}", runner)
    branch_access = "available"
    branch_error = ""
    if isinstance(branch_raw, dict) and branch_raw.get("_access_error"):
        branch_access = "blocked"
        branch_error = branch_raw["_access_error"]
        branch = {}
    else:
        branch = branch_raw or {}
    protection = optional_api_json(
        f"repos/{repo}/branches/{default_branch}/protection",
        runner,
    )
    rulesets_raw = optional_api_json(f"repos/{repo}/rulesets", runner)
    rulesets_access = "available"
    rulesets_error = ""
    if isinstance(rulesets_raw, dict) and rulesets_raw.get("_access_error"):
        rulesets_access = "blocked"
        rulesets_error = rulesets_raw["_access_error"]
        rulesets = []
    elif isinstance(rulesets_raw, list):
        rulesets = rulesets_raw
    else:
        rulesets = []

    result = {
        "repo": repo,
        "visibility": metadata.get("visibility"),
        "archived": bool(metadata.get("archived")),
        "default_branch": default_branch,
        "rulesets_access": rulesets_access,
        "rulesets_error": rulesets_error,
        "rulesets_total": len(rulesets),
        "active_rulesets": sorted(
            r.get("name", "")
            for r in rulesets
            if isinstance(r, dict) and r.get("enforcement") == "active"
        ),
        "default_branch_access": branch_access,
        "default_branch_error": branch_error,
        "default_branch_protected": None if branch_access == "blocked" else bool(branch.get("protected")),
        "classic_protection": protection_summary(protection),
        "security": security_summary(metadata),
    }
    return result


def build_report(cfg, runner=run_gh):
    owner = cfg["owner"]
    repositories = [
        audit_repository(owner, item["name"], runner)
        for item in cfg["repositories"]
    ]

    summary = {
        "repository_count": len(repositories),
        "protected_count": sum(
            1 for r in repositories if r["default_branch_protected"] is True
        ),
        "unprotected": [
            r["repo"] for r in repositories if r["default_branch_protected"] is False
        ],
        "default_branch_unavailable": [
            r["repo"] for r in repositories if r["default_branch_protected"] is None
        ],
        "classic_protection_unavailable": [
            r["repo"]
            for r in repositories
            if r["classic_protection"]["protected"] is None
        ],
        "with_active_rulesets": [
            r["repo"] for r in repositories if r["active_rulesets"]
        ],
        "secret_scanning_disabled_or_unknown": [
            r["repo"]
            for r in repositories
            if r["security"]["secret_scanning"] != "enabled"
        ],
        "push_protection_disabled_or_unknown": [
            r["repo"]
            for r in repositories
            if r["security"]["secret_scanning_push_protection"] != "enabled"
        ],
    }

    return {
        "schema_version": 1,
        "owner": owner,
        "summary": summary,
        "repositories": repositories,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        report = build_report(cfg)
        payload = json.dumps(report, indent=2, sort_keys=True)
        if args.output:
            Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    except (AuditError, json.JSONDecodeError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
