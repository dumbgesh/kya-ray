"""
Unit tests for extracted desktop core and AI modules:
- desktop.core.intents
- desktop.ai.prompts
- desktop.ai.client
- desktop.core.capture
- desktop.core.hotkey
- desktop.core.orchestrator
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

# Ensure repository root is on sys.path portably
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from desktop.core.intents import (
    CORE_INTENTS,
    infer_intent,
    check_code_diagnostics,
    detect_create_quantity,
    strip_conversational_preamble,
    extract_single_creation_output,
    strip_surrounding_quotes,
    is_typed_declaration_or_code_line,
    is_assignment_line,
    is_single_line_code_assignment_or_call,
)
from desktop.ai.prompts import clean_truncated_sentence, build_intent_prompt, INTENT_INSTRUCTIONS
from desktop.ai.client import (
    ExplanationResponse,
    sanitize_ollama_metrics,
    check_ollama_prerequisites,
    request_ai_explanation,
    OllamaClient,
)
from desktop.core.capture import SelectionCapture, capture_selected_text
from desktop.core.hotkey import HotkeyListener, is_space_key, is_shortcut_key
from desktop.core.orchestrator import AppOrchestrator


class TestCoreIntents(unittest.TestCase):
    def test_core_intents_tuple(self):
        self.assertEqual(CORE_INTENTS, ("-explain", "-summarize", "-code", "-create"))

    def test_infer_intent_explain(self):
        self.assertEqual(infer_intent("What is photosynthesis?"), "-explain")
        self.assertEqual(infer_intent("quantum computing"), "-explain")
        self.assertEqual(infer_intent(""), "-explain")

    def test_infer_intent_code(self):
        self.assertEqual(infer_intent("def add(a, b):\n    return a + b"), "-code")
        self.assertEqual(infer_intent("git status"), "-code")
        self.assertEqual(infer_intent("npm run build"), "-code")
        self.assertEqual(infer_intent("Traceback (most recent call last):\n  File 'main.py'"), "-code")
        self.assertEqual(infer_intent("app = FastAPI()"), "-code")

    def test_infer_intent_create(self):
        self.assertEqual(infer_intent("write a poem about winter"), "-create")
        self.assertEqual(infer_intent("generate a python script for scraping"), "-create")
        self.assertEqual(infer_intent("give me 3 pickup lines"), "-create")

    def test_infer_intent_summarize(self):
        long_prose = "Lorem ipsum dolor sit amet, " * 15
        self.assertEqual(infer_intent(long_prose), "-summarize")
        self.assertEqual(infer_intent("summarize the main findings of this study"), "-summarize")

    def test_check_code_diagnostics_typo(self):
        code = "import panadas as pd"
        diag = check_code_diagnostics(code)
        self.assertTrue(diag["is_python"])
        self.assertTrue(diag["has_typo"])
        self.assertIn(("panadas", "pandas"), diag["typos"])
        self.assertIn("Static check detected likely import typo", diag["diagnostics_note"])

    def test_check_code_diagnostics_valid(self):
        code = "import os\ndef test(): pass"
        diag = check_code_diagnostics(code)
        self.assertTrue(diag["is_valid_python"])
        self.assertFalse(diag["has_typo"])
        self.assertIn("confirms valid Python syntax", diag["diagnostics_note"])

    def test_check_code_diagnostics_syntax_error(self):
        code = "def bad_func(:\n    pass"
        diag = check_code_diagnostics(code)
        self.assertTrue(diag["is_python"])
        self.assertFalse(diag["is_valid_python"])
        self.assertIsNotNone(diag["syntax_error"])

    def test_detect_create_quantity(self):
        self.assertEqual(detect_create_quantity("give me 3 pickup lines"), (3, True))
        self.assertEqual(detect_create_quantity("five healthy snacks"), (5, True))
        self.assertEqual(detect_create_quantity("a list of ideas"), (None, True))
        self.assertEqual(detect_create_quantity("write a poem"), (1, False))

    def test_strip_conversational_preamble(self):
        raw = "Here is a cute pickup line: Are you a magician?"
        self.assertEqual(strip_conversational_preamble(raw), "Are you a magician?")
        self.assertEqual(strip_conversational_preamble("Sure! Here's your answer: Yes."), "Yes.")

    def test_extract_single_creation_output(self):
        numbered = "1. First option\n2. Second option\n3. Third option"
        self.assertEqual(extract_single_creation_output(numbered), "First option")

    def test_strip_surrounding_quotes(self):
        self.assertEqual(strip_surrounding_quotes('"Hello world"'), "Hello world")
        self.assertEqual(strip_surrounding_quotes("'Hello world'"), "Hello world")
        self.assertEqual(strip_surrounding_quotes('“Hello world”'), "Hello world")
        self.assertEqual(strip_surrounding_quotes('He said "hello" to her.'), 'He said "hello" to her.')


class TestAIPrompts(unittest.TestCase):
    def test_clean_truncated_sentence(self):
        self.assertEqual(clean_truncated_sentence("This is complete."), "This is complete.")
        self.assertEqual(
            clean_truncated_sentence("This is complete. But this is not"),
            "This is complete."
        )
        self.assertEqual(clean_truncated_sentence("The price is 3.14 dollars."), "The price is 3.14 dollars.")

    def test_build_intent_prompt_explain(self):
        prompt = build_intent_prompt("DNS", "-explain")
        self.assertIn(INTENT_INSTRUCTIONS["-explain"], prompt)
        self.assertIn('"DNS"', prompt)

    def test_build_intent_prompt_code_diagnostics(self):
        prompt = build_intent_prompt("import panadas as pd", "-code")
        self.assertIn("likely import typo", prompt)

    def test_build_intent_prompt_create_singular(self):
        prompt = build_intent_prompt("write a short haiku", "-create")
        self.assertIn("Provide exactly ONE finished output", prompt)


class TestAIClient(unittest.TestCase):
    def test_explanation_response_structure(self):
        resp = ExplanationResponse(True, "Result text", {"eval_count": 42}, intent="-explain")
        self.assertEqual(resp[0], True)
        self.assertEqual(resp[1], "Result text")
        self.assertEqual(resp[2], {"eval_count": 42})
        self.assertTrue(resp.success)
        self.assertEqual(resp.content, "Result text")
        self.assertEqual(resp.metrics, {"eval_count": 42})
        self.assertEqual(resp.intent, "-explain")

    def test_sanitize_ollama_metrics(self):
        raw = {
            "total_duration": 12345,
            "eval_count": 30,
            "load_duration": -10,  # Negative should be None
            "prompt_eval_duration": True,  # Boolean should be rejected
            "extra_key": "sensitive prompt data",  # Should be omitted
        }
        sanitized = sanitize_ollama_metrics(raw)
        self.assertEqual(sanitized["total_duration"], 12345)
        self.assertEqual(sanitized["eval_count"], 30)
        self.assertIsNone(sanitized["load_duration"])
        self.assertIsNone(sanitized["prompt_eval_duration"])
        self.assertNotIn("extra_key", sanitized)

    @patch("urllib.request.urlopen")
    def test_check_ollama_prerequisites_ready(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"models": [{"name": "llama3.2:1b"}]}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        status, msg = check_ollama_prerequisites(model="llama3.2:1b")
        self.assertEqual(status, "ready")
        self.assertIn("running with llama3.2:1b", msg)

    @patch("urllib.request.urlopen")
    def test_check_ollama_prerequisites_missing(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"models": [{"name": "other-model"}]}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        status, msg = check_ollama_prerequisites(model="llama3.2:1b")
        self.assertEqual(status, "model_missing")

    @patch("urllib.request.urlopen")
    def test_check_ollama_prerequisites_offline(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        status, msg = check_ollama_prerequisites()
        self.assertEqual(status, "offline")

    @patch("urllib.request.urlopen")
    def test_request_ai_explanation_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "response": "Python is a high-level programming language.",
            "total_duration": 1000,
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        client = OllamaClient()
        resp = client.generate("Python", intent="-explain")
        self.assertTrue(resp.success)
        self.assertIn("Python is a high-level", resp.content)
        self.assertEqual(resp.intent, "-explain")

    @patch("urllib.request.urlopen")
    def test_request_ai_explanation_404_missing_model(self, mock_urlopen):
        error = urllib.error.HTTPError("http://127.0.0.1:11434", 404, "Not Found", {}, io.BytesIO(b""))
        mock_urlopen.side_effect = error

        client = OllamaClient(model="llama3.2:1b")
        resp = client.generate("Python")
        self.assertFalse(resp.success)
        self.assertIn("Run 'ollama pull llama3.2:1b'", resp.content)


class TestCaptureAndHotkey(unittest.TestCase):
    @patch("desktop.core.capture._capture_clipboard_selection")
    def test_selection_capture(self, mock_capture):
        mock_capture.return_value = "  hello selected text  "
        cap = SelectionCapture()
        self.assertEqual(cap.capture(), "hello selected text")

        mock_capture.return_value = ""
        self.assertEqual(cap.capture(), "")

    def test_is_space_key(self):
        from pynput.keyboard import Key, KeyCode
        self.assertTrue(is_space_key(Key.space))
        self.assertTrue(is_space_key(KeyCode(char=" ")))
        self.assertFalse(is_space_key(Key.enter))

    def test_hotkey_listener_press_release(self):
        from pynput.keyboard import Key

        triggered = []
        dismissed = []

        listener = HotkeyListener(
            on_trigger=lambda run_id: triggered.append(run_id),
            on_dismiss=lambda: dismissed.append(True),
        )

        # Press Ctrl + Alt + Space
        listener._on_press(Key.ctrl)
        listener._on_press(Key.alt)
        listener._on_press(Key.space)

        self.assertEqual(triggered, [1])
        self.assertTrue(listener.shortcut_triggered)

        # Second press while held down should be debounced / latched
        listener._on_press(Key.space)
        self.assertEqual(triggered, [1])

        # Release space -> latch reset
        listener._on_release(Key.space)
        self.assertFalse(listener.shortcut_triggered)

        # Esc pressed -> triggers dismiss callback
        listener._on_release(Key.esc)
        self.assertEqual(dismissed, [True])


class TestAppOrchestrator(unittest.TestCase):
    def test_orchestrator_pipeline_success(self):
        mock_capture = MagicMock()
        mock_capture.capture.return_value = "def add(a, b): return a + b"

        mock_ai_client = MagicMock()
        mock_ai_client.generate.return_value = ExplanationResponse(
            True, "This function adds two values.", None, intent="-code"
        )

        generating_events = []
        explanation_events = []

        orchestrator = AppOrchestrator(
            ai_client=mock_ai_client,
            capture=mock_capture,
            on_generating=lambda text, intent, run_id: generating_events.append((text, intent, run_id)),
            on_explanation=lambda text, exp, intent, run_id: explanation_events.append((text, exp, intent, run_id)),
        )

        orchestrator.process_activation(run_id=42)

        self.assertEqual(len(generating_events), 1)
        self.assertEqual(generating_events[0][1], "-code")
        self.assertEqual(generating_events[0][2], 42)

        self.assertEqual(len(explanation_events), 1)
        self.assertEqual(explanation_events[0][1], "This function adds two values.")
        self.assertEqual(explanation_events[0][2], "-code")
        self.assertEqual(explanation_events[0][3], 42)

    def test_orchestrator_pipeline_no_selection(self):
        mock_capture = MagicMock()
        mock_capture.capture.return_value = ""

        no_selection_events = []
        orchestrator = AppOrchestrator(
            capture=mock_capture,
            on_no_selection=lambda run_id: no_selection_events.append(run_id),
        )

        orchestrator.process_activation(run_id=99)
        self.assertEqual(no_selection_events, [99])

    def test_orchestrator_pipeline_error(self):
        mock_capture = MagicMock()
        mock_capture.capture.return_value = "Python text"

        mock_ai_client = MagicMock()
        mock_ai_client.generate.return_value = ExplanationResponse(
            False, "Ollama is offline", None, intent="-explain"
        )

        error_events = []
        orchestrator = AppOrchestrator(
            ai_client=mock_ai_client,
            capture=mock_capture,
            on_error=lambda text, err, run_id: error_events.append((text, err, run_id)),
        )

        orchestrator.process_activation(run_id=101)
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0][1], "Ollama is offline")
        self.assertEqual(error_events[0][2], 101)


if __name__ == "__main__":
    unittest.main()

