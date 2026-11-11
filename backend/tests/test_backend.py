"""
Unit and integration tests for Kya-Ray Cloud Backend:
- backend.config
- backend.services.ai_provider
- backend.services.groq_client
- backend.routes.ai
- backend.main
"""

import asyncio
import os
import sys
from typing import Optional
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repository root is on sys.path portably
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from fastapi.testclient import TestClient

from backend.config import Settings, get_settings
from backend.main import app
from backend.routes.ai import get_ai_provider, set_ai_provider
from backend.services.ai_provider import AIProvider, AIResponse
from backend.services.groq_client import GroqProvider


class MockTestProvider(AIProvider):
    """Predictable mock AI provider for API route testing."""

    def __init__(self, should_fail: Optional[str] = None):
        self.should_fail = should_fail

    def is_configured(self) -> bool:
        return True

    async def generate(self, text: str, intent: str) -> AIResponse:
        if self.should_fail == "auth":
            raise PermissionError("Invalid Groq API Key")
        if self.should_fail == "rate_limit":
            raise RuntimeError("GroqCloud rate limit reached: 429")
        if self.should_fail == "connection":
            raise ConnectionError("Failed to connect to GroqCloud API")
        if self.should_fail == "unknown":
            raise ValueError("Unexpected provider failure")

        return AIResponse(
            success=True,
            content=f"Mock response for [{intent}]: {text[:30]}",
            intent=intent,
            model="mock-groq-model",
            usage={"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
        )

    async def stream(self, text: str, intent: str):
        if self.should_fail == "auth":
            raise PermissionError("Invalid Groq API Key")
        if self.should_fail == "connection":
            raise ConnectionError("Failed to connect to GroqCloud API")

        for token in ["Mock", " ", "streamed", " ", "content."]:
            yield token


class TestBackendConfig(unittest.TestCase):
    def test_default_settings(self):
        settings = get_settings()
        self.assertEqual(settings.APP_VERSION, "1.0.0-beta.2")
        self.assertGreaterEqual(settings.MAX_INPUT_LENGTH, 1000)
        self.assertTrue(hasattr(settings, "GROQ_MODEL"))

    def test_env_override(self):
        with patch.dict(os.environ, {"GROQ_MODEL": "custom-groq-model-v2", "BACKEND_PORT": "9090"}):
            settings = Settings()
            self.assertEqual(settings.GROQ_MODEL, "custom-groq-model-v2")
            self.assertEqual(settings.PORT, 9090)


class TestGroqProvider(unittest.IsolatedAsyncioTestCase):
    def test_is_configured(self):
        unconfigured = GroqProvider(api_key="")
        self.assertFalse(unconfigured.is_configured())

        configured = GroqProvider(api_key="gsk_valid_mock_key_12345")
        self.assertTrue(configured.is_configured())

    def test_build_messages_intent_integration(self):
        provider = GroqProvider(api_key="mock_key", model="llama-3.3-70b-versatile")
        messages = provider._build_messages("git status", "-code")
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Kya-Ray", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn('"git status"', messages[1]["content"])

    async def test_generate_mocked_groq_sdk(self):
        mock_client = AsyncMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Python is an interpreted programming language."
        mock_completion.usage = MagicMock()
        mock_completion.usage.prompt_tokens = 12
        mock_completion.usage.completion_tokens = 8
        mock_completion.usage.total_tokens = 20

        mock_client.chat.completions.create.return_value = mock_completion

        provider = GroqProvider(api_key="mock_key", client=mock_client)
        resp = await provider.generate("What is Python?", "-explain")

        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Python is an interpreted programming language.")
        self.assertEqual(resp.intent, "-explain")
        self.assertEqual(resp.usage["total_tokens"], 20)

    async def test_stream_mocked_groq_sdk(self):
        mock_client = AsyncMock()

        # Mock streaming chunks
        class MockChunk:
            def __init__(self, token):
                self.choices = [MagicMock()]
                self.choices[0].delta.content = token

        class MockAsyncStream:
            def __init__(self, items):
                self.items = items

            def __aiter__(self):
                self._iter = iter(self.items)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

        mock_client.chat.completions.create.return_value = MockAsyncStream([
            MockChunk("Hello"), MockChunk(" "), MockChunk("world")
        ])

        provider = GroqProvider(api_key="mock_key", client=mock_client)
        collected = []
        async for chunk in provider.stream("Hi", "-explain"):
            collected.append(chunk)

        self.assertEqual("".join(collected), "Hello world")


class TestBackendAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        set_ai_provider(MockTestProvider())

    def tearDown(self):
        set_ai_provider(GroqProvider())

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "kya-ray-backend")
        self.assertTrue(data["groq_configured"])
        self.assertIn("model", data)

    def test_generate_endpoint_success(self):
        payload = {"text": "Explain async await in Python", "intent": "-explain"}
        response = self.client.post("/api/v1/ai/generate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "-explain")
        self.assertIn("Mock response", data["content"])

    def test_generate_auto_intent_detection(self):
        # Text without intent specified should automatically trigger code intent
        payload = {"text": "def compute_sum(a, b):\n    return a + b"}
        response = self.client.post("/api/v1/ai/generate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["intent"], "-code")

    def test_generate_validation_empty_text(self):
        response = self.client.post("/api/v1/ai/generate", json={"text": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be empty", response.json()["detail"])

    def test_generate_validation_oversized_text(self):
        oversized = "x" * 20005
        response = self.client.post("/api/v1/ai/generate", json={"text": oversized})
        self.assertEqual(response.status_code, 422)

    def test_generate_auth_error_handling(self):
        set_ai_provider(MockTestProvider(should_fail="auth"))
        response = self.client.post("/api/v1/ai/generate", json={"text": "Hello"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid Groq API Key", response.json()["detail"])

    def test_generate_rate_limit_error_handling(self):
        set_ai_provider(MockTestProvider(should_fail="rate_limit"))
        response = self.client.post("/api/v1/ai/generate", json={"text": "Hello"})
        self.assertEqual(response.status_code, 429)

    def test_generate_connection_error_handling(self):
        set_ai_provider(MockTestProvider(should_fail="connection"))
        response = self.client.post("/api/v1/ai/generate", json={"text": "Hello"})
        self.assertEqual(response.status_code, 503)

    def test_stream_endpoint_success(self):
        payload = {"text": "Stream test text", "intent": "-explain"}
        response = self.client.post("/api/v1/ai/stream", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        body = response.text
        self.assertIn("data: ", body)
        self.assertIn("[DONE]", body)
        self.assertIn("streamed", body)

    def test_stream_endpoint_empty_text(self):
        response = self.client.post("/api/v1/ai/stream", json={"text": ""})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
