import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "audit-github-governance.py"
SPEC = importlib.util.spec_from_file_location("github_governance", SCRIPT)
ga = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ga)


class GovernanceAuditTests(unittest.TestCase):
    def test_unprotected_summary(self):
        self.assertEqual(
            ga.protection_summary(None),
            {
                "access": "available",
                "access_error": "",
                "protected": False,
                "pull_request_reviews": False,
                "required_status_checks": [],
                "conversation_resolution": False,
                "force_pushes_allowed": None,
                "deletions_allowed": None,
                "enforce_admins": False,
            },
        )

    def test_protected_summary(self):
        raw = {
            "required_pull_request_reviews": {"required_approving_review_count": 1},
            "required_status_checks": {
                "contexts": ["validate"],
                "checks": [{"context": "security"}],
            },
            "required_conversation_resolution": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "enforce_admins": {"enabled": True},
        }
        state = ga.protection_summary(raw)
        self.assertEqual(state["access"], "available")
        self.assertTrue(state["protected"])
        self.assertTrue(state["pull_request_reviews"])
        self.assertEqual(state["required_status_checks"], ["security", "validate"])
        self.assertTrue(state["conversation_resolution"])
        self.assertFalse(state["force_pushes_allowed"])
        self.assertFalse(state["deletions_allowed"])
        self.assertTrue(state["enforce_admins"])

    def test_blocked_protection_summary(self):
        state = ga.protection_summary({"_access_error": "HTTP 403"})
        self.assertEqual(state["access"], "blocked")
        self.assertIsNone(state["protected"])
        self.assertIn("403", state["access_error"])

    def test_security_summary_handles_missing_fields(self):
        state = ga.security_summary({})
        self.assertIsNone(state["secret_scanning"])
        self.assertIsNone(state["secret_scanning_push_protection"])
        self.assertIsNone(state["dependabot_security_updates"])
        self.assertIsNone(state["advanced_security"])

    def test_build_report_aggregates(self):
        cfg = {
            "owner": "Yolol100",
            "repositories": [{"name": "One"}, {"name": "Two"}],
        }

        def fake_audit(owner, name, runner=None):
            return {
                "repo": f"{owner}/{name}",
                "visibility": "public",
                "archived": False,
                "default_branch": "main",
                "rulesets_access": "available",
                "rulesets_error": "",
                "rulesets_total": 1 if name == "One" else 0,
                "active_rulesets": ["Protect main"] if name == "One" else [],
                "protection": {
                    "protected": name == "One",
                    "pull_request_reviews": name == "One",
                    "required_status_checks": ["validate"] if name == "One" else [],
                    "conversation_resolution": name == "One",
                    "force_pushes_allowed": False if name == "One" else None,
                    "deletions_allowed": False if name == "One" else None,
                    "enforce_admins": name == "One",
                },
                "security": {
                    "secret_scanning": "enabled" if name == "One" else None,
                    "secret_scanning_push_protection": "enabled" if name == "One" else None,
                    "dependabot_security_updates": None,
                    "advanced_security": None,
                },
            }

        original = ga.audit_repository
        ga.audit_repository = fake_audit
        try:
            report = ga.build_report(cfg, runner=lambda args: "")
        finally:
            ga.audit_repository = original

        self.assertEqual(report["summary"]["repository_count"], 2)
        self.assertEqual(report["summary"]["protected_count"], 1)
        self.assertEqual(report["summary"]["unprotected"], ["Yolol100/Two"])
        self.assertEqual(report["summary"]["with_active_rulesets"], ["Yolol100/One"])


if __name__ == "__main__":
    unittest.main()
