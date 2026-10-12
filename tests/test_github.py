import io
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

import github


class TokenTest(unittest.TestCase):
    def settings(self, text: str) -> Path:
        path = Path(self.tmp.name) / "settings.json"
        path.write_text(text, encoding="utf-8")
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("GITHUB_PERSONAL_ACCESS_TOKEN", None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_environment_wins(self):
        os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "from-env"
        path = self.settings(json.dumps({"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "from-file"}}))
        self.assertEqual(github.token(path), "from-env")

    def test_falls_back_to_settings_env_block(self):
        path = self.settings(json.dumps({"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": " from-file \n"}}))
        self.assertEqual(github.token(path), "from-file")

    def test_missing_file_is_none(self):
        self.assertIsNone(github.token(Path(self.tmp.name) / "missing.json"))

    def test_malformed_file_is_none_and_logged(self):
        path = self.settings('{"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "x",}}')
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertIsNone(github.token(path))
        self.assertIn("could not read", err.getvalue())

    def test_env_block_of_the_wrong_type_is_none(self):
        self.assertIsNone(github.token(self.settings('{"env": ["nope"]}')))


class ApiRequestTest(unittest.TestCase):
    def test_sends_bearer_token_and_parses_json(self):
        seen = {}

        class Response(io.BytesIO):
            pass

        def fake_urlopen(request, timeout):
            seen["url"], seen["auth"], seen["timeout"] = request.full_url, request.get_header("Authorization"), timeout
            seen["body"] = request.data
            return Response(b'{"login": "karim"}')

        with (
            mock.patch.object(github, "token", return_value="t0k"),
            mock.patch.object(github.urllib.request, "urlopen", fake_urlopen),
        ):
            self.assertEqual(github.api_request("graphql", {"query": "q"}, timeout=30), {"login": "karim"})
        self.assertEqual(seen["url"], "https://api.github.com/graphql")
        self.assertEqual(seen["auth"], "Bearer t0k")
        self.assertEqual(seen["timeout"], 30)
        self.assertEqual(json.loads(seen["body"]), {"query": "q"})

    def test_http_error_is_none_and_logged(self):
        error = github.urllib.error.HTTPError("u", 404, "Not Found", Message(), None)
        with (
            mock.patch.object(github, "token", return_value="t0k"),
            mock.patch.object(github.urllib.request, "urlopen", side_effect=error),
            mock.patch("sys.stderr", new_callable=io.StringIO) as err,
        ):
            self.assertIsNone(github.api_request("repos/a/b/issues/1"))
        self.assertIn("HTTP 404", err.getvalue())
