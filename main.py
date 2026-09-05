"""Upload PDFs from a local folder to a Drupal site over HTTPS using core JSON:API.

Usage:
    python main.py [--dry-run]

Site prerequisites (one-time, via Drupal admin UI, no server access needed):
    1. Enable core modules "JSON:API" and "HTTP Basic Authentication" at /admin/modules.
    2. At /admin/config/services/jsonapi choose "Accept all JSON:API create, read,
       update, and delete operations".
    3. Have a content type with a File field that allows the "pdf" extension, and one
       node of that type to hold the uploads. Set the field's "File directory" blank
       so files land in /sites/default/files/ like the existing PDFs.

Configuration (environment variables):
    DRUPAL_BASE_URL         required  https://example.com
    DRUPAL_USER             required  Drupal account that can edit the target node
    DRUPAL_PASSWORD         required
    DRUPAL_NODE_TYPE        required  content type machine name, e.g. pdf_library
    DRUPAL_NODE_ID          required  nid of the node that holds uploaded files
    DRUPAL_FILE_FIELD       required  file field machine name, e.g. field_pdf
    LOCAL_PDF_DIR           optional  default current directory
    DRUPAL_TIMEOUT_SECONDS  optional  default 120
    LOG_LEVEL               optional  default INFO

Prints one line per uploaded file to stdout: "<local name> -> <public URL>".
Drupal renames on collision (x.pdf -> x_0.pdf); the printed URL is authoritative.
"""

import argparse
import json
import logging
import os
import sys

from config import ConfigError, load_config
from drupal_jsonapi import DrupalApiError, build_session, fetch_node_uuid, upload_pdf
from pdf_files import InvalidPdfError, find_pdf_files

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_INVALID_INPUT = 3
EXIT_UPLOAD_ERROR = 4

STANDARD_LOG_ATTRIBUTES = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


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
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), handlers=[handler])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload local PDFs to a Drupal site via JSON:API.")
    parser.add_argument("--dry-run", action="store_true", help="List files that would be uploaded; do not connect.")
    return parser.parse_args()


def upload_all(config, pdf_files) -> None:
    with build_session(config) as session:
        node_uuid = fetch_node_uuid(session, config)
        for pdf_path in pdf_files:
            uploaded = upload_pdf(session, config, node_uuid, pdf_path)
            print(f"{uploaded.local_name} -> {uploaded.url}")


def main() -> int:
    configure_logging()
    logger = logging.getLogger("pdf_uploader")
    args = parse_args()

    try:
        config = load_config()
        pdf_files = find_pdf_files(config.local_dir)
    except ConfigError as error:
        logger.error("configuration error", extra={"event": "config_error", "detail": str(error)})
        return EXIT_CONFIG_ERROR
    except InvalidPdfError as error:
        logger.error("invalid input file", extra={"event": "invalid_pdf", "detail": str(error)})
        return EXIT_INVALID_INPUT

    if not pdf_files:
        logger.warning("no pdf files found", extra={"event": "no_files", "local_dir": str(config.local_dir)})
        return EXIT_OK

    logger.info("files selected", extra={"event": "files_selected", "count": len(pdf_files),
                                          "files": [path.name for path in pdf_files]})
    if args.dry_run:
        return EXIT_OK

    try:
        upload_all(config, pdf_files)
    except DrupalApiError as error:
        logger.error("upload failed", extra={"event": "upload_error", "detail": str(error)})
        return EXIT_UPLOAD_ERROR

    logger.info("all uploads complete", extra={"event": "done", "count": len(pdf_files)})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
