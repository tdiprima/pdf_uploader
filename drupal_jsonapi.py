"""HTTP side effects: upload files to a Drupal node's file field via core JSON:API.

Endpoint used:
    POST {base}/jsonapi/node/{type}/{node_uuid}/{field}
    Content-Type: application/octet-stream
    Content-Disposition: file; filename="name.pdf"

Uploading to an existing node's field attaches the file immediately, so Drupal
marks it permanent (unattached uploads are garbage-collected by cron).
Drupal never overwrites: an existing "x.pdf" produces "x_0.pdf". The real
filename and URL come back in the response and are logged.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from config import UploaderConfig

logger = logging.getLogger(__name__)

JSONAPI_CONTENT_TYPE = "application/vnd.api+json"
HTTP_OK = 200
HTTP_CREATED = 201


class DrupalApiError(Exception):
    """Raised when a Drupal JSON:API request fails or returns an unexpected shape."""


@dataclass(frozen=True)
class UploadedFile:
    local_name: str
    remote_name: str
    url: str


def _summarize_error(response: requests.Response) -> str:
    """Pull JSON:API error detail if present; otherwise the status line. Never dumps HTML bodies."""
    try:
        errors = response.json().get("errors", [])
        details = "; ".join(f"{err.get('title', '')}: {err.get('detail', '')}" for err in errors)
        if details:
            return f"HTTP {response.status_code} {details}"
    except ValueError:
        pass
    return f"HTTP {response.status_code} {response.reason}"


def build_session(config: UploaderConfig) -> requests.Session:
    """Basic Auth over HTTPS. Requires the core basic_auth module enabled on the site."""
    session = requests.Session()
    session.auth = (config.username, config.password)
    session.headers.update({"Accept": JSONAPI_CONTENT_TYPE})
    return session


def fetch_node_uuid(session: requests.Session, config: UploaderConfig) -> str:
    """Resolve the human-facing node ID to the UUID that JSON:API paths require."""
    url = f"{config.base_url}/jsonapi/node/{config.node_type}"
    params = {"filter[drupal_internal__nid]": config.node_id, "fields[node--" + config.node_type + "]": "id"}
    try:
        response = session.get(url, params=params, timeout=config.timeout_seconds)
    except requests.RequestException as error:
        raise DrupalApiError(f"Node lookup request failed: {error}") from error
    if response.status_code != HTTP_OK:
        raise DrupalApiError(f"Node lookup failed: {_summarize_error(response)}")

    data = response.json().get("data", [])
    if len(data) != 1:
        raise DrupalApiError(
            f"Expected exactly one node of type {config.node_type} with nid {config.node_id}, found {len(data)}"
        )
    return data[0]["id"]


def upload_pdf(session: requests.Session, config: UploaderConfig, node_uuid: str, local_path: Path) -> UploadedFile:
    """Upload one PDF into the node's file field. Returns the name and URL Drupal assigned."""
    url = f"{config.base_url}/jsonapi/node/{config.node_type}/{node_uuid}/{config.field_name}"
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f'file; filename="{local_path.name}"',
    }
    try:
        with local_path.open("rb") as file_handle:
            response = session.post(url, data=file_handle, headers=headers, timeout=config.timeout_seconds)
    except requests.RequestException as error:
        raise DrupalApiError(f"Upload request failed for {local_path.name}: {error}") from error
    if response.status_code not in (HTTP_OK, HTTP_CREATED):
        raise DrupalApiError(f"Upload rejected for {local_path.name}: {_summarize_error(response)}")

    try:
        attributes = response.json()["data"]["attributes"]
        uploaded = UploadedFile(
            local_name=local_path.name,
            remote_name=attributes["filename"],
            url=config.base_url + attributes["uri"]["url"],
        )
    except (ValueError, KeyError, TypeError) as error:
        raise DrupalApiError(f"Unexpected response shape for {local_path.name}: {error}") from error

    logger.info(
        "uploaded",
        extra={"event": "upload_complete", "file": uploaded.local_name,
               "remote_name": uploaded.remote_name, "url": uploaded.url},
    )
    return uploaded
