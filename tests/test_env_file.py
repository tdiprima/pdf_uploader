import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import ConfigError
from env_file import MAX_ENV_FILE_BYTES, load_env_file, parse_env_text


class ParseEnvTextTest(unittest.TestCase):
    def test_empty_text(self):
        self.assertEqual(parse_env_text(""), {})

    def test_comments_blank_lines_export_and_quotes(self):
        text = "# comment\n\nA=1\nexport B=two\nC=\"with space\"\nD='single'\nE=\n"
        self.assertEqual(parse_env_text(text), {"A": "1", "B": "two", "C": "with space", "D": "single", "E": ""})

    def test_values_are_literal(self):
        parsed = parse_env_text("PASSWORD=p#ss=word$HOME\"\n")
        self.assertEqual(parsed["PASSWORD"], 'p#ss=word$HOME"')

    def test_duplicate_key_last_wins(self):
        self.assertEqual(parse_env_text("A=1\nA=2\n"), {"A": "2"})

    def test_rejects_malformed_lines_without_echoing_them(self):
        for line in ["no_equals_sign", "=secret_value", "1BAD=x", "BAD KEY=x", "$(rm -rf /)=x"]:
            with self.subTest(line=line):
                with self.assertRaises(ConfigError) as context:
                    parse_env_text(f"OK=1\n{line}\n")
                self.assertIn("line 2", str(context.exception))
                self.assertNotIn(line, str(context.exception))


class LoadEnvFileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / ".env"

    def tearDown(self):
        self.directory.cleanup()

    def test_missing_file_is_ignored(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            load_env_file(self.path)
            self.assertEqual(dict(os.environ), {})

    def test_existing_environment_wins(self):
        self.path.write_text("DRUPAL_USER=from_file\nDRUPAL_NODE_ID=7\n")
        self.path.chmod(0o600)
        with mock.patch.dict(os.environ, {"DRUPAL_USER": "from_shell"}, clear=True):
            load_env_file(self.path)
            self.assertEqual(os.environ["DRUPAL_USER"], "from_shell")
            self.assertEqual(os.environ["DRUPAL_NODE_ID"], "7")

    def test_rejects_oversized_file(self):
        self.path.write_text("A=" + "x" * MAX_ENV_FILE_BYTES)
        with self.assertRaises(ConfigError):
            load_env_file(self.path)

    def test_rejects_non_utf8_file(self):
        self.path.write_bytes(b"A=\xff\xfe\n")
        with self.assertRaises(ConfigError):
            load_env_file(self.path)

    def test_warns_when_readable_by_others(self):
        self.path.write_text("A=1\n")
        self.path.chmod(0o644)
        with mock.patch.dict(os.environ, {}, clear=True), self.assertLogs("env_file", "WARNING"):
            load_env_file(self.path)


if __name__ == "__main__":
    unittest.main()
