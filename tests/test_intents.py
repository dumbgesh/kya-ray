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
            "git status --short",
            "> npm install --save-dev typescript",
            "docker run -d -p 8080:80 nginx:alpine",
            "curl -X POST https://api.example.com/data",
            "pip install -r requirements.txt",
            "pytest tests/test_app.py",
            "ls -la /var/log/nginx",
            "cargo build --release",
            "dotnet run --project MyApp",
            "find . -name '*.py'",
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
            "app = FastAPI()",
            "client = MongoClient('localhost')",
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

    def test_infer_create_pickup_line_and_generation_directives(self):
        """Verifies explicit generation directives including 'give me a cute pickup line' map to -create."""
        cases = [
            "give me a cute pickup line",
            "Give me a cute pickup line",
            "give me an idea for a birthday gift",
            "give me three reasons to learn Rust",
            "come up with a catchy title for my blog post",
            "rewrite this email to sound more professional",
            "suggest a name for my open-source project",
            "make a list of 5 healthy snacks for office workers",
            "draft an announcement for our upcoming webinar",
        ]
        for prompt in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(infer_intent(prompt), "-create")

    def test_infer_explain_distinction_from_create(self):
        """Verifies explanatory questions are not hijacked by embedded create words."""
        cases = [
            "Explain what a pickup line is",
            "What is a pickup line?",
            "How do you write a pickup line?",
            "Explain how to draft a business proposal",
            "What are the key elements of a good title?",
            "Why do writers rewrite their drafts?",
            "Define the concept of creative generation",
        ]
        for prompt in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(infer_intent(prompt), "-explain")

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
            "y = mx + b",
            "f(x) = x^2 + 2x + 1",
            "E = mc^2",
            "A = pi * r^2",
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
        code_inst = INTENT_INSTRUCTIONS["-code"].lower()
        self.assertIn("not claim", code_inst)
        self.assertIn("executed", code_inst)
        self.assertIn("syntax error", code_inst)
        self.assertIn("misspelled", code_inst)
        # Must not presume every input has an error
        self.assertIn("do not assume", code_inst)
        self.assertIn("valid", code_inst)
        self.assertIn("without inventing", code_inst)

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
        self.assertIn("misspelled", prompt_lower)
        self.assertIn("panadas", prompt_lower)
        self.assertIn("pandas", prompt_lower)
        self.assertIn("do not claim it was executed", prompt_lower)
        self.assertIn("never invent command execution results", prompt_lower)

    def test_regression_valid_command_git_status_prompt(self):
        """Verifies 'git status --short' prompt does not assume errors and instructs explaining valid syntax."""
        prompt = build_intent_prompt("git status --short", "-code")
        self.assertIn('"git status --short"', prompt)
        prompt_lower = prompt.lower()
        self.assertIn("do not assume", prompt_lower)
        self.assertIn("valid", prompt_lower)
        self.assertIn("without inventing", prompt_lower)

    def test_regression_return_key_intent_and_prompt(self):
        """Verifies 'return key' is categorized and prompted without assuming missing parentheses."""
        intent = infer_intent("return key")
        self.assertEqual(intent, "-code")
        prompt = build_intent_prompt("return key", "-code")
        prompt_lower = prompt.lower()
        self.assertIn("do not assume", prompt_lower)
        self.assertNotIn("missing parentheses", prompt_lower)

    def test_regression_fastapi_valid_syntax(self):
        """Verifies 'app = FastAPI()' is recognized as code without trailing semicolon."""
        self.assertEqual(infer_intent("app = FastAPI()"), "-code")
        prompt = build_intent_prompt("app = FastAPI()", "-code")
        self.assertIn("without inventing", prompt.lower())

    def test_regression_cap_theorem_prompt_accuracy(self):
        """Verifies CAP theorem is prompted under -explain with accurate constraints."""
        self.assertEqual(infer_intent("CAP theorem"), "-explain")
        prompt = build_intent_prompt("CAP theorem", "-explain")
        self.assertIn("accurately", prompt.lower())

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


