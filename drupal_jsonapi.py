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
import uuid
from typing import Any, BinaryIO
from urllib.parse import urljoin

import requests

from config import UploaderConfig
from reconcile import RemoteFile

logger = logging.getLogger(__name__)

JSONAPI_CONTENT_TYPE = "application/vnd.api+json"
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_SERVER_ERROR = 500
RETRY_HINT = "Drupal may still have stored the file; rerunning skips files already attached to the node."


class DrupalApiError(Exception):
    """Raised when a Drupal JSON:API request fails or returns an unexpected shape."""


def is_canonical_uuid(value: Any) -> bool:
    """True for a lowercase hyphenated UUID string, the only form Drupal emits."""
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def build_file_url(base_url: str, file_url: str) -> str:
    """Resolve Drupal's root-relative uri.url against the site origin, not the configured base path."""
    return urljoin(base_url + "/", file_url)


def _format_error_item(error_item: dict[str, Any]) -> str:
    """Render one JSON:API error object as 'title: detail'."""
    return f"{error_item.get('title', '')}: {error_item.get('detail', '')}"


def _summarize_error(response: requests.Response) -> str:
    """Pull JSON:API error detail if present; otherwise the status line. Never dumps HTML bodies."""
    status_line = f"HTTP {response.status_code} {response.reason}"
    try:
        body = response.json()
    except ValueError:
        return status_line
    errors = body.get("errors") if isinstance(body, dict) else None
    if not isinstance(errors, list):
        return status_line
    details = "; ".join(_format_error_item(item) for item in errors if isinstance(item, dict))
    return f"HTTP {response.status_code} {details}" if details else status_line


def _decode_json_object(response: requests.Response, action: str) -> dict[str, Any]:
    """Decode a response body that must be a JSON object."""
    try:
        body = response.json()
    except ValueError as error:
        content_type = response.headers.get("Content-Type", "unknown")
        raise DrupalApiError(
            f"{action}: response is not JSON (HTTP {response.status_code}, Content-Type {content_type})"
        ) from error
    if not isinstance(body, dict):
        raise DrupalApiError(f"{action}: expected a JSON object, got {type(body).__name__}")
    return body


def _get_json_object(
    session: requests.Session, config: UploaderConfig, url: str, action: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET a JSON:API URL and return its decoded body, or raise DrupalApiError."""
    try:
        response = session.get(url, params=params, timeout=config.timeout_seconds)
    except requests.RequestException as error:
        raise DrupalApiError(f"{action} request failed: {error}") from error
    if response.status_code != HTTP_OK:
        raise DrupalApiError(f"{action} failed: {_summarize_error(response)}")
    return _decode_json_object(response, action)


def _parse_remote_file(resource: Any, config: UploaderConfig, action: str) -> RemoteFile:
    """Turn a JSON:API file--file resource object into a RemoteFile."""
    try:
        attributes = resource["attributes"]
        filename = attributes["filename"]
        size = attributes["filesize"]
        file_url = attributes["uri"]["url"]
    except (KeyError, TypeError) as error:
        raise DrupalApiError(f"{action}: unexpected file resource shape, missing {error}") from error
    if not isinstance(filename, str) or not isinstance(size, int) or not isinstance(file_url, str):
        raise DrupalApiError(f"{action}: file resource has wrongly typed filename, filesize or uri.url")
    return RemoteFile(filename=filename, size=size, url=build_file_url(config.base_url, file_url))


def _field_url(config: UploaderConfig, node_uuid: str) -> str:
    """URL of the node's file field, used both to list and to upload files."""
    return f"{config.base_url}/jsonapi/node/{config.node_type}/{node_uuid}/{config.field_name}"


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
    body = _get_json_object(session, config, url, "Node lookup", params)

    data = body.get("data")
    if not isinstance(data, list):
        raise DrupalApiError("Node lookup: response has no 'data' list")
    if len(data) != 1:
        raise DrupalApiError(
            f"Expected exactly one node of type {config.node_type} with nid {config.node_id}, found {len(data)}"
        )
    node_uuid = data[0].get("id") if isinstance(data[0], dict) else None
    # The UUID goes into later URL paths, so accept nothing but a canonical UUID.
    if not is_canonical_uuid(node_uuid):
        raise DrupalApiError(f"Node lookup: response id is not a UUID: {node_uuid!r}")
    return node_uuid


def fetch_attached_files(session: requests.Session, config: UploaderConfig, node_uuid: str) -> list[RemoteFile]:
    """List files already in the node's field. Refuses single-value fields, where uploads replace the file."""
    action = f"Listing files in {config.field_name}"
    body = _get_json_object(session, config, _field_url(config, node_uuid), action)
    data = body.get("data")
    # JSON:API returns an object (or null) for single-value fields and a list for multi-value ones.
    if not isinstance(data, list):
        raise DrupalApiError(
            f"Field {config.field_name} holds only one file, so each upload would replace the last. "
            "Set its 'Allowed number of values' to Unlimited."
        )
    return [_parse_remote_file(resource, config, action) for resource in data]


def upload_pdf(
    session: requests.Session, config: UploaderConfig, node_uuid: str, filename: str, file_handle: BinaryIO
) -> RemoteFile:
    """Upload one PDF into the node's file field. Returns the name and URL Drupal assigned."""
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f'file; filename="{filename}"',
    }
    try:
        response = session.post(
            _field_url(config, node_uuid), data=file_handle, headers=headers, timeout=config.timeout_seconds
        )
    except requests.RequestException as error:
        raise DrupalApiError(f"Upload request failed for {filename}: {error}. {RETRY_HINT}") from error
    except OSError as error:
        raise DrupalApiError(f"Could not read {filename} while uploading: {error}") from error
    if response.status_code >= HTTP_SERVER_ERROR:
        raise DrupalApiError(f"Upload failed for {filename}: {_summarize_error(response)}. {RETRY_HINT}")
    if response.status_code not in (HTTP_OK, HTTP_CREATED):
        raise DrupalApiError(f"Upload rejected for {filename}: {_summarize_error(response)}")

    action = f"Upload of {filename}"
    uploaded = _parse_remote_file(_decode_json_object(response, action).get("data"), config, action)
    logger.info(
        "uploaded",
        extra={"event": "upload_complete", "file": filename, "remote_name": uploaded.filename, "url": uploaded.url},
    )
    return uploaded
