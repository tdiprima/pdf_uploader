"""Load KEY=VALUE pairs from a local .env file into the process environment.

Supported format (a deliberate subset of what shells accept):
    # comment lines and blank lines are ignored
    KEY=value
    KEY="value with spaces"
    KEY='value with spaces'
    export KEY=value

Values are taken literally: no variable expansion, no inline comments (so a
password may contain "#"), no multi-line values. Variables already set in the
environment win over the file, so an exported value always overrides .env.
"""

import logging
import os
import re
import stat
from pathlib import Path

from config import ConfigError

logger = logging.getLogger(__name__)

MAX_ENV_FILE_BYTES = 64 * 1024
ENV_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
EXPORT_PREFIX = "export "
QUOTE_CHARACTERS = ("'", '"')


def _strip_quotes(raw_value: str) -> str:
    """Remove one pair of matching surrounding quotes, if present."""
    if len(raw_value) >= 2 and raw_value[0] in QUOTE_CHARACTERS and raw_value[-1] == raw_value[0]:
        return raw_value[1:-1]
    return raw_value


def _parse_line(line: str, line_number: int) -> tuple[str, str] | None:
    """Parse one .env line. Returns None for blank and comment lines."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith(EXPORT_PREFIX):
        stripped = stripped[len(EXPORT_PREFIX):].lstrip()
    key, separator, raw_value = stripped.partition("=")
    key = key.strip()
    # Never echo the line itself: it may hold a password.
    if not separator or ENV_KEY_PATTERN.fullmatch(key) is None:
        raise ConfigError(f".env line {line_number} is not a valid KEY=value assignment")
    return key, _strip_quotes(raw_value.strip())


def parse_env_text(text: str) -> dict[str, str]:
    """Parse the full contents of a .env file into a dict. Later keys win."""
    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        parsed = _parse_line(line, line_number)
        if parsed is not None:
            values[parsed[0]] = parsed[1]
    return values


def _read_env_file(path: Path) -> str:
    """Read the .env file as UTF-8, refusing oversized or unreadable files."""
    try:
        file_stat = path.stat()
        if file_stat.st_size > MAX_ENV_FILE_BYTES:
            raise ConfigError(f"{path} is larger than {MAX_ENV_FILE_BYTES} bytes")
        if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.warning(
                "env file is accessible to other users; run chmod 600 on it",
                extra={"event": "env_file_permissions", "path": str(path)},
            )
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path} is not valid UTF-8") from error


def load_env_file(path: Path) -> None:
    """Copy variables from path into os.environ without overriding existing ones. Missing file is fine."""
    if not path.is_file():
        logger.debug("no env file", extra={"event": "env_file_absent", "path": str(path)})
        return
    values = parse_env_text(_read_env_file(path))
    applied_keys = [key for key in values if key not in os.environ]
    for key in applied_keys:
        os.environ[key] = values[key]
    logger.info(
        "env file loaded",
        extra={"event": "env_file_loaded", "path": str(path), "applied": sorted(applied_keys)},
    )
