"""Exhaustive adversarial attack probe matrix for the TermiNex Safety Kernel."""

import unittest
from terminex.safety.ast_validator import ASTSecurityValidator
from terminex.safety.risk_scorer import RiskScorer


class TestSafetyKernelProbes(unittest.TestCase):

    def setUp(self):
        self.validator = ASTSecurityValidator()
        self.scorer = RiskScorer()

    def test_sudo_root_delete_blocked(self):
        """sudo rm -rf / must be blocked with CRITICAL_DANGER."""
        res = self.validator.validate_command("sudo rm -rf /")
        self.assertFalse(res["valid"])
        self.assertTrue(res["is_dangerous"])
        risk = self.scorer.score_command("sudo rm -rf /", res)
        self.assertEqual(risk["tier"], 2)
        self.assertFalse(risk["can_auto_execute"])

    def test_sudo_shell_c_wrapper_blocked(self):
        """sudo sh -c 'rm -rf /' must be unpacked and blocked."""
        res = self.validator.validate_command('sudo sh -c "rm -rf /"')
        self.assertFalse(res["valid"])
        self.assertTrue(res["is_dangerous"])
        risk = self.scorer.score_command('sudo sh -c "rm -rf /"', res)
        self.assertEqual(risk["tier"], 2)
        self.assertFalse(risk["can_auto_execute"])

    def test_sudo_mkfs_blocked(self):
        """sudo mkfs.ext4 /dev/sda1 must be blocked."""
        res = self.validator.validate_command("sudo mkfs.ext4 /dev/sda1")
        self.assertFalse(res["valid"])
        self.assertTrue(res["is_dangerous"])

    def test_find_exec_ls_is_safe_read_only(self):
        """find /var/log -exec ls -lh {} + must be Tier 0 (Read-Only)."""
        cmd = "find /var/log -type f -size +50M -exec ls -lh {} +"
        res = self.validator.validate_command(cmd)
        self.assertTrue(res["valid"])
        risk = self.scorer.score_command(cmd, res)
        self.assertEqual(risk["tier"], 0)

    def test_compound_systemctl_status_is_tier_0(self):
        """sudo nginx -t && sudo systemctl status nginx must be Tier 0."""
        cmd = "sudo nginx -t && sudo systemctl status nginx"
        res = self.validator.validate_command(cmd)
        self.assertTrue(res["valid"])
        risk = self.scorer.score_command(cmd, res)
        self.assertEqual(risk["tier"], 0)

    def test_systemctl_restart_is_tier_1(self):
        """sudo systemctl restart nginx must be Tier 1 (Mutating)."""
        cmd = "sudo systemctl restart nginx"
        res = self.validator.validate_command(cmd)
        risk = self.scorer.score_command(cmd, res)
        self.assertEqual(risk["tier"], 1)
        self.assertTrue(risk["requires_rehearsal"])


if __name__ == "__main__":
    unittest.main()
