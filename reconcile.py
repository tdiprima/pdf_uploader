"""Pure logic: decide whether a local PDF is already attached to the Drupal node.

Uploads are not idempotent, so a rerun after a partial or ambiguous failure
(for example a timeout after Drupal already stored the file) would otherwise
upload the same PDF again under a collision-renamed name. Matching on name
plus byte size lets a rerun skip what is already there.
"""

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RemoteFile:
    filename: str
    size: int
    url: str


def is_same_or_renamed(local_name: str, remote_name: str) -> bool:
    """True when remote_name is local_name or Drupal's collision rename of it (x.pdf -> x_0.pdf)."""
    stem, dot, suffix = local_name.rpartition(".")
    if not dot:
        return False
    pattern = re.escape(stem) + r"(?:_\d+)?" + re.escape(dot + suffix)
    # ASCII-only case folding: Drupal may lowercase names, but nothing more exotic.
    return re.fullmatch(pattern, remote_name, flags=re.IGNORECASE | re.ASCII) is not None


def find_existing_upload(local_name: str, local_size: int, remote_files: Iterable[RemoteFile]) -> RemoteFile | None:
    """Return the attached file that matches this local PDF by name and size, if any."""
    for remote_file in remote_files:
        if remote_file.size == local_size and is_same_or_renamed(local_name, remote_file.filename):
            return remote_file
    return None
