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
        self.profile_nodes = []
        self.live_repo_names = sorted(repo.split('/', 1)[1] for repo in states)

    def __call__(self, args, capture=True):
        if args[:2] == ["auth", "status"]:
            return ""

        if args[:3] == ["repo", "list", "Yolol100"]:
            return json.dumps([{"name": name} for name in self.live_repo_names])

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

        if args[:2] == ["api", "graphql"]:
            return json.dumps({
                "data": {
                    "user": {
                        "pinnedItems": {
                            "nodes": self.profile_nodes
                        }
                    }
                }
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
            "schema_version": 1,
            "owner": "Yolol100",
            "profile": {
                "desired_pins": ["One", "Two"]
            },
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

    def test_normalize_state_handles_null_topics(self):
        raw = {
            "description": None,
            "homepageUrl": None,
            "repositoryTopics": None,
        }
        self.assertEqual(
            ga.normalize_state(raw),
            {"description": "", "homepage": "", "topics": []},
        )

    def test_validate_accepts_valid_config(self):
        cfg = self.config()
        self.assertEqual(ga.validate(cfg), cfg)

    def test_validate_accepts_description_only_entry(self):
        cfg = self.config()
        cfg["repositories"][0] = {
            "name": "One",
            "description": "Description only",
        }
        self.assertEqual(ga.validate(cfg), cfg)

    def test_validate_rejects_entry_without_managed_fields(self):
        cfg = self.config()
        cfg["repositories"][0] = {"name": "One"}
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_validate_rejects_workflow_owner_mismatch(self):
        cfg = self.config()
        with patch.dict(ga.os.environ, {"GITHUB_REPOSITORY_OWNER": "OtherOwner"}, clear=False):
            with self.assertRaises(ga.ConfigError):
                ga.validate(cfg)

    def test_validate_rejects_missing_schema_version(self):
        cfg = self.config()
        del cfg["schema_version"]
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

    def test_validate_rejects_more_than_six_pins(self):
        cfg = self.config()
        cfg["profile"]["desired_pins"] = [f"Repo-{i}" for i in range(7)]
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_validate_rejects_pin_not_in_repositories(self):
        cfg = self.config()
        cfg["profile"]["desired_pins"] = ["One", "Missing"]
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_validate_rejects_duplicate_pins(self):
        cfg = self.config()
        cfg["profile"]["desired_pins"] = ["One", "One"]
        with self.assertRaises(ga.ConfigError):
            ga.validate(cfg)

    def test_profile_pin_state_matches_exact_order(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        fake.profile_nodes = [
            {"__typename": "Repository", "nameWithOwner": "Yolol100/One"},
            {"__typename": "Repository", "nameWithOwner": "Yolol100/Two"},
        ]
        state = ga.profile_pin_state(cfg, runner=fake)
        self.assertTrue(state["matches"])
        self.assertFalse(state["write_supported"])

    def test_profile_pin_state_detects_wrong_order(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        fake.profile_nodes = [
            {"__typename": "Repository", "nameWithOwner": "Yolol100/Two"},
            {"__typename": "Repository", "nameWithOwner": "Yolol100/One"},
        ]
        state = ga.profile_pin_state(cfg, runner=fake)
        self.assertFalse(state["matches"])

    def test_profile_pin_state_detects_gist(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        fake.profile_nodes = [
            {"__typename": "Gist", "name": "example", "url": "https://gist.github.com/example"},
        ]
        state = ga.profile_pin_state(cfg, runner=fake)
        self.assertFalse(state["matches"])
        self.assertTrue(state["current"][0].startswith("gist:"))

    def test_repository_inventory_matches_exact_config(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
        })
        state = ga.repository_inventory_state(cfg, runner=fake)
        self.assertTrue(state["matches"])
        self.assertEqual(state["missing_from_config"], [])
        self.assertEqual(state["missing_from_github"], [])

    def test_repository_inventory_detects_unconfigured_live_repo(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
            "Yolol100/Two": repo_state(),
            "Yolol100/Three": repo_state(),
        })
        state = ga.repository_inventory_state(cfg, runner=fake)
        self.assertFalse(state["matches"])
        self.assertEqual(state["missing_from_config"], ["Three"])
        self.assertEqual(state["missing_from_github"], [])

    def test_repository_inventory_detects_stale_config_repo(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state(),
        })
        state = ga.repository_inventory_state(cfg, runner=fake)
        self.assertFalse(state["matches"])
        self.assertEqual(state["missing_from_config"], [])
        self.assertEqual(state["missing_from_github"], ["Two"])

    def test_repository_drift_state_matches_exact_state(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": ga.desired_state(cfg["repositories"][0]),
            "Yolol100/Two": ga.desired_state(cfg["repositories"][1]),
        })
        state = ga.repository_drift_state(cfg, runner=fake)
        self.assertTrue(state["matches"])
        self.assertTrue(all(item["matches"] for item in state["repositories"]))
        self.assertEqual(fake.edit_calls, [])

    def test_repository_drift_state_detects_difference(self):
        cfg = self.config()
        fake = FakeRunner({
            "Yolol100/One": repo_state("wrong", "https://example.com/one", ["php", "wordpress"]),
            "Yolol100/Two": ga.desired_state(cfg["repositories"][1]),
        })
        state = ga.repository_drift_state(cfg, runner=fake)
        self.assertFalse(state["matches"])
        self.assertFalse(state["repositories"][0]["matches"])
        self.assertTrue(state["repositories"][1]["matches"])
        self.assertEqual(fake.edit_calls, [])

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

    def test_description_only_preserves_unmanaged_metadata(self):
        cfg = {
            "schema_version": 1,
            "owner": "Yolol100",
            "profile": {"desired_pins": ["One"]},
            "repositories": [{
                "name": "One",
                "description": "New description",
            }],
        }
        original = repo_state(
            "Old description",
            "https://keep.example",
            ["keep", "untouched"],
        )
        fake = FakeRunner({"Yolol100/One": original})
        ga.apply_all(cfg, runner=fake)

        self.assertEqual(
            fake.states["Yolol100/One"],
            repo_state(
                "New description",
                "https://keep.example",
                ["keep", "untouched"],
            ),
        )
        args = fake.edit_calls[0]
        self.assertIn("--description", args)
        self.assertNotIn("--homepage", args)
        self.assertNotIn("--add-topic", args)
        self.assertNotIn("--remove-topic", args)

    def test_topics_are_reconciled_exactly(self):
        cfg = {
            "schema_version": 1,
            "owner": "Yolol100",
            "profile": {"desired_pins": ["One"]},
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
