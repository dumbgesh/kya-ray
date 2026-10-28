"""
Unit tests for Kya-Ray context-aware intent selection and prompt construction.
Tests verify:
1. Intent inference across terminal commands, code snippets, errors, prose, and prompts.
2. Prompt instruction formatting and curly-brace safety (JSON/code).
3. ExplanationResponse tuple backward compatibility.
4. Model request integration and fallback handling.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure workspace root is in python path
sys.path.insert(0, "c:/kya-ray")

from prototype.main import (
    CORE_INTENTS,
    INTENT_INSTRUCTIONS,
    ExplanationResponse,
    build_intent_prompt,
    clean_truncated_sentence,
    infer_intent,
    request_ai_explanation,
)


class TestIntentInference(unittest.TestCase):
    """Verifies heuristic intent classification across all four core intents."""

    def test_core_intents_defined(self):
        self.assertEqual(CORE_INTENTS, ("-explain", "-summarize", "-code", "-create"))
        for intent in CORE_INTENTS:
            self.assertIn(intent, INTENT_INSTRUCTIONS)

    def test_infer_code_terminal_commands(self):
        cases = [
            "git commit -m 'feat: add feature'",
            "$ git status",
            "> npm install --save-dev typescript",
            "docker run -d -p 8080:80 nginx:alpine",
            "curl -X POST https://api.example.com/data",
            "pip install -r requirements.txt",
            "pytest tests/test_app.py",
            "ls -la /var/log/nginx",
        ]
        for cmd in cases:
            with self.subTest(command=cmd):
                self.assertEqual(infer_intent(cmd), "-code")

    def test_infer_code_syntax(self):
        cases = [
            "def calculate_total(items):\n    return sum(item.price for item in items)",
            "class UserRepository:\n    def find_by_id(self, user_id): pass",
            "const handleClick = (event) => {\n    console.log(event);\n};",
            "import os\nfrom pathlib import Path",
            "let items = [1, 2, 3]; items.map(x => x * 2);",
            "try:\n    perform_action()\nexcept ValueError as err:\n    pass",
            "app = FastAPI();",
        ]
        for snippet in cases:
            with self.subTest(snippet=snippet):
                self.assertEqual(infer_intent(snippet), "-code")

    def test_infer_code_multiline_typed_declarations(self):
        """Verifies multiline typed variable declarations and arithmetic without requiring semicolons."""
        cases = [
            "int a = 1\nint b = 10\nint sum\nsum = a + b\nprint('sum)",
            "int x = 42\nint y = 58\nint total = x + y",
            "float rate = 0.05\nfloat principal = 1000.0\nfloat interest = principal * rate",
            "double balance = 500.25;\ndouble withdrawal = 40.00;",
            "bool is_valid = true\nbool has_access = false",
            "char letter = 'k'\nchar next = 'y'",
            "void execute_task(int count)",
            "val items = listOf(1, 2, 3)\nval total = items.sum()",
        ]
        for snippet in cases:
            with self.subTest(snippet=snippet):
                self.assertEqual(infer_intent(snippet), "-code")

    def test_infer_code_stack_traces_and_errors(self):
        cases = [
            "Traceback (most recent call last):\n  File 'main.py', line 12, in <module>\nIndexError: list index out of range",
            "TypeError: Cannot read properties of undefined (reading 'length')",
            "fatal: not a git repository (or any of the parent directories): .git",
            "SyntaxError: unexpected EOF while parsing at line 42",
            "bash: /usr/local/bin/custom_tool: command not found",
        ]
        for err in cases:
            with self.subTest(error=err):
                self.assertEqual(infer_intent(err), "-code")

    def test_infer_create_directives(self):
        cases = [
            "Write a Python script to parse an Apache access log and count 404 errors.",
            "Create an email draft apologizing for the service outage to enterprise clients.",
            "Generate a markdown table comparing PostgreSQL, MySQL, and SQLite.",
            "Draft a concise announcement for the v2.0 product release.",
            "Make a list of key performance metrics for our web application.",
            "Implement a retry decorator with exponential backoff.",
            "Template for a pull request description.",
        ]
        for prompt in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(infer_intent(prompt), "-create")

    def test_infer_summarize_long_prose(self):
        long_prose = (
            "The architecture of modern distributed systems relies heavily on asynchronous event "
            "streaming and message queues to decouple services. By ensuring that microservices "
            "communicate through persistent logs like Apache Kafka or RabbitMQ, teams can scale "
            "independent consumer services without bottlenecking the producer pipelines. In addition, "
            "event sourcing guarantees a tamper-evident audit trail of state changes across the entire "
            "enterprise cluster, allowing historical replay during incident debugging and Disaster "
            "Recovery operations."
        )
        self.assertGreaterEqual(len(long_prose.split()), 60)
        self.assertEqual(infer_intent(long_prose), "-summarize")

        multi_paragraph = (
            "Sprint planning for Q4 commenced yesterday with leadership.\n\n"
            "Key milestones include database migration, zero-downtime deployments, "
            "and delivering the cross-platform desktop prototype on schedule."
        )
        self.assertEqual(infer_intent(multi_paragraph), "-summarize")

    def test_infer_explain_concepts_and_short_text(self):
        cases = [
            "Orthogonal persistence",
            "Idempotency",
            "Backpressure in reactive streams",
            "What is a goroutine?",
            "CAP theorem",
        ]
        for concept in cases:
            with self.subTest(concept=concept):
                self.assertEqual(infer_intent(concept), "-explain")

    def test_infer_explain_ambiguous_or_empty_text(self):
        self.assertEqual(infer_intent(""), "-explain")
        self.assertEqual(infer_intent("   "), "-explain")
        self.assertEqual(infer_intent(None), "-explain")
        self.assertEqual(infer_intent("yield"), "-explain")
        self.assertEqual(infer_intent("closure"), "-explain")

    def test_infer_explain_prose_negative_cases(self):
        """
        Negative tests: Ensures ordinary prose containing words like 'international'
        or 'integral' is not falsely classified as -code.
        """
        cases = [
            "International relations and foreign policy in Europe",
            "An integral part of software development is automated testing.",
            "Interior design trends for modern startup offices",
            "Integration testing across microservices architectures",
            "Interview questions for senior backend engineering roles",
            "Intellectual property law protecting software patents",
            "Introduction to database indexing and query optimization",
            "Internal communication within engineering teams",
        ]
        for prose in cases:
            with self.subTest(prose=prose):
                self.assertEqual(infer_intent(prose), "-explain")

    def test_manual_regression_cases(self):
        """Verifies the five observed manual test inputs from user verification."""
        dw_etl_paragraph = (
            "A data warehouse is a centralized repository designed to store structured data "
            "from multiple disparate sources for analytical reporting. During the extract, "
            "transform, and load (ETL) process, raw transactional records are cleansed, standardized, "
            "and consolidated into dimensional schemas. Business intelligence analysts query these "
            "warehouse tables to identify historical trends and evaluate organizational performance indicators. "
            "By maintaining historical snapshots and separating analytics workloads from production operational "
            "databases, enterprise systems maintain high throughput and reliability."
        )

        cases = [
            ("cd asthma-attack-prediction", "-code"),
            ("def calculate_average(numbers): return sum(numbers) / len(numbers)", "-code"),
            ("Categorical Naive Bayes", "-explain"),
            (dw_etl_paragraph, "-summarize"),
            (
                "Write a professional email asking my professor for an extension on an assignment because I was unwell.",
                "-create",
            ),
        ]

        for text, expected in cases:
            with self.subTest(input_text=text[:40]):
                self.assertEqual(infer_intent(text), expected)


class TestPromptConstruction(unittest.TestCase):
    """Verifies prompt construction and formatting safety."""

    def test_build_prompt_all_intents(self):
        for intent in CORE_INTENTS:
            prompt = build_intent_prompt("Sample test input", intent)
            self.assertIn("Sample test input", prompt)
            self.assertIn(INTENT_INSTRUCTIONS[intent], prompt)

    def test_build_prompt_curly_brace_safety(self):
        """Ensures text with curly braces (code, JSON) does not crash with KeyError."""
        code_with_braces = '{"status": 200, "data": {"users": [1, 2, 3]}}'
        prompt = build_intent_prompt(code_with_braces, "-code")
        self.assertIn(code_with_braces, prompt)

    def test_build_prompt_fallback_on_unknown_intent(self):
        prompt = build_intent_prompt("Unknown intent test", "-unknown")
        self.assertIn(INTENT_INSTRUCTIONS["-explain"], prompt)

    def test_prompt_instructions_constraints(self):
        """Verifies specific reliability guidance rules in intent prompt instructions."""
        # -code must place syntax error / typo correction guidance near the beginning
        code_inst = INTENT_INSTRUCTIONS["-code"].lower()
        self.assertIn("not claim", code_inst)
        self.assertIn("executed", code_inst)
        self.assertIn("syntax error", code_inst)
        self.assertIn("misspelled", code_inst)
        self.assertLess(code_inst.find("syntax error"), 160)

        # -summarize must guide finishing in 1 to 2 sentences without trailing off
        summ_inst = INTENT_INSTRUCTIONS["-summarize"].lower()
        self.assertIn("1 to 2", summ_inst)
        self.assertIn("trailing off", summ_inst)

        # -create must guide fulfilling benign requests without assuming deception
        create_inst = INTENT_INSTRUCTIONS["-create"].lower()
        self.assertIn("deception", create_inst)
        self.assertIn("legitimate", create_inst)


class TestExplanationResponse(unittest.TestCase):
    """Verifies ExplanationResponse tuple subclass backward compatibility."""

    def test_tuple_unpacking(self):
        resp = ExplanationResponse(True, "Response text", {"eval_count": 25}, intent="-code")
        success, content, metrics = resp
        self.assertTrue(success)
        self.assertEqual(content, "Response text")
        self.assertEqual(metrics, {"eval_count": 25})
        self.assertEqual(resp.intent, "-code")
        self.assertEqual(len(resp), 3)

    def test_properties(self):
        resp = ExplanationResponse(False, "Failed connection", None, intent="-explain")
        self.assertFalse(resp.success)
        self.assertEqual(resp.content, "Failed connection")
        self.assertIsNone(resp.metrics)
        self.assertEqual(resp.intent, "-explain")


class TestRequestAIExplanationIntegration(unittest.TestCase):
    """Verifies request_ai_explanation intent dispatching and return types."""

    @patch("prototype.main.urllib.request.urlopen")
    def test_request_ai_inferred_intent(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = (
            b'{"response": "Git status shows modified files.", "eval_count": 10, "eval_duration": 500000000}'
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = request_ai_explanation("git status")
        self.assertTrue(res.success)
        self.assertEqual(res.intent, "-code")
        self.assertIn("Git status", res.content)
        self.assertIsNotNone(res.metrics)
        self.assertEqual(res.metrics["eval_count"], 10)

    @patch("prototype.main.urllib.request.urlopen")
    def test_request_ai_explicit_intent_override(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"response": "Summary output.", "eval_count": 8}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Even with short concept text, explicit intent is respected
        res = request_ai_explanation("Orthogonal persistence", intent="-summarize")
        self.assertTrue(res.success)
        self.assertEqual(res.intent, "-summarize")


class TestAnswerReliabilityRegression(unittest.TestCase):
    """
    Regression tests for answer reliability and truthfulness across five key test cases:
    1. Humera: Ambiguous / unfamiliar term -> acknowledge uncertainty, do not invent origins/facts.
    2. Humera means zenith bird: Unverified claim -> distinguish claims from verified facts, no auto-endorsement.
    3. Porcelain: Known term -> concise, accurate explanation, no trailing off.
    4. Windows (CLRF): Typo / ambiguous term -> identify typo (CRLF) and never invent command execution/buffer resets.
    5. import panadas as pd: Code snippet with misspelled module -> identify typo (pandas) and obvious correction.
    """

    FIVE_EXAMPLES = [
        ("Humera", "-explain"),
        ("Humera means zenith bird", "-explain"),
        ("Porcelain", "-explain"),
        ("Windows (CLRF)", "-explain"),
        ("import panadas as pd", "-code"),
    ]

    def test_regression_intent_inference_for_all_five_cases(self):
        """Verifies deterministic intent classification preserves expected categories without classifier changes."""
        for text, expected_intent in self.FIVE_EXAMPLES:
            with self.subTest(input_text=text):
                self.assertEqual(infer_intent(text), expected_intent)

    def test_regression_humera_prompt_construction(self):
        """Verifies prompt for 'Humera' instructs acknowledging uncertainty without inventing facts."""
        prompt = build_intent_prompt("Humera", "-explain")
        self.assertIn('"Humera"', prompt)
        prompt_lower = prompt.lower()
        self.assertIn("unfamiliar", prompt_lower)
        self.assertIn("acknowledge uncertainty", prompt_lower)
        self.assertIn("avoid inventing", prompt_lower)

    def test_regression_humera_claim_prompt_construction(self):
        """Verifies prompt for 'Humera means zenith bird' instructs distinguishing claims from verified facts."""
        prompt = build_intent_prompt("Humera means zenith bird", "-explain")
        self.assertIn('"Humera means zenith bird"', prompt)
        prompt_lower = prompt.lower()
        self.assertIn("distinguish claims", prompt_lower)
        self.assertIn("verified facts", prompt_lower)
        self.assertIn("not automatically endorse", prompt_lower)

    def test_regression_porcelain_prompt_construction(self):
        """Verifies prompt for 'Porcelain' instructs concise, accurate explanation without trailing off."""
        prompt = build_intent_prompt("Porcelain", "-explain")
        self.assertIn('"Porcelain"', prompt)
        prompt_lower = prompt.lower()
        self.assertIn("accurately", prompt_lower)
        self.assertIn("1 to 2 complete sentences", prompt_lower)
        self.assertIn("without trailing off", prompt_lower)

    def test_regression_windows_clrf_prompt_construction(self):
        """Verifies prompt for 'Windows (CLRF)' instructs not inventing commands and identifying CRLF typo."""
        prompt = build_intent_prompt("Windows (CLRF)", "-explain")
        self.assertIn('"Windows (CLRF)"', prompt)
        prompt_lower = prompt.lower()
        self.assertIn("never invent command execution results", prompt_lower)
        self.assertIn("clrf", prompt_lower)
        self.assertIn("crlf", prompt_lower)

    def test_regression_panadas_code_prompt_construction(self):
        """Verifies prompt for 'import panadas as pd' instructs identifying misspelled modules and corrections."""
        prompt = build_intent_prompt("import panadas as pd", "-code")
        self.assertIn('"import panadas as pd"', prompt)
        prompt_lower = prompt.lower()
        self.assertIn("misspelled module names", prompt_lower)
        self.assertIn("panadas", prompt_lower)
        self.assertIn("pandas", prompt_lower)
        self.assertIn("obvious correction", prompt_lower)
        self.assertIn("do not claim it was executed", prompt_lower)
        self.assertIn("never invent command execution results", prompt_lower)

    def test_regression_deterministic_clean_truncated_sentence(self):
        """Verifies deterministic post-processing cleans trailing incomplete sentence fragments."""
        cases = [
            # Trailing fragment cut off mid-sentence
            (
                'The word "porcelain" refers to a ceramic material.\n\nThe ambiguity in the text is the',
                'The word "porcelain" refers to a ceramic material.',
            ),
            # Already complete single sentence
            (
                "Humera is an unfamiliar proper noun.",
                "Humera is an unfamiliar proper noun.",
            ),
            # Complete sentence with closing quote
            (
                'The module name is a typo for "pandas." Trailing cut off words',
                'The module name is a typo for "pandas."',
            ),
            # Exclamation and question punctuation
            (
                "Is this a command? No, it is not! Trailing words",
                "Is this a command? No, it is not!",
            ),
            # Code snippet or single expression without terminal punctuation
            (
                "`import pandas as pd`",
                "`import pandas as pd`",
            ),
            # Number with decimal point not mistaken for terminal punctuation
            (
                "Compatible with Python 3.12 releases. Truncated extra",
                "Compatible with Python 3.12 releases.",
            ),
            # Empty / None handling
            (
                "",
                "",
            ),
        ]
        for input_text, expected_output in cases:
            with self.subTest(input_text=input_text[:30]):
                self.assertEqual(clean_truncated_sentence(input_text), expected_output)

    @patch("prototype.main.urllib.request.urlopen")
    def test_regression_generation_token_limit_and_options(self, mock_urlopen):
        """Verifies token limit (num_predict >= 80) and low temperature to prevent mid-sentence cut-offs and hallucinations."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"response": "Accurate complete explanation.", "eval_count": 20}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = request_ai_explanation("Porcelain")
        self.assertTrue(res.success)

        # Inspect the payload sent in urllib Request
        sent_req = mock_urlopen.call_args[0][0]
        import json
        payload = json.loads(sent_req.data.decode("utf-8"))
        options = payload.get("options", {})
        self.assertGreaterEqual(options.get("num_predict", 0), 80, "num_predict must be at least 80 to avoid truncation")
        self.assertLessEqual(options.get("temperature", 1.0), 0.2, "temperature must be <= 0.2 for deterministic reliability")

    @patch("prototype.main.urllib.request.urlopen")
    def test_regression_mocked_end_to_end_all_five_examples(self, mock_urlopen):
        """Verifies end-to-end request handling, truncation cleaning, and response structure for the five examples."""
        for text, expected_intent in self.FIVE_EXAMPLES:
            mock_response = MagicMock()
            mock_response.status = 200
            # Simulate a response that has a complete sentence plus a truncated fragment
            mock_response.read.return_value = (
                b'{"response": "Complete factual sentence. Dangling cut-off fragment", "eval_count": 15}'
            )
            mock_urlopen.return_value.__enter__.return_value = mock_response

            res = request_ai_explanation(text)
            self.assertTrue(res.success)
            self.assertEqual(res.intent, expected_intent)
            self.assertEqual(res.content, "Complete factual sentence.")
            # Verify backward compatible tuple unpacking
            success, content, metrics = res
            self.assertTrue(success)
            self.assertEqual(content, "Complete factual sentence.")
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics["eval_count"], 15)


if __name__ == "__main__":
    unittest.main()

