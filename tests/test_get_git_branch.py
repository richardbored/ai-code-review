import subprocess
import unittest
from unittest.mock import patch

from ai_code_review import get_git_branch


class TestGetGitBranch(unittest.TestCase):
    @patch("ai_code_review.subprocess.run")
    def test_returns_current_branch_name(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "branch", "--show-current"],
            returncode=0,
            stdout="feature/my-branch\n",
            stderr="",
        )

        result = get_git_branch()

        self.assertEqual(result, "feature/my-branch")
        mock_run.assert_called_once_with(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("ai_code_review.subprocess.run")
    def test_strips_whitespace_from_branch_name(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "branch", "--show-current"],
            returncode=0,
            stdout="  main \n",
            stderr="",
        )

        result = get_git_branch()

        self.assertEqual(result, "main")

    @patch("ai_code_review.subprocess.run")
    def test_returns_empty_string_when_git_outputs_no_branch(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "branch", "--show-current"],
            returncode=0,
            stdout="",
            stderr="",
        )

        result = get_git_branch()

        self.assertEqual(result, "")

    @patch("ai_code_review.subprocess.run")
    def test_returns_none_when_git_command_fails(self, mock_run) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "branch", "--show-current"],
        )

        result = get_git_branch()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()