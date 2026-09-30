import importlib.util
import json
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "apply-github-public-security.py"
SPEC = importlib.util.spec_from_file_location("github_public_security", SCRIPT)
ps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ps)


class FakeRunner:
    def __init__(self):
        self.repos = {}
        self.calls = []

    def add_repo(self, name, visibility="public", archived=False, scanning=None, push=None):
        sec = {}
        if scanning is not None:
            sec["secret_scanning"] = {"status": scanning}
        if push is not None:
            sec["secret_scanning_push_protection"] = {"status": push}
        self.repos[name] = {
            "visibility": visibility,
            "archived": archived,
            "security_and_analysis": sec,
        }

    def __call__(self, args, input_text=None):
        self.calls.append((list(args), input_text))
        path = args[1]
        parts = path.split("/")
        name = parts[2]
        method = "GET"
        if "--method" in args:
            method = args[args.index("--method") + 1]

        if method == "GET":
            return json.dumps(self.repos[name])

        if method == "PATCH":
            payload = json.loads(input_text)
            sec = payload["security_and_analysis"]
            self.repos[name]["security_and_analysis"] = sec
            return json.dumps(self.repos[name])

        raise AssertionError(f"unexpected method: {method}")


def config(*names):
    return {
        "schema_version": 1,
        "owner": "Yolol100",
        "repositories": [{"name": name, "description": "x"} for name in names],
    }


class PublicSecurityTests(unittest.TestCase):
    def test_desired_payload_enables_secret_scanning_and_push_protection(self):
        sec = ps.desired_payload()["security_and_analysis"]
        self.assertEqual(sec["secret_scanning"]["status"], "enabled")
        self.assertEqual(sec["secret_scanning_push_protection"]["status"], "enabled")

    def test_dry_run_marks_missing_security_for_enable(self):
        fake = FakeRunner()
        fake.add_repo("One", scanning="disabled", push="disabled")
        result = ps.apply(config("One"), dry_run=True, runner=fake)
        self.assertEqual(result["plan"][0]["action"], "enable")

    def test_enabled_security_is_idempotent(self):
        fake = FakeRunner()
        fake.add_repo("One", scanning="enabled", push="enabled")
        result = ps.apply(config("One"), runner=fake)
        self.assertEqual(result["changed"], [])
        self.assertEqual(
            [call for call in fake.calls if "--method" in call[0]],
            [],
        )

    def test_private_repo_is_skipped(self):
        fake = FakeRunner()
        fake.add_repo("Private", visibility="private")
        result = ps.apply(config("Private"), dry_run=True, runner=fake)
        self.assertEqual(result["plan"][0]["action"], "skip_non_public")

    def test_archived_repo_is_skipped(self):
        fake = FakeRunner()
        fake.add_repo("Old", archived=True)
        result = ps.apply(config("Old"), dry_run=True, runner=fake)
        self.assertEqual(result["plan"][0]["action"], "skip_archived")

    def test_apply_enables_and_verifies(self):
        fake = FakeRunner()
        fake.add_repo("One", scanning=None, push=None)
        result = ps.apply(config("One"), runner=fake)
        self.assertEqual(result["changed"], ["Yolol100/One"])
        state = ps.security_status(fake.repos["One"])
        self.assertEqual(state["secret_scanning"], "enabled")
        self.assertEqual(state["secret_scanning_push_protection"], "enabled")


if __name__ == "__main__":
    unittest.main()
