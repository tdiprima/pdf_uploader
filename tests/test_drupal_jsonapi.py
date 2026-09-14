import io
import json
import unittest
from pathlib import Path
from unittest import mock

import requests

from config import UploaderConfig
from drupal_jsonapi import (
    DrupalApiError,
    _summarize_error,
    build_file_url,
    fetch_attached_files,
    fetch_node_uuid,
    upload_pdf,
)

NODE_UUID = "0b7f2c8e-5d1a-4c3b-9e6f-1a2b3c4d5e6f"


def make_config(base_url: str = "https://example.com") -> UploaderConfig:
    return UploaderConfig(base_url=base_url, username="u", password="p", node_type="page", node_id=1,
                          field_name="field_pdf", local_dir=Path("."), timeout_seconds=5)


def make_response(status_code: int, body: bytes, content_type: str = "application/vnd.api+json") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.reason = "Reason"
    response._content = body
    response.headers["Content-Type"] = content_type
    return response


def file_resource(filename: str = "a.pdf", size: int = 10, url: str = "/sites/default/files/a.pdf") -> dict:
    return {"type": "file--file", "attributes": {"filename": filename, "filesize": size, "uri": {"url": url}}}


def json_bytes(value) -> bytes:
    return json.dumps(value).encode()


class BuildFileUrlTest(unittest.TestCase):
    def test_root_relative_url_under_subdirectory_install(self):
        self.assertEqual(build_file_url("https://example.com/drupal", "/drupal/sites/default/files/a.pdf"),
                         "https://example.com/drupal/sites/default/files/a.pdf")

    def test_root_install(self):
        self.assertEqual(build_file_url("https://example.com", "/sites/default/files/a.pdf"),
                         "https://example.com/sites/default/files/a.pdf")

    def test_absolute_url_kept(self):
        self.assertEqual(build_file_url("https://example.com", "https://cdn.example.com/a.pdf"),
                         "https://cdn.example.com/a.pdf")


class SummarizeErrorTest(unittest.TestCase):
    def test_jsonapi_errors(self):
        body = json_bytes({"errors": [{"title": "Unprocessable", "detail": "too many values"}]})
        self.assertEqual(_summarize_error(make_response(422, body)), "HTTP 422 Unprocessable: too many values")

    def test_malformed_bodies_fall_back_to_status_line(self):
        for body in [b"[]", b"<html>bad gateway</html>", b"", b'{"errors": "nope"}', b'{"errors": [1, null]}',
                     b"null", b'"text"']:
            with self.subTest(body=body):
                self.assertEqual(_summarize_error(make_response(502, body)), "HTTP 502 Reason")


class FetchNodeUuidTest(unittest.TestCase):
    def fetch_with(self, response: requests.Response) -> str:
        session = mock.Mock(spec=requests.Session)
        session.get.return_value = response
        return fetch_node_uuid(session, make_config())

    def test_returns_uuid(self):
        self.assertEqual(self.fetch_with(make_response(200, json_bytes({"data": [{"id": NODE_UUID}]}))), NODE_UUID)

    def test_malformed_responses_raise_drupal_api_error(self):
        bodies = [b"<html>login</html>", b"[]", b"null", json_bytes({"data": {}}), json_bytes({"data": []}),
                  json_bytes({"data": [{"id": NODE_UUID}, {"id": NODE_UUID}]}), json_bytes({"data": ["x"]}),
                  json_bytes({"data": [{"id": "../../user/1"}]}), json_bytes({"data": [{"id": 5}]}),
                  json_bytes({"data": [{"id": "{" + NODE_UUID + "}"}]})]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(DrupalApiError):
                self.fetch_with(make_response(200, body))

    def test_network_error(self):
        session = mock.Mock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("down")
        with self.assertRaises(DrupalApiError):
            fetch_node_uuid(session, make_config())


class FetchAttachedFilesTest(unittest.TestCase):
    def fetch_with(self, body: bytes, base_url: str = "https://example.com"):
        session = mock.Mock(spec=requests.Session)
        session.get.return_value = make_response(200, body)
        return fetch_attached_files(session, make_config(base_url), NODE_UUID)

    def test_empty_multi_value_field(self):
        self.assertEqual(self.fetch_with(json_bytes({"data": []})), [])

    def test_parses_files(self):
        files = self.fetch_with(json_bytes({"data": [file_resource(url="/drupal/sites/default/files/a.pdf")]}),
                                base_url="https://example.com/drupal")
        self.assertEqual(files[0].filename, "a.pdf")
        self.assertEqual(files[0].size, 10)
        self.assertEqual(files[0].url, "https://example.com/drupal/sites/default/files/a.pdf")

    def test_single_value_field_is_refused(self):
        for data in [None, file_resource()]:
            with self.subTest(data=data), self.assertRaisesRegex(DrupalApiError, "Unlimited"):
                self.fetch_with(json_bytes({"data": data}))

    def test_malformed_file_resources(self):
        for resource in [{}, "x", {"attributes": {"filename": "a.pdf"}}, file_resource(size="10"),
                         file_resource(url=None), {"attributes": {"filename": 1, "filesize": 1, "uri": {"url": "/"}}}]:
            with self.subTest(resource=resource), self.assertRaises(DrupalApiError):
                self.fetch_with(json_bytes({"data": [resource]}))


class UploadPdfTest(unittest.TestCase):
    def upload_with(self, session: mock.Mock, base_url: str = "https://example.com"):
        return upload_pdf(session, make_config(base_url), NODE_UUID, "a.pdf", io.BytesIO(b"%PDF-1"))

    def session_returning(self, response: requests.Response) -> mock.Mock:
        session = mock.Mock(spec=requests.Session)
        session.post.return_value = response
        return session

    def test_success_uses_origin_relative_url(self):
        body = json_bytes({"data": file_resource("a_0.pdf", 6, "/drupal/sites/default/files/a_0.pdf")})
        session = self.session_returning(make_response(201, body))
        uploaded = self.upload_with(session, base_url="https://example.com/drupal")
        self.assertEqual(uploaded.url, "https://example.com/drupal/sites/default/files/a_0.pdf")
        headers = session.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Content-Disposition"], 'file; filename="a.pdf"')

    def test_timeout_mentions_rerun(self):
        session = mock.Mock(spec=requests.Session)
        session.post.side_effect = requests.Timeout("read timed out")
        with self.assertRaisesRegex(DrupalApiError, "rerunning"):
            self.upload_with(session)

    def test_server_error_mentions_rerun(self):
        with self.assertRaisesRegex(DrupalApiError, "rerunning"):
            self.upload_with(self.session_returning(make_response(502, b"[]")))

    def test_client_error_is_rejection(self):
        body = json_bytes({"errors": [{"title": "Unprocessable", "detail": "field full"}]})
        with self.assertRaisesRegex(DrupalApiError, "rejected.*field full"):
            self.upload_with(self.session_returning(make_response(422, body)))

    def test_local_read_error_becomes_drupal_api_error(self):
        session = mock.Mock(spec=requests.Session)
        session.post.side_effect = PermissionError("denied")
        with self.assertRaises(DrupalApiError):
            self.upload_with(session)

    def test_malformed_success_bodies(self):
        for body in [b"<html>ok</html>", b"[]", json_bytes({"data": None}), json_bytes({"data": []})]:
            with self.subTest(body=body), self.assertRaises(DrupalApiError):
                self.upload_with(self.session_returning(make_response(200, body)))


if __name__ == "__main__":
    unittest.main()
