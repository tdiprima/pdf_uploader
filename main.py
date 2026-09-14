"""Upload PDFs from a local folder to a Drupal site over HTTPS using core JSON:API.

Usage:
    python main.py [--dry-run]

Site prerequisites (one-time, via Drupal admin UI, no server access needed):
    1. Enable core modules "JSON:API" and "HTTP Basic Authentication" at /admin/modules.
    2. At /admin/config/services/jsonapi choose "Accept all JSON:API create, read,
       update, and delete operations".
    3. Have a content type with a File field that allows the "pdf" extension, and one
       node of that type to hold the uploads. Set the field's "Allowed number of
       values" to Unlimited, and its "File directory" blank so files land in
       /sites/default/files/ like the existing PDFs.

Configuration (environment variables, or a .env file in the current directory;
variables already set in the environment take precedence over .env):
    DRUPAL_BASE_URL         required  https://example.com
    DRUPAL_USER             required  Drupal account that can edit the target node
    DRUPAL_PASSWORD         required
    DRUPAL_NODE_TYPE        required  content type machine name, e.g. pdf_library
    DRUPAL_NODE_ID          required  nid of the node that holds uploaded files
    DRUPAL_FILE_FIELD       required  file field machine name, e.g. field_pdf
    LOCAL_PDF_DIR           optional  default current directory
    DRUPAL_TIMEOUT_SECONDS  optional  default 120
    LOG_LEVEL               optional  default INFO

Prints one line per file to stdout: "<local name> -> <public URL>".
Drupal renames on collision (x.pdf -> x_0.pdf); the printed URL is authoritative.
Files already attached to the node (same name or collision rename, same size)
are skipped, so rerunning after a failure is safe.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import requests

from config import DEFAULT_LOG_LEVEL, ConfigError, UploaderConfig, load_config, parse_log_level
from drupal_jsonapi import DrupalApiError, build_session, fetch_attached_files, fetch_node_uuid, upload_pdf
from env_file import load_env_file
from pdf_files import InvalidPdfError, LocalFileError, find_pdf_files, open_validated_pdf
from reconcile import RemoteFile, find_existing_upload

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_INVALID_INPUT = 3
EXIT_UPLOAD_ERROR = 4
EXIT_LOCAL_FILE_ERROR = 5

ENV_FILE_NAME = ".env"
STANDARD_LOG_ATTRIBUTES = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

logger = logging.getLogger("pdf_uploader")


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line, including any extra= fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_ATTRIBUTES:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Send JSON logs to stderr at the default level; LOG_LEVEL is applied once config is read."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=DEFAULT_LOG_LEVEL, handlers=[handler])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload local PDFs to a Drupal site via JSON:API.")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be uploaded; do not connect.")
    return parser.parse_args()


def upload_one(
    session: requests.Session,
    config: UploaderConfig,
    node_uuid: str,
    pdf_path: Path,
    attached: list[RemoteFile],
    reserved_names: set[str] | None = None,
) -> bool:
    """Upload one PDF unless it is already attached. Returns True if it was uploaded."""
    with open_validated_pdf(pdf_path) as pdf:
        existing = find_existing_upload(pdf.name, pdf.size, attached, reserved_names or set())
        if existing is not None:
            attached.remove(existing)
            logger.info("already attached, skipping", extra={"event": "upload_skipped", "file": pdf.name,
                                                             "remote_name": existing.filename, "url": existing.url})
            print(f"{pdf.name} -> {existing.url}")
            return False
        uploaded = upload_pdf(session, config, node_uuid, pdf.name, pdf.file_handle)
    print(f"{pdf.name} -> {uploaded.url}")
    return True


def upload_all(config: UploaderConfig, pdf_files: list[Path]) -> int:
    """Upload every PDF not already on the node. Returns how many were uploaded."""
    with build_session(config) as session:
        node_uuid = fetch_node_uuid(session, config)
        attached = fetch_attached_files(session, config, node_uuid)
        reserved_names = {path.name for path in pdf_files}
        return sum(
            upload_one(session, config, node_uuid, pdf_path, attached, reserved_names) for pdf_path in pdf_files
        )


def run(args: argparse.Namespace) -> int:
    """Load configuration, validate local files, then upload. Raises on any failure."""
    load_env_file(Path(ENV_FILE_NAME))
    logging.getLogger().setLevel(parse_log_level(os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL)))
    config = load_config()
    pdf_files = find_pdf_files(config.local_dir)

    if not pdf_files:
        logger.warning("no pdf files found", extra={"event": "no_files", "local_dir": str(config.local_dir)})
        return EXIT_OK

    logger.info("files selected", extra={"event": "files_selected", "count": len(pdf_files),
                                          "files": [path.name for path in pdf_files]})
    if args.dry_run:
        for path in pdf_files:
            print(path.name)
        return EXIT_OK

    uploaded_count = upload_all(config, pdf_files)
    logger.info("all uploads complete", extra={"event": "done", "count": len(pdf_files),
                                                "uploaded": uploaded_count, "skipped": len(pdf_files) - uploaded_count})
    return EXIT_OK


def report_failure(message: str, event: str, error: Exception, exit_code: int) -> int:
    """Log a structured failure and return its exit code."""
    logger.error(message, extra={"event": event, "detail": str(error)})
    return exit_code


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        return run(args)
    except ConfigError as error:
        return report_failure("configuration error", "config_error", error, EXIT_CONFIG_ERROR)
    except InvalidPdfError as error:
        return report_failure("invalid input file", "invalid_pdf", error, EXIT_INVALID_INPUT)
    except LocalFileError as error:
        return report_failure("local file error", "local_file_error", error, EXIT_LOCAL_FILE_ERROR)
    except DrupalApiError as error:
        return report_failure("upload failed", "upload_error", error, EXIT_UPLOAD_ERROR)


if __name__ == "__main__":
    sys.exit(main())
