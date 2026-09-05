"""Pure logic: discover and validate local PDF files. No network access here."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PDF_SUFFIX = ".pdf"
PDF_MAGIC_BYTES = b"%PDF-"


class InvalidPdfError(Exception):
    """Raised when a file claims to be a PDF but is not."""


def is_safe_filename(name: str) -> bool:
    """Reject names that could escape the target directory or hide as dotfiles."""
    if not name or name.startswith("."):
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    return name.lower().endswith(PDF_SUFFIX)


def has_pdf_header(path: Path) -> bool:
    """Check file starts with the PDF magic bytes."""
    with path.open("rb") as file_handle:
        return file_handle.read(len(PDF_MAGIC_BYTES)) == PDF_MAGIC_BYTES


def find_pdf_files(local_dir: Path) -> list[Path]:
    """Return sorted, validated PDF files directly inside local_dir (no recursion)."""
    pdf_files: list[Path] = []
    for candidate in sorted(local_dir.iterdir()):
        if not candidate.is_file():
            continue
        if not is_safe_filename(candidate.name):
            logger.debug("skipping non-pdf", extra={"event": "skip_file", "name": candidate.name})
            continue
        if candidate.stat().st_size == 0:
            raise InvalidPdfError(f"Empty file: {candidate}")
        if not has_pdf_header(candidate):
            raise InvalidPdfError(f"Not a PDF (bad header): {candidate}")
        pdf_files.append(candidate)
    return pdf_files
