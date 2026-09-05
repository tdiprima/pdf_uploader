"""Load and validate uploader configuration from environment variables."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_DIR = "."
DEFAULT_TIMEOUT_SECONDS = 120


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class UploaderConfig:
    base_url: str
    username: str
    password: str
    node_type: str
    node_id: int
    field_name: str
    local_dir: Path
    timeout_seconds: int


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _parse_base_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"DRUPAL_BASE_URL must be an https:// URL, got: {raw_url!r}")
    return raw_url.rstrip("/")


def _parse_positive_int(env_name: str, raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigError(f"{env_name} must be an integer, got: {raw_value!r}") from error
    if value <= 0:
        raise ConfigError(f"{env_name} must be positive, got: {value}")
    return value


def _parse_machine_name(env_name: str, raw_value: str) -> str:
    """Drupal machine names: lowercase letters, digits, underscores."""
    if not raw_value.replace("_", "").isalnum() or raw_value != raw_value.lower():
        raise ConfigError(f"{env_name} must be a Drupal machine name (a-z, 0-9, _), got: {raw_value!r}")
    return raw_value


def load_config() -> UploaderConfig:
    """Read configuration from environment. Fail fast on anything missing."""
    local_dir = Path(os.environ.get("LOCAL_PDF_DIR", DEFAULT_LOCAL_DIR)).expanduser().resolve()
    if not local_dir.is_dir():
        raise ConfigError(f"LOCAL_PDF_DIR is not a directory: {local_dir}")

    config = UploaderConfig(
        base_url=_parse_base_url(_require_env("DRUPAL_BASE_URL")),
        username=_require_env("DRUPAL_USER"),
        password=_require_env("DRUPAL_PASSWORD"),
        node_type=_parse_machine_name("DRUPAL_NODE_TYPE", _require_env("DRUPAL_NODE_TYPE")),
        node_id=_parse_positive_int("DRUPAL_NODE_ID", _require_env("DRUPAL_NODE_ID")),
        field_name=_parse_machine_name("DRUPAL_FILE_FIELD", _require_env("DRUPAL_FILE_FIELD")),
        local_dir=local_dir,
        timeout_seconds=_parse_positive_int(
            "DRUPAL_TIMEOUT_SECONDS", os.environ.get("DRUPAL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        ),
    )
    logger.info(
        "config loaded",
        extra={"event": "config_loaded", "base_url": config.base_url, "node_type": config.node_type,
               "node_id": config.node_id, "field": config.field_name, "local_dir": str(config.local_dir)},
    )
    return config
