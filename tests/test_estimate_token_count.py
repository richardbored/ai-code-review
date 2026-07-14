import unittest

from ai_code_review import estimate_token_count


class TestEstimateTokenCount(unittest.TestCase):
    def test_empty_string_returns_zero(self) -> None:
        self.assertEqual(estimate_token_count(""), 0)

    def test_whitespace_only_returns_zero(self) -> None:
        self.assertEqual(estimate_token_count(" \n\t  "), 0)

    def test_single_word(self) -> None:
        # int(1 * 1.3) == 1
        self.assertEqual(estimate_token_count("hello"), 1)

    def test_multiple_words(self) -> None:
        # int(3 * 1.3) == 3
        self.assertEqual(estimate_token_count("one two three"), 3)

    def test_punctuation_only(self) -> None:
        # int(4 * 0.35) == 1
        self.assertEqual(estimate_token_count("!?.,") , 1)

    def test_words_and_punctuation(self) -> None:
        # 2 words and 2 punctuation characters:
        # int((2 * 1.3) + (2 * 0.35)) == int(3.3) == 3
        self.assertEqual(estimate_token_count("hello, world!"), 3)

    def test_newlines_do_not_count_as_punctuation(self) -> None:
        # 2 words, while whitespace characters are ignored.
        self.assertEqual(estimate_token_count("hello\nworld"), 2)

    def test_underscores_are_word_characters(self) -> None:
        # Python-style identifiers containing underscores count as one word.
        self.assertEqual(estimate_token_count("token_count"), 1)

    def test_numbers_are_word_characters(self) -> None:
        # "version" and "123" are both matched by \w+.
        self.assertEqual(estimate_token_count("version 123"), 2)

    def test_unicode_letters_are_word_characters(self) -> None:
        self.assertEqual(estimate_token_count("café résumé"), 2)

    def test_simple_python_statement(self) -> None:
        text = "result = add(1, 2)"

        # Words: result, add, 1, 2 = 4
        # Punctuation: =, (, ,, ) = 4
        # int((4 * 1.3) + (4 * 0.35)) == int(6.6) == 6
        self.assertEqual(estimate_token_count(text), 6)

    def test_result_is_always_an_integer(self) -> None:
        result = estimate_token_count("def greet(name): return f'Hello, {name}!'")

        self.assertIsInstance(result, int)

    def test_more_content_produces_larger_estimate(self) -> None:
        short_text = "hello"
        longer_text = "hello world, this is a longer string!"

        self.assertGreater(
            estimate_token_count(longer_text),
            estimate_token_count(short_text),
        )


if __name__ == "__main__":
    unittest.main()