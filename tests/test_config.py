import logging
import os
import unittest
from unittest import mock

from config import ConfigError, _parse_base_url, _parse_machine_name, load_config, parse_log_level


class ParseMachineNameTest(unittest.TestCase):
    def test_accepts_lowercase_digits_underscore(self):
        self.assertEqual(_parse_machine_name("X", "field_pdf_2"), "field_pdf_2")

    def test_accepts_32_characters(self):
        self.assertEqual(_parse_machine_name("X", "a" * 32), "a" * 32)

    def test_rejects_invalid_values(self):
        invalid_values = ["", "a" * 33, "Field_pdf", "field-pdf", "café", "字段", "field pdf",
                          "field\n", "../node", "x/y", "٣"]
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ConfigError):
                _parse_machine_name("X", value)


class ParseLogLevelTest(unittest.TestCase):
    def test_accepts_known_names_any_case(self):
        self.assertEqual(parse_log_level("debug"), logging.DEBUG)
        self.assertEqual(parse_log_level(" WARNING "), logging.WARNING)

    def test_rejects_unknown_names(self):
        for value in ["verbose", "", "10", "WARN", "NOTSET"]:
            with self.subTest(value=value), self.assertRaises(ConfigError):
                parse_log_level(value)


class ParseBaseUrlTest(unittest.TestCase):
    def test_rejects_query_and_fragment(self):
        for value in ["https://example.com?tenant=x", "https://example.com/#section"]:
            with self.subTest(value=value), self.assertRaises(ConfigError):
                _parse_base_url(value)


class LoadConfigTest(unittest.TestCase):
    def test_preserves_password_whitespace(self):
        env = {
            "DRUPAL_BASE_URL": "https://example.com",
            "DRUPAL_USER": "user",
            "DRUPAL_PASSWORD": " secret ",
            "DRUPAL_NODE_TYPE": "page",
            "DRUPAL_NODE_ID": "1",
            "DRUPAL_FILE_FIELD": "field_pdf",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_config().password, " secret ")


if __name__ == "__main__":
    unittest.main()
