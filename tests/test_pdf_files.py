import tempfile
import unittest
from pathlib import Path

from pdf_files import (
    MAX_FILENAME_LENGTH,
    InvalidPdfError,
    LocalFileError,
    find_pdf_files,
    is_supported_filename,
    open_validated_pdf,
)

VALID_PDF_BYTES = b"%PDF-1.7\n%test\n"


class IsSupportedFilenameTest(unittest.TestCase):
    def test_accepts_plain_ascii_names(self):
        for name in ["report.pdf", "Annual Report 2026.PDF", "a_b-c.v2.pdf", "1.pdf"]:
            with self.subTest(name=name):
                self.assertTrue(is_supported_filename(name))

    def test_length_boundary(self):
        name_at_limit = "a" * (MAX_FILENAME_LENGTH - 4) + ".pdf"
        self.assertTrue(is_supported_filename(name_at_limit))
        self.assertFalse(is_supported_filename("a" + name_at_limit))

    def test_rejects_header_breaking_or_non_ascii_names(self):
        for name in ["", "报告.pdf", "café.pdf", 'a".pdf', "it's.pdf", "a\r\nX-Evil: 1.pdf",
                     "a\x00.pdf", "a;b.pdf", " lead.pdf", "-dash.pdf", "K.pdf"]:
            with self.subTest(name=name):
                self.assertFalse(is_supported_filename(name))


class PdfDirectoryTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name: str, content: bytes = VALID_PDF_BYTES) -> Path:
        path = self.root / name
        path.write_bytes(content)
        return path


class FindPdfFilesTest(PdfDirectoryTestCase):
    def test_empty_directory(self):
        self.assertEqual(find_pdf_files(self.root), [])

    def test_returns_sorted_pdfs_and_skips_others(self):
        self.write("b.pdf")
        self.write("a.pdf")
        self.write("notes.txt", b"hello")
        self.write(".hidden.pdf", b"junk")
        (self.root / "sub.pdf").mkdir()
        self.assertEqual([path.name for path in find_pdf_files(self.root)], ["a.pdf", "b.pdf"])

    def test_rejects_empty_pdf(self):
        self.write("empty.pdf", b"")
        with self.assertRaises(InvalidPdfError):
            find_pdf_files(self.root)

    def test_rejects_bad_header(self):
        self.write("fake.pdf", b"<html>")
        with self.assertRaises(InvalidPdfError):
            find_pdf_files(self.root)

    def test_rejects_unsupported_name(self):
        self.write("报告.pdf")
        with self.assertRaises(InvalidPdfError):
            find_pdf_files(self.root)

    def test_missing_directory_is_local_file_error(self):
        with self.assertRaises(LocalFileError):
            find_pdf_files(self.root / "gone")


class OpenValidatedPdfTest(PdfDirectoryTestCase):
    def test_yields_rewound_handle_and_size(self):
        path = self.write("ok.pdf")
        with open_validated_pdf(path) as pdf:
            self.assertEqual(pdf.name, "ok.pdf")
            self.assertEqual(pdf.size, len(VALID_PDF_BYTES))
            self.assertEqual(pdf.file_handle.read(), VALID_PDF_BYTES)

    def test_file_removed_after_discovery(self):
        path = self.write("gone.pdf")
        self.assertEqual(find_pdf_files(self.root), [path])
        path.unlink()
        with self.assertRaises(LocalFileError), open_validated_pdf(path):
            pass

    def test_file_replaced_after_discovery(self):
        path = self.write("swap.pdf")
        find_pdf_files(self.root)
        path.write_bytes(b"MZ not a pdf")
        with self.assertRaises(InvalidPdfError), open_validated_pdf(path):
            pass


if __name__ == "__main__":
    unittest.main()