class TestCodeDiagnosticsAndReliability(unittest.TestCase):
    """
    Verifies deterministic static code diagnostics:
    - AST-based parsing and syntax validation
    - Curated module set with difflib typo suggestions (e.g. panadas -> pandas, numppy -> numpy)
    - Unfamiliar modules without close matches are not falsely flagged
    - Shell commands and math expressions are identified appropriately
    - Static validation is kept separate from LLM generation
    """

    def test_static_code_diagnostics_typo_detection(self):
        try:
            from prototype.main import check_code_diagnostics
        except ImportError:
            self.fail("check_code_diagnostics must be defined in prototype.main")

        # Misspelled pandas
        diag_pandas = check_code_diagnostics("import panadas as pd")
        self.assertTrue(diag_pandas["has_typo"])
        self.assertIn("panadas", [t[0] for t in diag_pandas["typos"]])
        self.assertEqual(diag_pandas["typos"][0][1], "pandas")

        # Misspelled numpy
        diag_numpy = check_code_diagnostics("import numppy as np")
        self.assertTrue(diag_numpy["has_typo"])
        self.assertIn("numppy", [t[0] for t in diag_numpy["typos"]])
        self.assertEqual(diag_numpy["typos"][0][1], "numpy")

    def test_static_code_diagnostics_valid_code_not_flagged(self):
        try:
            from prototype.main import check_code_diagnostics
        except ImportError:
            self.fail("check_code_diagnostics must be defined in prototype.main")

        valid_cases = [
            "import pandas as pd",
            "import numpy as np",
            "from pathlib import Path",
            "app = FastAPI()",
            "client = MongoClient('localhost')",
            "def calculate_sum(a, b): return a + b",
        ]
        for code in valid_cases:
            with self.subTest(code=code):
                diag = check_code_diagnostics(code)
                self.assertFalse(diag["has_typo"])
                self.assertTrue(diag["is_valid_python"])

    def test_static_code_diagnostics_unfamiliar_import_not_falsely_flagged(self):
        try:
            from prototype.main import check_code_diagnostics
        except ImportError:
            self.fail("check_code_diagnostics must be defined in prototype.main")

        diag = check_code_diagnostics("import my_internal_corp_security_v2")
        self.assertFalse(diag["has_typo"])
        self.assertEqual(len(diag["typos"]), 0)

    def test_static_code_diagnostics_shell_and_math(self):
        try:
            from prototype.main import check_code_diagnostics
        except ImportError:
            self.fail("check_code_diagnostics must be defined in prototype.main")

        diag_shell = check_code_diagnostics("git status --short")
        self.assertFalse(diag_shell["has_typo"])

        diag_math = check_code_diagnostics("y = mx + b")
        self.assertFalse(diag_math["has_typo"])

    def test_strip_surrounding_quotes(self):
        try:
            from prototype.main import strip_surrounding_quotes
        except ImportError:
            self.fail("strip_surrounding_quotes must be defined in prototype.main")

        self.assertEqual(
            strip_surrounding_quotes('"Are you a magician? Because whenever I look at you, everyone else disappears."'),
            "Are you a magician? Because whenever I look at you, everyone else disappears."
        )
        self.assertEqual(strip_surrounding_quotes("'Single quoted text.'"), "Single quoted text.")
        self.assertEqual(strip_surrounding_quotes('`code expression`'), '`code expression`')
        self.assertEqual(strip_surrounding_quotes('He said, "Hello!"'), 'He said, "Hello!"')


