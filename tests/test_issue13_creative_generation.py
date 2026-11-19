"""
tests/test_issue13_creative_generation.py - Verification for Issue #13.

Covers:
1. Intent-aware temperature selection (0.7 for -create, 0.2 for -explain, -summarize, -code).
2. Default temperature fallback for unknown intents and None.
3. GroqProvider.generate() passing resolved temperature to Groq chat completions.
4. GroqProvider.stream() passing resolved temperature to Groq chat completions.
5. Singular Create prompt requesting exactly one finished output.
6. Creative prompt including originality, context-awareness, and cliché avoidance guidance.
7. Preserved behavior for Explain, Summarize, and Code prompts.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.services.groq_client import (
    DEFAULT_TEMPERATURE,
    INTENT_TEMPERATURES,
    GroqProvider,
    get_intent_temperature,
)
from desktop.ai.prompts import INTENT_INSTRUCTIONS, build_intent_prompt


class TestIssue13TemperatureConfiguration(unittest.TestCase):
    """Verifies intent-aware temperature resolution and defaults."""

    def test_temperature_selection_for_each_intent(self):
        """Verifies correct temperature mappings for all core intents."""
        self.assertEqual(get_intent_temperature("-create"), 0.7)
        self.assertEqual(get_intent_temperature("-explain"), 0.2)
        self.assertEqual(get_intent_temperature("-summarize"), 0.2)
        self.assertEqual(get_intent_temperature("-code"), 0.2)

        # Class/instance method consistency
        provider = GroqProvider(api_key="mock_key", client=MagicMock())
        self.assertEqual(provider.get_temperature("-create"), 0.7)
        self.assertEqual(provider.get_temperature("-explain"), 0.2)
        self.assertEqual(provider.get_temperature("-summarize"), 0.2)
        self.assertEqual(provider.get_temperature("-code"), 0.2)
        self.assertEqual(GroqProvider.get_temperature("-create"), 0.7)

    def test_default_temperature_for_unknown_intents(self):
        """Verifies unknown, empty, or None intents fall back to DEFAULT_TEMPERATURE (0.2)."""
        self.assertEqual(DEFAULT_TEMPERATURE, 0.2)
        self.assertEqual(get_intent_temperature(None), 0.2)
        self.assertEqual(get_intent_temperature(""), 0.2)
        self.assertEqual(get_intent_temperature("-unknown"), 0.2)
        self.assertEqual(get_intent_temperature("custom_intent"), 0.2)

        provider = GroqProvider(api_key="mock_key", client=MagicMock())
        self.assertEqual(provider.get_temperature(None), 0.2)
        self.assertEqual(provider.get_temperature("-nonexistent"), 0.2)


class TestIssue13GroqProviderInvocation(unittest.IsolatedAsyncioTestCase):
    """Verifies that generate() and stream() pass the resolved temperature to Groq client."""

    async def test_generate_passes_resolved_temperature_to_groq_client(self):
        """Verifies generate() passes temperature=0.7 for -create and 0.2 for others."""
        mock_client = MagicMock()
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Sample generated response."
        mock_completion.usage = None
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        provider = GroqProvider(api_key="mock_key", client=mock_client)

        # Test -create (expected temperature: 0.7)
        await provider.generate("write a pickup line", "-create")
        self.assertEqual(mock_client.chat.completions.create.call_count, 1)
        create_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["temperature"], 0.7)
        self.assertFalse(create_kwargs["stream"])

        # Test -explain (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        await provider.generate("explain DNS", "-explain")
        explain_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(explain_kwargs["temperature"], 0.2)

        # Test -code (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        await provider.generate("def foo(): return 42", "-code")
        code_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(code_kwargs["temperature"], 0.2)

        # Test -summarize (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        await provider.generate("Paragraph to summarize", "-summarize")
        summarize_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(summarize_kwargs["temperature"], 0.2)

        # Test unknown intent (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        await provider.generate("some text", "-unknown")
        unknown_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(unknown_kwargs["temperature"], 0.2)

    async def test_stream_passes_resolved_temperature_to_groq_client(self):
        """Verifies stream() passes temperature=0.7 for -create and 0.2 for others."""
        mock_client = MagicMock()

        async def _mock_stream_generator():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = "token "
            yield chunk

        mock_client.chat.completions.create = AsyncMock(side_effect=lambda **kwargs: _mock_stream_generator())

        provider = GroqProvider(api_key="mock_key", client=mock_client)

        # Test -create streaming (expected temperature: 0.7)
        tokens = []
        async for chunk in provider.stream("write a pickup line for a girl", "-create"):
            tokens.append(chunk)

        self.assertEqual(tokens, ["token "])
        create_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["temperature"], 0.7)
        self.assertTrue(create_kwargs["stream"])

        # Test -explain streaming (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        async for _ in provider.stream("What is DNS?", "-explain"):
            pass
        explain_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(explain_kwargs["temperature"], 0.2)

        # Test -code streaming (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        async for _ in provider.stream("git status", "-code"):
            pass
        code_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(code_kwargs["temperature"], 0.2)

        # Test unknown intent streaming (expected temperature: 0.2)
        mock_client.chat.completions.create.reset_mock()
        async for _ in provider.stream("something else", "-unknown"):
            pass
        unknown_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(unknown_kwargs["temperature"], 0.2)


class TestIssue13PromptRefinements(unittest.TestCase):
    """Verifies creative prompt wording, originality instructions, and preservation of existing intents."""

    def test_singular_create_prompt_requests_exactly_one_output(self):
        """Verifies that singular Create prompt maintains the single-output requirement."""
        test_inputs = [
            "write a pickup line",
            "write a pickup line for a girl",
            "give me a pickup line",
            "create a pickup line",
            "write a short haiku",
            "write a joke",
        ]
        for user_input in test_inputs:
            prompt = build_intent_prompt(user_input, "-create")
            self.assertIn("Provide exactly ONE finished output directly without multiple options or alternatives.", prompt)
            self.assertIn(f'"{user_input}"', prompt)

    def test_creative_prompt_includes_originality_and_context_awareness_guidance(self):
        """Verifies that singular Create prompt includes directives for originality and cliché avoidance."""
        prompt = build_intent_prompt("write a pickup line for a girl", "-create")
        self.assertIn("original, context-aware response", prompt)
        self.assertIn("natural language and varied phrasing", prompt)
        self.assertIn("avoiding generic clichés, stock templates, or repetitive tropes", prompt)
        self.assertIn("Do not include conversational preamble.", prompt)

    def test_existing_explain_summarize_code_prompt_behavior_remains_intact(self):
        """Verifies that -explain, -summarize, and -code prompts remain completely intact."""
        # Explain
        explain_prompt = build_intent_prompt("DNS", "-explain")
        self.assertIn(INTENT_INSTRUCTIONS["-explain"], explain_prompt)
        self.assertIn('"DNS"', explain_prompt)

        # Summarize
        summ_prompt = build_intent_prompt("Long prose content to summarize.", "-summarize")
        self.assertIn(INTENT_INSTRUCTIONS["-summarize"], summ_prompt)
        self.assertIn('"Long prose content to summarize."', summ_prompt)

        # Code explanation / review
        code_prompt = build_intent_prompt("import panadas as pd", "-code")
        self.assertIn("likely import typo", code_prompt)

        # Multiple create quantity still works
        multi_prompt = build_intent_prompt("give me 3 pickup lines", "-create")
        self.assertIn("Provide exactly 3 options directly", multi_prompt)


if __name__ == "__main__":
    unittest.main()
