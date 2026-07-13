from contextlib import redirect_stdout
import io
import unittest
# from typing import Any

from ai_code_review import Colour, cprint


class TestCPrint(unittest.TestCase):
    def test_default(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            cprint()

        self.assertEqual(
            output.getvalue(),
            f"{Colour.RESET}{Colour.RESET}\n",
        )

    def test_text_only(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            cprint("Hello")

        self.assertEqual(
            output.getvalue(),
            f"{Colour.RESET}Hello{Colour.RESET}\n",
        )

    def test_colour(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            cprint("Hello", colour=Colour.RED)

        self.assertEqual(
            output.getvalue(),
            f"{Colour.RED}Hello{Colour.RESET}\n",
        )

    def test_bold(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            cprint("Hello", bold=True)

        self.assertEqual(
            output.getvalue(),
            f"{Colour.BOLD}{Colour.RESET}Hello{Colour.RESET}\n",
        )

    def test_bold_and_colour(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            cprint("Hello", colour=Colour.GREEN, bold=True)

        self.assertEqual(
            output.getvalue(),
            f"{Colour.BOLD}{Colour.GREEN}Hello{Colour.RESET}\n",
        )

    def test_custom_end(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            cprint("Hello", end="")

        self.assertEqual(
            output.getvalue(),
            f"{Colour.RESET}Hello{Colour.RESET}",
        )


if __name__ == "__main__":
    unittest.main()