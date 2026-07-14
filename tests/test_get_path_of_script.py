import unittest
from pathlib import Path

from ai_code_review import get_path_of_script


class TestGetPathOfScript(unittest.TestCase):
    def test_returns_path(self) -> None:
        result = get_path_of_script()

        self.assertIsInstance(result, Path)

    def test_returns_absolute_path(self) -> None:
        result = get_path_of_script()

        self.assertTrue(result.is_absolute())

    def test_returns_resolved_module_path(self) -> None:
        result = get_path_of_script()
        expected = Path(get_path_of_script.__code__.co_filename).resolve()

        self.assertEqual(result, expected)

    def test_path_exists(self) -> None:
        result = get_path_of_script()

        self.assertTrue(result.exists())
        self.assertTrue(result.is_file())


if __name__ == "__main__":
    unittest.main()