import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import ai_code_review


class TestWriteAuditEvent(unittest.TestCase):
    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_writes_expected_json_line(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "2026-07-13T10:30:00"
        mock_get_path_of_script.return_value = Path("/app/tools/audit.py")
        mock_get_git_branch.return_value = "feature-tests"
        mock_set_working_directory.return_value = Path("/projects/my-project")

        file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = file_handle

        ai_code_review.write_audit_event(
            "review_completed",
            reviewer="Alice",
            approved=True,
        )

        expected_path = Path(
            "/app/tools/code_review_log/"
            "dir_my-project__br_feature-tests__ai_review.log.jsonl"
        )
        mock_open.assert_called_once_with(
            expected_path,
            "a",
            encoding="utf-8",
        )

        expected_record = {
            "timestamp": "2026-07-13T10:30:00",
            "event": "review_completed",
            "reviewer": "Alice",
            "approved": True,
        }

        file_handle.write.assert_has_calls(
            [
                call(json.dumps(expected_record, ensure_ascii=False)),
                call("\n"),
            ]
        )
        file_handle.flush.assert_called_once_with()

    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_preserves_non_ascii_characters(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "2026-07-13T10:30:00"
        mock_get_path_of_script.return_value = Path("/app/audit.py")
        mock_get_git_branch.return_value = "main"
        mock_set_working_directory.return_value = Path("/projects/demo")

        file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = file_handle

        ai_code_review.write_audit_event(
            "prüfung",
            message="Café résumé",
        )

        written_json = file_handle.write.call_args_list[0].args[0]

        self.assertIn("prüfung", written_json)
        self.assertIn("Café résumé", written_json)
        self.assertNotIn(r"\u00fc", written_json)
        self.assertEqual(
            json.loads(written_json),
            {
                "timestamp": "2026-07-13T10:30:00",
                "event": "prüfung",
                "message": "Café résumé",
            },
        )

    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_uses_none_when_no_git_branch_is_available(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "2026-07-13T10:30:00"
        mock_get_path_of_script.return_value = Path("/app/audit.py")
        mock_get_git_branch.return_value = None
        mock_set_working_directory.return_value = Path("/projects/demo")

        mock_open.return_value.__enter__.return_value = MagicMock()

        ai_code_review.write_audit_event("detached_head")

        expected_path = Path(
            "/app/code_review_log/"
            "dir_demo__br_None__ai_review.log.jsonl"
        )
        mock_open.assert_called_once_with(
            expected_path,
            "a",
            encoding="utf-8",
        )

    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_additional_timestamp_overrides_generated_timestamp(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "generated timestamp"
        mock_get_path_of_script.return_value = Path("/app/audit.py")
        mock_get_git_branch.return_value = "main"
        mock_set_working_directory.return_value = Path("/projects/demo")

        file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = file_handle

        ai_code_review.write_audit_event(
            "test_event",
            timestamp="caller timestamp",
        )

        written_json = file_handle.write.call_args_list[0].args[0]
        record = json.loads(written_json)

        self.assertEqual(record["timestamp"], "caller timestamp")

    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_raises_type_error_for_non_serializable_data(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "2026-07-13T10:30:00"
        mock_get_path_of_script.return_value = Path("/app/audit.py")
        mock_get_git_branch.return_value = "main"
        mock_set_working_directory.return_value = Path("/projects/demo")

        file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = file_handle

        with self.assertRaises(TypeError):
            ai_code_review.write_audit_event(
                "invalid_data",
                value=object(),
            )

        file_handle.write.assert_not_called()
        file_handle.flush.assert_not_called()

    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_propagates_error_when_log_file_cannot_be_opened(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "2026-07-13T10:30:00"
        mock_get_path_of_script.return_value = Path("/app/audit.py")
        mock_get_git_branch.return_value = "main"
        mock_set_working_directory.return_value = Path("/projects/demo")
        mock_open.side_effect = OSError("permission denied")

        with self.assertRaisesRegex(OSError, "permission denied"):
            ai_code_review.write_audit_event("test_event")

    @patch("ai_code_review.set_working_directory")
    @patch("ai_code_review.get_git_branch")
    @patch("ai_code_review.get_path_of_script")
    @patch("ai_code_review.get_current_datetime")
    @patch("pathlib.Path.open", autospec=True)
    def test_propagates_error_when_write_fails(
        self,
        mock_open: MagicMock,
        mock_get_current_datetime: MagicMock,
        mock_get_path_of_script: MagicMock,
        mock_get_git_branch: MagicMock,
        mock_set_working_directory: MagicMock,
    ) -> None:
        mock_get_current_datetime.return_value = "2026-07-13T10:30:00"
        mock_get_path_of_script.return_value = Path("/app/audit.py")
        mock_get_git_branch.return_value = "main"
        mock_set_working_directory.return_value = Path("/projects/demo")

        file_handle = MagicMock()
        file_handle.write.side_effect = OSError("disk full")
        mock_open.return_value.__enter__.return_value = file_handle

        with self.assertRaisesRegex(OSError, "disk full"):
            ai_code_review.write_audit_event("test_event")

        file_handle.flush.assert_not_called()


if __name__ == "__main__":
    unittest.main()