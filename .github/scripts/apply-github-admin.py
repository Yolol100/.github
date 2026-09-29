#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TOPIC_RE = re.compile(r"^[a-z0-9-]{1,50}$")


def run_gh(args, capture=True):
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        raise SystemExit("GH_TOKEN is required")
    result = subprocess.run(
        ["gh", *args],
        check=False,
        text=True,
        capture_output=capture,
        env=env,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout.strip() if capture else ""


def validate(cfg):
    owner = cfg.get("owner")
    if not owner or not OWNER_RE.fullmatch(owner):
        raise SystemExit("Invalid owner in github-admin.json")

    repos = cfg.get("repositories")
    if not isinstance(repos, list) or not repos:
        raise SystemExit("repositories must be a non-empty list")

    seen = set()
    for item in repos:
        name = item.get("name")
        if not name or not REPO_RE.fullmatch(name):
            raise SystemExit(f"Invalid repository name: {name!r}")
        if name in seen:
            raise SystemExit(f"Duplicate repository entry: {name}")
        seen.add(name)

        description = item.get("description")
        homepage = item.get("homepage")
        topics = item.get("topics")

        if not isinstance(description, str) or len(description) > 350:
            raise SystemExit(f"Invalid description for {name}")
        if not isinstance(homepage, str) or not homepage.startswith(("https://", "http://")):
            raise SystemExit(f"Invalid homepage for {name}")
        if not isinstance(topics, list) or len(topics) > 20:
            raise SystemExit(f"Invalid topics for {name}")
        if len(topics) != len(set(topics)):
            raise SystemExit(f"Duplicate topic for {name}")
        for topic in topics:
            if not isinstance(topic, str) or not TOPIC_RE.fullmatch(topic):
                raise SystemExit(f"Invalid topic for {name}: {topic!r}")


def apply_repo(owner, item):
    repo = f"{owner}/{item['name']}"
    raw = run_gh([
        "repo", "view", repo,
        "--json", "nameWithOwner,description,homepageUrl,repositoryTopics"
    ])
    current = json.loads(raw)
    current_topics = sorted(x["name"] for x in current.get("repositoryTopics", []))
    desired_topics = sorted(item["topics"])

    args = [
        "repo", "edit", repo,
        "--description", item["description"],
        "--homepage", item["homepage"],
    ]

    for topic in current_topics:
        if topic not in desired_topics:
            args.extend(["--remove-topic", topic])
    for topic in desired_topics:
        if topic not in current_topics:
            args.extend(["--add-topic", topic])

    print(f"Applying {repo}")
    run_gh(args, capture=False)

    verify_raw = run_gh([
        "repo", "view", repo,
        "--json", "nameWithOwner,description,homepageUrl,repositoryTopics"
    ])
    verify = json.loads(verify_raw)
    verify_topics = sorted(x["name"] for x in verify.get("repositoryTopics", []))

    errors = []
    if verify.get("description") != item["description"]:
        errors.append("description")
    if (verify.get("homepageUrl") or "") != item["homepage"]:
        errors.append("homepage")
    if verify_topics != desired_topics:
        errors.append("topics")

    if errors:
        raise SystemExit(f"Readback mismatch for {repo}: {', '.join(errors)}")

    print(f"Verified {repo}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply-github-admin.py <config.json>")

    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    validate(cfg)

    run_gh(["auth", "status", "--hostname", "github.com"], capture=False)

    for item in cfg["repositories"]:
        apply_repo(cfg["owner"], item)

    print("All configured repositories applied and verified.")


if __name__ == "__main__":
    main()