class TestCreateIntentRefinement(unittest.TestCase):
    """
    Verifies focused refinement to Kya-Ray's -create intent:
    1. For simple, singular creation requests, defaults to one finished output.
    2. Avoids conversational preambles such as 'I\'d be happy to...' or 'Here is...'.
    3. Respects explicit quantities (e.g. 3 options when requested).
    4. Ensures generated responses end cleanly without trailing fragments.
    5. Preserves normal behavior for -explain, -summarize, and -code.
    """

    def test_detect_create_quantity_singular(self):
        try:
            from prototype.main import detect_create_quantity
        except ImportError:
            self.fail("detect_create_quantity must be defined in prototype.main")

        singular_cases = [
            "give me a cute pickup line",
            "Give me a cute pickup line",
            "write an email to my manager asking for leave",
            "draft a concise announcement for v2.0",
            "suggest a name for my open-source project",
            "compose an apology note to a friend",
            "come up with a catchy title for my blog post",
            "write one slogan for our coffee company",
        ]
        for text in singular_cases:
            with self.subTest(text=text):
                qty, is_multiple = detect_create_quantity(text)
                self.assertEqual(qty, 1)
                self.assertFalse(is_multiple)

    def test_detect_create_quantity_explicit_multiple(self):
        try:
            from prototype.main import detect_create_quantity
        except ImportError:
            self.fail("detect_create_quantity must be defined in prototype.main")

        multi_cases = [
            ("give me three reasons to learn Rust", 3),
            ("give me 3 pickup lines", 3),
            ("make a list of 5 healthy snacks for office workers", 5),
            ("suggest two options for our brand tagline", 2),
            ("give me ten ideas for weekend projects", 10),
        ]
        for text, expected_qty in multi_cases:
            with self.subTest(text=text):
                qty, is_multiple = detect_create_quantity(text)
                self.assertEqual(qty, expected_qty)
                self.assertTrue(is_multiple)

    def test_detect_create_quantity_general_list(self):
        try:
            from prototype.main import detect_create_quantity
        except ImportError:
            self.fail("detect_create_quantity must be defined in prototype.main")

        list_cases = [
            "make a list of key performance metrics",
            "give me a few suggestions for breakfast",
            "suggest several alternatives to SQLite",
            "give me some options for wedding gifts",
        ]
        for text in list_cases:
            with self.subTest(text=text):
                qty, is_multiple = detect_create_quantity(text)
                self.assertTrue(is_multiple)

    def test_strip_conversational_preamble(self):
        try:
            from prototype.main import strip_conversational_preamble
        except ImportError:
            self.fail("strip_conversational_preamble must be defined in prototype.main")

        cases = [
            (
                "I'd be happy to provide a cute pickup line. How about: 'Are you a magician? Everyone else disappears.'",
                "'Are you a magician? Everyone else disappears.'",
            ),
            (
                "Sure! Here is a cute pickup line: Are you a camera? Because I smile whenever I see you.",
                "Are you a camera? Because I smile whenever I see you.",
            ),
            (
                "Certainly! Here's an email draft:\nSubject: Vacation Request",
                "Subject: Vacation Request",
            ),
            (
                "Here is an example of a formal apology:\nDear Professor Smith,",
                "Dear Professor Smith,",
            ),
            (
                "Are you a magician? Everyone else disappears.",
                "Are you a magician? Everyone else disappears.",
            ),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw[:30]):
                self.assertEqual(strip_conversational_preamble(raw), expected)

    def test_extract_single_creation_output(self):
        try:
            from prototype.main import extract_single_creation_output
        except ImportError:
            self.fail("extract_single_creation_output must be defined in prototype.main")

        # Numbered options should extract the first option
        numbered = (
            "1. Are you a magician? Because whenever I look at you, everyone else disappears.\n"
            "2. Do you have a map? Because I just got lost in your eyes.\n"
            "3. Are you a camera? Because every time I look at you, I smile."
        )
        self.assertEqual(
            extract_single_creation_output(numbered),
            "Are you a magician? Because whenever I look at you, everyone else disappears."
        )

        # Multi-paragraph with 'I\'d also suggest' should retain only the first option
        paras = (
            "Are you a magician? Because whenever I look at you, everyone else disappears.\n\n"
            "I'd also suggest: Do you have a map? Because I just got lost in your eyes."
        )
        self.assertEqual(
            extract_single_creation_output(paras),
            "Are you a magician? Because whenever I look at you, everyone else disappears."
        )

    def test_create_prompt_instructions_singular_vs_multiple(self):
        """Verifies prompt construction specifically steers model to 1 output for singular and N for multiple."""
        singular_prompt = build_intent_prompt("give me a cute pickup line", "-create")
        self.assertIn("ONE finished output", singular_prompt)
        self.assertIn("conversational preamble", singular_prompt.lower())

        multi_prompt = build_intent_prompt("give me three reasons to learn Rust", "-create")
        self.assertIn("exactly 3 options", multi_prompt)
        self.assertNotIn("ONE finished output", multi_prompt)

    def test_other_intents_preserved_without_create_constraints(self):
        """Verifies -explain, -summarize, and -code do not receive the single-output constraint."""
        explain_prompt = build_intent_prompt("Explain what a pickup line is", "-explain")
        self.assertNotIn("ONE finished output", explain_prompt)
        self.assertIn("Explain the following selected text accurately", explain_prompt)

        code_prompt = build_intent_prompt("app = FastAPI()", "-code")
        self.assertNotIn("ONE finished output", code_prompt)
        self.assertIn("Explain what the following code", code_prompt)

        summ_prompt = build_intent_prompt("Long paragraph of text to summarize", "-summarize")
        self.assertNotIn("ONE finished output", summ_prompt)
        self.assertIn("Summarize the essential meaning", summ_prompt)

    @patch("prototype.main.urllib.request.urlopen")
    def test_request_ai_create_pickup_line_singular_default(self, mock_urlopen):
        """Verifies singular pickup line request returns one finished line without conversational intro."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = (
            b'{"response": "I\'d be happy to provide a cute pickup line. How about: \\\"Are you a magician? Because whenever I look at you, everyone else disappears.\\\"\\n\\nI\'d also suggest: \\\"Do you have a map?\\\"", "eval_count": 25}'
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = request_ai_explanation("give me a cute pickup line")
        self.assertTrue(res.success)
        self.assertEqual(res.intent, "-create")
        self.assertEqual(
            res.content,
            "Are you a magician? Because whenever I look at you, everyone else disappears."
        )

    @patch("prototype.main.urllib.request.urlopen")
    def test_request_ai_create_explicit_multiple_preserved(self, mock_urlopen):
        """Verifies explicit request for 3 reasons preserves all 3 options without collapsing to one."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = (
            b'{"response": "1. Memory safety without garbage collection.\\n2. Concurrency without data races.\\n3. Predictable high performance.", "eval_count": 30}'
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        res = request_ai_explanation("give me three reasons to learn Rust")
        self.assertTrue(res.success)
        self.assertEqual(res.intent, "-create")
        self.assertIn("1. Memory safety", res.content)
        self.assertIn("2. Concurrency", res.content)
        self.assertIn("3. Predictable high performance", res.content)


if __name__ == "__main__":
    unittest.main()

