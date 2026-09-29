import importlib.util
import json
import pathlib
import unittest
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "apply-github-admin.py"
SPEC = importlib.util.spec_from_file_location("github_admin", SCRIPT)
ga = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ga)


def repo_state(description="", homepage="", topics=None):
    return {
        "description": description,
        "homepage": homepage,
        "topics": sorted(topics or []),
    }


class FakeRunner:
    def __init__(self, states):
        self.states = {k: dict(v, topics=list(v["topics"])) for k, v in states.items()}
        self.edit_calls = []
        self.view_counts = {}
        self.fail_edit_repo = None
        self.fail_view_repo = None
        self.mutate_on_second_view = None

    def __call__(self, args, capture=True):
        if args[:2] == ["auth", "status"]:
            return ""

        if args[:2] == ["repo", "view"]:
            repo = args[2]
            self.view_counts[repo] = self.view_counts.get(repo, 0) + 1

            if repo == self.fail_view_repo:
                raise ga.GhError("view failed")

            if repo == self.mutate_on_second_view and self.view_counts[repo] == 2:
                self.states[repo]["description"] = "external change"

            state = self.states[repo]
            return json.dumps({
                "nameWithOwner": repo,
                "description": state["description"],
                "homepageUrl": state["homepage"],
                "repositoryTopics": [{"name": t} for t in state["topics"]],
            })

        if args[:2] == ["repo", "edit"]:
            repo = args[2]
            self.edit_calls.append(list(args))
            if repo == self.fail_edit_repo:
                raise ga.GhError("edit failed")

            state = self.states[repo]
            i = 3
            while i < len(args):
                flag = args[i]
                value = args[i + 1]
                if flag == "--description":
                    state["description"] = value
                elif flag == "--homepage":
                    state["homepage"] = value
                elif flag == "--remove-topic":
                    state["topics"] = [t for t in state["topics"] if t != value]
                elif flag == "--add-topic":
                    if value not in state["topics"]:
                        state["topics"].append(value)
                else:
                    raise AssertionError(f"Unexpected flag {flag}")
                i += 2
            state["topics"] = sorted(state["topics"])
            return ""

        raise AssertionError(f"Unexpected gh args: {args}")


class GitHubAdminTests(unittest.TestCase):
    def config(self):
        return {
            "owner": "Yolol100",
            "repositories": [
                {
                    "name": "One",
                    "description": "One description",
                    "homepage": "https://example.com/one",
                    "topics": ["php", "wordpress"],
                },
                {
                    "name": "Two",
                    "description": "Two description",
                    "homepage": "https://example.com/two",
                    "topics": ["ci", "testing"],
                },
            ],
        }

    def test_validate_accepts_valid_config(self):
        cfg = self.config()
        self.assertEqual(ga.validate(cfg), cfg)

    def test_validate_rejects_workflow_owner_mismatch(self):
        cfg = self.config()
        with patch.dict(ga.os.environ, {"GITHUB_REPOSITORY_OWNER": "OtherOwner"}, clear=False):
            with self.assertRaises(ga.ConfigError):
                ga.validate(cfg)

    def test_validate_rejects_duplicate_repo(self):
        cfg = self.config()
        cfg["repositories"].append(dict(cfg["repositories"][0]))
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_validate_rejects_invalid_topic(self):
        cfg = self.config()
        cfg["repositories"][0]["topics"] = ["Not-Lowercase"]
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_validate_rejects_more_than_twenty_topics(self):
        cfg = self.config()
        cfg["repositories"][0]["topics"] = [f"topic-{i}" for i in range(21)]
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_validate_rejects_non_http_homepage(self):
        cfg = self.config()
        cfg["repositories"][0]["homepage"] = "javascript:alert(1)"
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_dry_run_has_no_writes(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        result = ga.apply_all(cfg, runner=fake, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(fake.edit_calls, [])
        self.assertTrue(all(x["change_required"] for x in result["plan"]))

    def test_idempotent_state_produces_no_write(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": ga.desired_state(cfg["repositories"][0]),
            "Yolol100/Two": ga.desired_state(cfg["repositories"][1]),
        })
        result = ga.apply_all(cfg, runner=fake)
        self.assertEqual(result["modified"], [])
        self.assertEqual(fake.edit_calls, [])

    def test_topics_are_reconciled_exactly(self):
        cfg = {
            "owner": "Yolol100",
            "repositories": [{
                "name": "One",
                "description": "New",
                "homepage": "https://example.com",
                "topics": ["keep", "new"],
            }],
        }
        fake = FakeRunner({
            "Yolol100/One": repo_state("Old", "https://old.example", ["keep", "remove"]),
        })
        ga.apply_all(cfg, runner=fake)
        self.assertEqual(fake.states["Yolol100/One"], repo_state("New", "https://example.com", ["keep", "new"]))
        args = fake.edit_calls[0]
        self.assertIn("--remove-topic", args)
        self.assertIn("remove", args)
        self.assertIn("--add-topic", args)
        self.assertIn("new", args)

    def test_preflight_failure_makes_no_writes(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        fake.fail_view_repo = "Yolol100/Two"
        with self.assertRaises(ga.GhError):
            ga.apply_all(cfg, runner=fake)
        self.assertEqual(fake.edit_calls, [])

    def test_stale_state_blocks_write(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        fake.mutate_on_second_view = "Yolol100/One"
        with self.assertRaises(ga.GhError):
            ga.apply_all(cfg, runner=fake)
        self.assertEqual(fake.edit_calls, [])

    def test_failure_rolls_back_earlier_repository(self):
        cfg = self.config()
        baseline_one = repo_state("old one", "https://old.example/one", ["old"])
        baseline_two = repo_state("old two", "https://old.example/two", ["old"])
        fake = FakeRunner({
            "Yolol100/One": baseline_one,
            "Yolol100/Two": baseline_two,
        })
        fake.fail_edit_repo = "Yolol100/Two"

        with self.assertRaises(ga.GhError):
            ga.apply_all(cfg, runner=fake)

        self.assertEqual(fake.states["Yolol100/One"], baseline_one)
        self.assertEqual(fake.states["Yolol100/Two"], baseline_two)


if __name__ == "__main__":
    unittest.main()
