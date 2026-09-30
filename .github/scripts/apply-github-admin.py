#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TOPIC_RE = re.compile(r"^[a-z0-9-]{1,50}$")


class ConfigError(ValueError):
    pass


class GhError(RuntimeError):
    pass


def run_gh(args, capture=True):
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        raise GhError("GH_TOKEN is required for GitHub reads/writes")
    result = subprocess.run(
        ["gh", *args],
        check=False,
        text=True,
        capture_output=capture,
        env=env,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise GhError(details or f"gh command failed with exit code {result.returncode}")
    return result.stdout.strip() if capture else ""


def validate(cfg):
    if cfg.get("schema_version") != 1:
        raise ConfigError("Unsupported or missing schema_version; expected 1")

    owner = cfg.get("owner")
    if not owner or not OWNER_RE.fullmatch(owner):
        raise ConfigError("Invalid owner in github-admin.json")

    expected_owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if expected_owner and owner.lower() != expected_owner.lower():
        raise ConfigError(
            f"Config owner {owner!r} does not match workflow repository owner {expected_owner!r}"
        )

    repos = cfg.get("repositories")
    if not isinstance(repos, list) or not repos:
        raise ConfigError("repositories must be a non-empty list")

    profile = cfg.get("profile", {})
    if not isinstance(profile, dict):
        raise ConfigError("profile must be an object")
    pins = profile.get("desired_pins", [])
    if not isinstance(pins, list) or len(pins) > 6:
        raise ConfigError("profile.desired_pins must be a list with at most six repositories")
    if len(pins) != len(set(pins)):
        raise ConfigError("profile.desired_pins contains duplicates")
    for pin in pins:
        if not isinstance(pin, str) or not REPO_RE.fullmatch(pin):
            raise ConfigError(f"Invalid desired profile pin: {pin!r}")

    seen = set()
    for item in repos:
        if not isinstance(item, dict):
            raise ConfigError("Every repository entry must be an object")

        name = item.get("name")
        if not name or not REPO_RE.fullmatch(name):
            raise ConfigError(f"Invalid repository name: {name!r}")
        if name in seen:
            raise ConfigError(f"Duplicate repository entry: {name}")
        seen.add(name)

        managed_fields = ("description", "homepage", "topics")
        if not any(field in item for field in managed_fields):
            raise ConfigError(
                f"Repository {name} must manage at least one of: description, homepage, topics"
            )

        if "description" in item:
            description = item["description"]
            if not isinstance(description, str) or len(description) > 350:
                raise ConfigError(f"Invalid description for {name}")

        if "homepage" in item:
            homepage = item["homepage"]
            if (
                not isinstance(homepage, str)
                or (homepage and not homepage.startswith(("https://", "http://")))
            ):
                raise ConfigError(f"Invalid homepage for {name}")

        if "topics" in item:
            topics = item["topics"]
            if not isinstance(topics, list) or len(topics) > 20:
                raise ConfigError(f"Invalid topics for {name}")
            if len(topics) != len(set(topics)):
                raise ConfigError(f"Duplicate topic for {name}")
            for topic in topics:
                if not isinstance(topic, str) or not TOPIC_RE.fullmatch(topic):
                    raise ConfigError(f"Invalid topic for {name}: {topic!r}")

    missing_pins = [pin for pin in pins if pin not in seen]
    if missing_pins:
        raise ConfigError(
            "profile.desired_pins must reference configured repositories: "
            + ", ".join(missing_pins)
        )

    return cfg


def normalize_state(raw):
    return {
        "description": raw.get("description") or "",
        "homepage": raw.get("homepageUrl") or "",
        "topics": sorted(x["name"] for x in (raw.get("repositoryTopics") or [])),
    }


def desired_state(item, current=None):
    target = dict(current or {
        "description": "",
        "homepage": "",
        "topics": [],
    })
    target["topics"] = list(target.get("topics", []))

    if "description" in item:
        target["description"] = item["description"]
    if "homepage" in item:
        target["homepage"] = item["homepage"]
    if "topics" in item:
        target["topics"] = sorted(item["topics"])
    else:
        target["topics"] = sorted(target["topics"])

    return target


def get_repo_state(repo, runner=run_gh):
    raw = runner([
        "repo", "view", repo,
        "--json", "nameWithOwner,description,homepageUrl,repositoryTopics"
    ])
    return normalize_state(json.loads(raw))


def build_edit_args(repo, current, target):
    args = ["repo", "edit", repo]

    if current["description"] != target["description"]:
        args.extend(["--description", target["description"]])
    if current["homepage"] != target["homepage"]:
        args.extend(["--homepage", target["homepage"]])

    for topic in current["topics"]:
        if topic not in target["topics"]:
            args.extend(["--remove-topic", topic])
    for topic in target["topics"]:
        if topic not in current["topics"]:
            args.extend(["--add-topic", topic])

    if len(args) == 3:
        raise GhError(f"No repository edit required for {repo}")

    return args


def states_equal(left, right):
    return left == right


def preflight(cfg, runner=run_gh):
    runner(["auth", "status", "--hostname", "github.com"], capture=False)
    baseline = {}
    owner = cfg["owner"]
    for item in cfg["repositories"]:
        repo = f"{owner}/{item['name']}"
        baseline[repo] = get_repo_state(repo, runner)
    return baseline


def apply_all(cfg, runner=run_gh, dry_run=False):
    baseline = preflight(cfg, runner)
    owner = cfg["owner"]

    if dry_run:
        plan = []
        for item in cfg["repositories"]:
            repo = f"{owner}/{item['name']}"
            current = baseline[repo]
            target = desired_state(item, current)
            plan.append({
                "repo": repo,
                "change_required": not states_equal(current, target),
                "current": current,
                "target": target,
            })
        return {"dry_run": True, "plan": plan}

    modified = []
    rollback_errors = []

    try:
        for item in cfg["repositories"]:
            repo = f"{owner}/{item['name']}"
            baseline_state = baseline[repo]
            target = desired_state(item, baseline_state)

            fresh = get_repo_state(repo, runner)
            if not states_equal(fresh, baseline_state):
                raise GhError(f"State changed after preflight for {repo}; refusing stale write")

            if states_equal(fresh, target):
                print(f"No change {repo}")
                continue

            runner(build_edit_args(repo, fresh, target), capture=False)
            modified.append(repo)

            verify = get_repo_state(repo, runner)
            if not states_equal(verify, target):
                raise GhError(f"Readback mismatch for {repo}")

            print(f"Verified {repo}")

    except Exception as original_error:
        for repo in reversed(modified):
            try:
                current = get_repo_state(repo, runner)
                original = baseline[repo]
                if not states_equal(current, original):
                    runner(build_edit_args(repo, current, original), capture=False)
                restored = get_repo_state(repo, runner)
                if not states_equal(restored, original):
                    rollback_errors.append(f"{repo}: readback mismatch")
            except Exception as rollback_error:
                rollback_errors.append(f"{repo}: {rollback_error}")

        if rollback_errors:
            raise GhError(
                f"{original_error}; rollback incomplete: " + "; ".join(rollback_errors)
            ) from original_error
        raise

    return {"dry_run": False, "modified": modified}


def profile_pin_state(cfg, runner=run_gh):
    owner = cfg["owner"]
    desired = [f"{owner}/{name}" for name in cfg.get("profile", {}).get("desired_pins", [])]
    query = (
        "query($login:String!){user(login:$login){"
        "pinnedItems(first:6){nodes{__typename "
        "... on Repository{nameWithOwner} "
        "... on Gist{name url}}}}}"
    )
    raw = runner([
        "api", "graphql",
        "-f", f"query={query}",
        "-F", f"login={owner}",
    ])
    payload = json.loads(raw)
    user = payload.get("data", {}).get("user")
    if not user:
        raise GhError(f"GitHub GraphQL returned no user for {owner}")

    current = []
    for node in user.get("pinnedItems", {}).get("nodes", []):
        if node.get("__typename") == "Repository":
            current.append(node.get("nameWithOwner"))
        elif node.get("__typename") == "Gist":
            current.append(f"gist:{node.get('url') or node.get('name')}")
        else:
            current.append(f"unknown:{node.get('__typename')}")

    return {
        "owner": owner,
        "desired": desired,
        "current": current,
        "matches": current == desired,
        "write_supported": False,
        "write_method": "GitHub profile > Customize your pins",
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Path to github-admin.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--check-pins", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        validate(cfg)

        if args.validate_only:
            print("Configuration valid.")
            return 0

        if args.check_pins:
            state = profile_pin_state(cfg)
            print(json.dumps(state, indent=2, sort_keys=True))
            return 0 if state["matches"] else 2

        result = apply_all(cfg, dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("All configured repositories applied and verified.")
        return 0

    except (ConfigError, GhError, json.JSONDecodeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
