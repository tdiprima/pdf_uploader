import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import main
from reconcile import RemoteFile

VALID_PDF_BYTES = b"%PDF-1.7\n"


class MainExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = {"DRUPAL_BASE_URL": "https://example.com", "DRUPAL_USER": "u", "DRUPAL_PASSWORD": "p",
                    "DRUPAL_NODE_TYPE": "page", "DRUPAL_NODE_ID": "1", "DRUPAL_FILE_FIELD": "field_pdf",
                    "LOCAL_PDF_DIR": str(self.root)}
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.directory.cleanup()

    def run_main(self, env: dict[str, str], dry_run: bool = True) -> int:
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(main, "parse_args", return_value=argparse.Namespace(dry_run=dry_run)), \
                self.assertLogs("pdf_uploader", "INFO"):
            return main.main()

    def test_invalid_log_level_is_config_error(self):
        self.assertEqual(self.run_main({**self.env, "LOG_LEVEL": "verbose"}), main.EXIT_CONFIG_ERROR)

    def test_env_file_is_loaded(self):
        (self.root / ".env").write_text("".join(f"{key}={value}\n" for key, value in self.env.items()))
        (self.root / ".env").chmod(0o600)
        self.assertEqual(self.run_main({}), main.EXIT_OK)

    def test_missing_config_is_config_error(self):
        self.assertEqual(self.run_main({}), main.EXIT_CONFIG_ERROR)

    def test_bad_pdf_is_invalid_input(self):
        (self.root / "fake.pdf").write_bytes(b"nope")
        self.assertEqual(self.run_main(self.env), main.EXIT_INVALID_INPUT)

    def test_dry_run_prints_each_selected_filename(self):
        (self.root / "a.pdf").write_bytes(VALID_PDF_BYTES)
        (self.root / "b.pdf").write_bytes(VALID_PDF_BYTES)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(self.run_main({**self.env, "LOG_LEVEL": "ERROR"}), main.EXIT_OK)
        self.assertEqual(output.getvalue(), "a.pdf\nb.pdf\n")


class UploadOneTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.pdf_path = Path(self.directory.name) / "a.pdf"
        self.pdf_path.write_bytes(VALID_PDF_BYTES)

    def tearDown(self):
        self.directory.cleanup()

    def test_skips_file_already_attached_under_renamed_name(self):
        attached = [RemoteFile("a_0.pdf", len(VALID_PDF_BYTES), "https://example.com/a_0.pdf")]
        output = io.StringIO()
        with mock.patch.object(main, "upload_pdf") as upload_pdf, redirect_stdout(output):
            was_uploaded = main.upload_one(mock.Mock(), mock.Mock(), "uuid", self.pdf_path, attached)
        self.assertFalse(was_uploaded)
        upload_pdf.assert_not_called()
        self.assertEqual(output.getvalue(), "a.pdf -> https://example.com/a_0.pdf\n")

    def test_uploads_without_adding_new_file_to_reconciliation_pool(self):
        attached: list[RemoteFile] = []
        uploaded = RemoteFile("a.pdf", len(VALID_PDF_BYTES), "https://example.com/a.pdf")
        with mock.patch.object(main, "upload_pdf", return_value=uploaded), redirect_stdout(io.StringIO()):
            was_uploaded = main.upload_one(mock.Mock(), mock.Mock(), "uuid", self.pdf_path, attached)
        self.assertTrue(was_uploaded)
        self.assertEqual(attached, [])


class UploadAllReconciliationTest(unittest.TestCase):
    def test_remote_file_is_not_reused_for_two_local_files(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        paths = [root / "report.pdf", root / "report_0.pdf"]
        for path in paths:
            path.write_bytes(VALID_PDF_BYTES)
        remote = RemoteFile("report_0.pdf", len(VALID_PDF_BYTES), "https://example.com/report_0.pdf")
        uploaded = RemoteFile("report_1.pdf", len(VALID_PDF_BYTES), "https://example.com/report_1.pdf")

        session = mock.MagicMock()
        session.__enter__.return_value = session
        with mock.patch.object(main, "build_session", return_value=session), \
                mock.patch.object(main, "fetch_node_uuid", return_value="uuid"), \
                mock.patch.object(main, "fetch_attached_files", return_value=[remote]), \
                mock.patch.object(main, "upload_pdf", return_value=uploaded) as upload_pdf, \
                redirect_stdout(io.StringIO()):
            uploaded_count = main.upload_all(mock.Mock(), paths)

        self.assertEqual(uploaded_count, 1)
        self.assertEqual(upload_pdf.call_args.args[3], "report.pdf")


if __name__ == "__main__":
    unittest.main()
