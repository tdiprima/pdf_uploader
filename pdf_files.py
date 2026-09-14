"""Pure logic: discover and validate local PDF files. No network access here."""

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

PDF_SUFFIX = ".pdf"
PDF_MAGIC_BYTES = b"%PDF-"
# The name travels in an HTTP header, which only carries Latin-1 safely, and
# quotes or control characters would break the header. Keep to plain ASCII.
SUPPORTED_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]*")
# Drupal stores filenames in a 255-character column and may append "_N" on collision.
MAX_FILENAME_LENGTH = 240


class InvalidPdfError(Exception):
    """Raised when a file claims to be a PDF but is not."""


class LocalFileError(Exception):
    """Raised when a local file or directory cannot be read."""


@dataclass(frozen=True)
class OpenPdf:
    name: str
    size: int
    file_handle: BinaryIO


def is_safe_filename(name: str) -> bool:
    """Reject names that could escape the target directory or hide as dotfiles."""
    if not name or name.startswith("."):
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    return name.lower().endswith(PDF_SUFFIX)


def is_supported_filename(name: str) -> bool:
    """True when the name uses only ASCII letters, digits, space, '.', '_' or '-' and fits Drupal's limit."""
    if len(name) > MAX_FILENAME_LENGTH:
        return False
    return SUPPORTED_FILENAME_PATTERN.fullmatch(name) is not None


def _require_supported_filename(path: Path) -> None:
    """Raise InvalidPdfError for a name that cannot be sent to Drupal unchanged."""
    if not is_supported_filename(path.name):
        raise InvalidPdfError(
            f"Unsupported filename (use ASCII letters, digits, space, '.', '_', '-'; "
            f"max {MAX_FILENAME_LENGTH} characters): {path}"
        )


def _require_pdf_content(file_handle: BinaryIO, path: Path) -> int:
    """Check an open file is non-empty and starts with the PDF magic bytes. Returns its size."""
    try:
        size = os.fstat(file_handle.fileno()).st_size
        header = file_handle.read(len(PDF_MAGIC_BYTES))
        file_handle.seek(0)
    except OSError as error:
        raise LocalFileError(f"Cannot read {path}: {error}") from error
    if size == 0:
        raise InvalidPdfError(f"Empty file: {path}")
    if header != PDF_MAGIC_BYTES:
        raise InvalidPdfError(f"Not a PDF (bad header): {path}")
    return size


@contextmanager
def open_validated_pdf(path: Path) -> Iterator[OpenPdf]:
    """Open a PDF for reading after checking its name, size and header.

    Checks run on the open handle, so a file swapped or truncated after
    discovery is caught before any bytes are sent.
    """
    _require_supported_filename(path)
    try:
        file_handle = path.open("rb")
    except OSError as error:
        raise LocalFileError(f"Cannot open {path}: {error}") from error
    with file_handle:
        size = _require_pdf_content(file_handle, path)
        yield OpenPdf(name=path.name, size=size, file_handle=file_handle)


def _list_directory(local_dir: Path) -> list[Path]:
    """Return the directory's entries in sorted order."""
    try:
        return sorted(local_dir.iterdir())
    except OSError as error:
        raise LocalFileError(f"Cannot list directory {local_dir}: {error}") from error


def find_pdf_files(local_dir: Path) -> list[Path]:
    """Return sorted, validated PDF files directly inside local_dir (no recursion)."""
    pdf_files: list[Path] = []
    for candidate in _list_directory(local_dir):
        if not candidate.is_file():
            continue
        if not is_safe_filename(candidate.name):
            logger.debug("skipping non-pdf", extra={"event": "skip_file", "name": candidate.name})
            continue
        with open_validated_pdf(candidate):
            pdf_files.append(candidate)
    return pdf_files
