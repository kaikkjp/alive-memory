import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

from pipeline import embed as embed_mod


class _FakeResponse:
    def __init__(self, status, payload=None, body="err"):
        self.status = status
        self._payload = payload if payload is not None else {}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._body

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, headers=None, json=None):
        self.calls.append((url, headers, json))
        return self.response


class EmbedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orig_provider = embed_mod.EMBED_PROVIDER
        self.orig_key = embed_mod._OPENAI_API_KEY
        embed_mod._session_var.set(None)

    def tearDown(self):
        embed_mod.EMBED_PROVIDER = self.orig_provider
        embed_mod._OPENAI_API_KEY = self.orig_key
        embed_mod._session_var.set(None)

    async def test_embed_returns_none_for_blank_text(self):
        self.assertIsNone(await embed_mod.embed(""))
        self.assertIsNone(await embed_mod.embed("   "))

    async def test_embed_unknown_provider_returns_none(self):
        embed_mod.EMBED_PROVIDER = "unknown"
        self.assertIsNone(await embed_mod.embed("hello"))

    async def test_embed_local_returns_none(self):
        embed_mod.EMBED_PROVIDER = "local"
        self.assertIsNone(await embed_mod.embed("hello"))

    async def test_openai_non_200_returns_none(self):
        session = _FakeSession(_FakeResponse(status=500, body="bad"))
        out = await embed_mod._openai_post(
            session,
            headers={"Authorization": "Bearer x"},
            payload={"model": "m", "input": "hello"},
        )
        self.assertIsNone(out)

    async def test_openai_wrong_dimension_returns_none(self):
        payload = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        session = _FakeSession(_FakeResponse(status=200, payload=payload))
        out = await embed_mod._openai_post(
            session,
            headers={"Authorization": "Bearer x"},
            payload={"model": "m", "input": "hello"},
        )
        self.assertIsNone(out)

    async def test_embed_handles_malformed_openai_response(self):
        embed_mod.EMBED_PROVIDER = "openai"
        embed_mod._OPENAI_API_KEY = "sk-test"
        with patch.object(embed_mod, "_openai_request", new=AsyncMock(side_effect=KeyError("data"))):
            out = await embed_mod.embed("hello")
        self.assertIsNone(out)

    async def test_embed_session_reuses_one_session_within_batch(self):
        embed_mod.EMBED_PROVIDER = "openai"
        embed_mod._OPENAI_API_KEY = "sk-test"
        seen_session_ids = []

        async def fake_post(session, _headers, _payload):
            seen_session_ids.append(id(session))
            return [0.0] * embed_mod.EMBED_DIMENSION

        with patch.object(embed_mod, "_openai_post", new=fake_post):
            async with embed_mod.embed_session():
                out1 = await embed_mod.embed("alpha")
                out2 = await embed_mod.embed("beta")

        self.assertIsNotNone(out1)
        self.assertIsNotNone(out2)
        self.assertEqual(len(seen_session_ids), 2)
        self.assertEqual(seen_session_ids[0], seen_session_ids[1])

    async def test_embed_session_contextvar_isolated_across_concurrent_tasks(self):
        async def capture_session():
            async with embed_mod.embed_session():
                sess = embed_mod._session_var.get()
                await asyncio.sleep(0)
                return sess

        s1, s2 = await asyncio.gather(capture_session(), capture_session())
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertIsNot(s1, s2)
        self.assertIsNone(embed_mod._session_var.get())
