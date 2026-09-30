import importlib.util
import json
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "apply-github-branch-safety.py"
SPEC = importlib.util.spec_from_file_location("github_branch_safety", SCRIPT)
bs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bs)


class FakeRunner:
    def __init__(self):
        self.repos = {}
        self.rulesets = {}
        self.calls = []
        self.next_id = 100

    def add_repo(self, name, visibility="public", archived=False, rulesets=None):
        self.repos[name] = {"visibility": visibility, "archived": archived}
        self.rulesets[name] = list(rulesets or [])

    def __call__(self, args, input_text=None):
        self.calls.append((list(args), input_text))
        path = args[1]
        method = "GET"
        if "--method" in args:
            method = args[args.index("--method") + 1]

        parts = path.split("/")
        name = parts[2]

        if len(parts) == 3:
            return json.dumps(self.repos[name])

        if len(parts) == 4 and parts[3] == "rulesets":
            if method == "GET":
                return json.dumps([
                    {"id": r["id"], "name": r["name"]} for r in self.rulesets[name]
                ])
            payload = json.loads(input_text)
            self.next_id += 1
            created = {"id": self.next_id, **payload}
            self.rulesets[name].append(created)
            return json.dumps(created)

        if len(parts) == 5 and parts[3] == "rulesets":
            ruleset_id = int(parts[4])
            for item in self.rulesets[name]:
                if item["id"] == ruleset_id:
                    return json.dumps(item)
            raise AssertionError("ruleset not found")

        raise AssertionError(f"unexpected path: {path}")


def config(*names):
    return {
        "schema_version": 1,
        "owner": "Yolol100",
        "repositories": [{"name": name, "description": "x"} for name in names],
    }


class BranchSafetyTests(unittest.TestCase):
    def test_desired_ruleset_is_minimal_default_branch_protection(self):
        desired = bs.desired_ruleset()
        self.assertEqual(desired["conditions"]["ref_name"]["include"], ["~DEFAULT_BRANCH"])
        self.assertEqual(
            sorted(rule["type"] for rule in desired["rules"]),
            ["deletion", "non_fast_forward"],
        )
        self.assertEqual(desired["bypass_actors"], [])

    def test_dry_run_creates_only_missing_public_ruleset(self):
        fake = FakeRunner()
        fake.add_repo("One")
        fake.add_repo("Two", rulesets=[{"id": 7, **bs.desired_ruleset()}])
        result = bs.apply(config("One", "Two"), dry_run=True, runner=fake)
        self.assertEqual([x["action"] for x in result["plan"]], ["create", "no_change"])

    def test_non_public_repository_is_skipped(self):
        fake = FakeRunner()
        fake.add_repo("Private", visibility="private")
        result = bs.apply(config("Private"), dry_run=True, runner=fake)
        self.assertEqual(result["plan"][0]["action"], "skip_non_public")

    def test_archived_repository_is_skipped(self):
        fake = FakeRunner()
        fake.add_repo("Old", archived=True)
        result = bs.apply(config("Old"), dry_run=True, runner=fake)
        self.assertEqual(result["plan"][0]["action"], "skip_archived")

    def test_conflicting_named_ruleset_fails_closed(self):
        fake = FakeRunner()
        bad = bs.desired_ruleset()
        bad["rules"] = [{"type": "deletion"}]
        fake.add_repo("One", rulesets=[{"id": 7, **bad}])
        with self.assertRaises(bs.BranchSafetyError):
            bs.apply(config("One"), dry_run=True, runner=fake)

    def test_apply_creates_and_verifies(self):
        fake = FakeRunner()
        fake.add_repo("One")
        result = bs.apply(config("One"), runner=fake)
        self.assertEqual(len(result["created"]), 1)
        created = fake.rulesets["One"][0]
        self.assertTrue(bs.ruleset_matches(created))


if __name__ == "__main__":
    unittest.main()
