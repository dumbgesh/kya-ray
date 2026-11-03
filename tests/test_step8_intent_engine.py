"""
tests/test_step8_intent_engine.py - Test suite for Kya-Ray Step 8 Intelligent Context and Intent Engine.

Validates:
1. Content understanding across 10+ content types (code, errors, math, structured data,
   foreign language, rough notes, rewrites, long-form, technical concepts, natural language).
2. Local heuristic intent classification accuracy on representative dataset (clear, ambiguous,
   mixed, math, code/error, short, and long selections).
3. Specialized prompt instruction synthesis for specialized behaviors.
4. Single-pass hybrid reasoning architecture.
"""

import unittest
from desktop.core.intents import (
    CORE_INTENTS,
    CONTENT_TYPE_SOURCE_CODE,
    CONTENT_TYPE_PROGRAMMING_ERROR,
    CONTENT_TYPE_TERMINAL,
    CONTENT_TYPE_MATH,
    CONTENT_TYPE_STRUCTURED_DATA,
    CONTENT_TYPE_FOREIGN_LANGUAGE,
    CONTENT_TYPE_ROUGH_NOTES,
    CONTENT_TYPE_REWRITE,
    CONTENT_TYPE_CREATIVE,
    CONTENT_TYPE_LONG_FORM,
    CONTENT_TYPE_TECHNICAL_CONCEPT,
    CONTENT_TYPE_NATURAL_LANGUAGE,
    analyze_content,
    infer_intent,
    is_math_expression,
    is_structured_data,
    is_foreign_language,
    is_programming_error,
    is_rough_notes_or_rewrite,
)
from desktop.ai.prompts import build_intent_prompt, INTENT_INSTRUCTIONS


class TestStep8ContentUnderstanding(unittest.TestCase):
    """Verifies granular content type detection across varied inputs."""

    def test_detect_math_expressions(self):
        math_samples = [
            "2x + 5 = 15",
            "y = mx + b",
            "f(x) = x^2 - 4x + 3",
            "E = mc^2",
            r"\int_0^\pi \sin(x) dx",
            r"\frac{a + b}{c - d}",
            "calculate 45 * 12 + 100",
            "solve for x: 3x - 9 = 0",
            "(144 / 12) * 5 + 7^2",
            "2^10 + 5!",
        ]
        for expr in math_samples:
            with self.subTest(expr=expr):
                is_math, kind, _ = is_math_expression(expr)
                self.assertTrue(is_math, f"Expected '{expr}' to be detected as math")
                analysis = analyze_content(expr)
                self.assertEqual(analysis.content_type, CONTENT_TYPE_MATH)
                self.assertEqual(analysis.suggested_intent, "-explain")
                self.assertEqual(analysis.specialized_task, "solve_math")

    def test_detect_structured_data(self):
        data_samples = [
            ('{"service": "kya-ray", "status": "active", "port": 8000}', "json"),
            ('[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]', "json"),
            ("server:\n  host: 127.0.0.1\n  port: 8000\n  env: dev", "yaml"),
            ("| Name | Role | Status |\n|---|---|---|\n| Alice | Admin | Active |", "markdown_table"),
            ("id,name,department,salary\n1,Alice,Engineering,120000\n2,Bob,Product,110000", "csv"),
        ]
        for data, expected_kind in data_samples:
            with self.subTest(data=data[:30]):
                is_data, kind, _ = is_structured_data(data)
                self.assertTrue(is_data, f"Expected '{data[:30]}' to be detected as structured data")
                analysis = analyze_content(data)
                self.assertEqual(analysis.content_type, CONTENT_TYPE_STRUCTURED_DATA)
                self.assertEqual(analysis.suggested_intent, "-explain")
                self.assertEqual(analysis.specialized_task, "interpret_data")

    def test_detect_foreign_language(self):
        foreign_samples = [
            ("こんにちは、世界！今日の天気はどうですか？", "Japanese"),
            ("Bonjour tout le monde, comment allez-vous aujourd'hui?", "French"),
            ("¿Cómo estás hoy? Espero que tengas un excelente día.", "Spanish"),
            ("Translate to English: Das Leben ist kein Ponyhof.", "Translation directive"),
            ("Привет мир! Как твои дела?", "Russian"),
            ("مرحبا بالعالم، أتمنى لك يوما سعيدا", "Arabic"),
            ("नमस्ते दुनिया, आप कैसे हैं?", "Hindi"),
        ]
        for text, lang in foreign_samples:
            with self.subTest(text=text[:25], lang=lang):
                is_foreign, _, _ = is_foreign_language(text)
                self.assertTrue(is_foreign, f"Expected '{text[:25]}' to be recognized as foreign/translation")
                analysis = analyze_content(text)
                self.assertEqual(analysis.content_type, CONTENT_TYPE_FOREIGN_LANGUAGE)
                self.assertEqual(analysis.suggested_intent, "-explain")
                self.assertEqual(analysis.specialized_task, "translate_and_explain")

    def test_detect_programming_errors_and_traces(self):
        error_samples = [
            "Traceback (most recent call last):\n  File 'app.py', line 45, in run\nTypeError: 'NoneType' object is not callable",
            "SyntaxError: unexpected EOF while parsing at line 102",
            "fatal: not a git repository (or any of the parent directories): .git",
            "panic: runtime error: index out of range [5] with length 3",
            "npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree",
            "error[E0308]: mismatched types\n  --> src/main.rs:14:18",
            "TS2322: Type 'string' is not assignable to type 'number'.",
            "java.lang.NullPointerException: Cannot invoke 'String.length()' because 'str' is null",
        ]
        for err in error_samples:
            with self.subTest(err=err[:40]):
                is_err, _, _ = is_programming_error(err)
                self.assertTrue(is_err, f"Expected '{err[:40]}' to be detected as programming error")
                analysis = analyze_content(err)
                self.assertEqual(analysis.content_type, CONTENT_TYPE_PROGRAMMING_ERROR)
                self.assertEqual(analysis.suggested_intent, "-code")
                self.assertEqual(analysis.specialized_task, "diagnose_error")

    def test_detect_rough_notes_and_rewrites(self):
        rewrite_samples = [
            "Rewrite this to sound more professional: hey boss cant come in 2day feeling sick",
            "Make this more polite and concise: I need the report right now send it immediately",
            "Fix grammar and polish: The datas was not received proper by the clients.",
        ]
        for item in rewrite_samples:
            with self.subTest(item=item[:30]):
                analysis = analyze_content(item)
                self.assertEqual(analysis.content_type, CONTENT_TYPE_REWRITE)
                self.assertEqual(analysis.suggested_intent, "-create")
                self.assertEqual(analysis.specialized_task, "rewrite_and_polish")

        rough_notes_samples = [
            "- finalize quarterly slide deck\n- ping Sarah regarding AWS spend\n- set up 1-on-1 with design lead",
            "* idea 1: desktop companion with hotkey\n* idea 2: local fallback cache\n* idea 3: markdown rendering",
            "TODO:\n- buy milk\n- call dentist\n- file taxes",
        ]
        for item in rough_notes_samples:
            with self.subTest(item=item[:30]):
                analysis = analyze_content(item)
                self.assertIn(analysis.content_type, (CONTENT_TYPE_ROUGH_NOTES, CONTENT_TYPE_CREATIVE))
                self.assertEqual(analysis.suggested_intent, "-create")
                self.assertEqual(analysis.specialized_task, "expand_notes")


class TestRepresentativeIntentBenchmark(unittest.TestCase):
    """
    Comprehensive benchmark dataset measuring classification accuracy
    across clear, ambiguous, mixed, code, math, and prose selections.
    """

    BENCHMARK_DATASET = [
        # --- Code & Terminal (Target: -code) ---
        ("git checkout -b feature/auth-v2", "-code", "Terminal command"),
        ("docker-compose up -d --build", "-code", "Docker compose command"),
        ("def compute_fibonacci(n):\n    if n <= 1: return n\n    return compute_fibonacci(n-1) + compute_fibonacci(n-2)", "-code", "Python recursion snippet"),
        ("const memoizedValue = useMemo(() => computeExpensiveValue(a, b), [a, b]);", "-code", "React hook snippet"),
        ("SELECT u.id, u.email, COUNT(o.id) FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.id;", "-code", "SQL query"),
        ("app = FastAPI(title='Kya-Ray Backend')", "-code", "Single line code instantiation"),
        ("int total = 0;\nfor (int i = 0; i < 10; i++) {\n    total += i;\n}", "-code", "C/Java loop"),
        ("TypeError: undefined is not an object (evaluating 'response.data.items')", "-code", "JavaScript runtime error"),
        ("bash: /usr/local/bin/deploy: No such file or directory", "-code", "Shell error"),

        # --- Create & Drafting (Target: -create) ---
        ("write an email to client thanking them for renewing their subscription", "-create", "Email draft prompt"),
        ("give me 3 creative tagline ideas for an AI desktop companion", "-create", "Artifact idea generation"),
        ("draft a polite decline message for an unwanted meeting invitation", "-create", "Message drafting"),
        ("compose a haiku about autumn mornings", "-create", "Creative poetry"),
        ("Rewrite this to be more punchy and professional: our product is kinda fast and does good things", "-create", "Writing polish"),
        ("- fix css padding\n- add unit test for auth\n- deploy to staging", "-create", "Rough notes to expand"),

        # --- Summarize & Long-Form (Target: -summarize) ---
        (
            "Artificial intelligence systems are rapidly evolving from narrow, single-task models to generalized agents capable "
            "of reasoning across multiple modalities. Organizations worldwide are re-architecting their engineering stacks to "
            "incorporate retrieval-augmented generation, fine-tuning pipelines, and distributed vector indexes. However, substantial "
            "challenges persist around latency, privacy, and deterministic reliability in production environments.",
            "-summarize",
            "Multi-sentence article paragraph (> 50 words)"
        ),
        (
            "Meeting Notes - Oct 28:\n"
            "Discussed Q4 roadmap deliverables. Key priorities include completing the PySide6 UI refactor by Friday, "
            "integrating the FastAPI backend with GroqCloud, and setting up automated regression tests. "
            "Sarah will oversee the UI components while Alex audits API token usage and latency thresholds.",
            "-summarize",
            "Structured meeting minutes"
        ),
        ("summarize the key differences between monolithic and microservice architectures", "-summarize", "Explicit summary directive"),
        ("tl;dr on the latest European Union AI Act regulations", "-summarize", "TLDR directive"),

        # --- Explain & Conceptual (Target: -explain) ---
        ("OAuth 2.0 Authorization Code flow with PKCE", "-explain", "Technical concept term"),
        ("What is the CAP theorem in distributed databases?", "-explain", "Explanatory question"),
        ("Why does Python use a Global Interpreter Lock (GIL)?", "-explain", "Technical question"),
        ("Idempotency in REST APIs", "-explain", "Technical architecture concept"),
        ("2x + 10 = 50", "-explain", "Algebraic math equation"),
        (r"\int_0^1 x^2 dx", "-explain", "Definite integral math problem"),
        ('{"host": "localhost", "port": 5432, "database": "users"}', "-explain", "JSON configuration data"),
        ("Bonjour! Comment puis-je vous aider aujourd'hui?", "-explain", "Foreign language greeting"),
        ("B-tree indexing", "-explain", "Short technical term"),
        ("Ephemeral tokens", "-explain", "Short technical phrase"),
    ]

    def test_benchmark_dataset_classification_accuracy(self):
        """Measures classification accuracy across all benchmark categories."""
        total = len(self.BENCHMARK_DATASET)
        correct = 0
        failures = []

        for sample, expected_intent, label in self.BENCHMARK_DATASET:
            inferred = infer_intent(sample)
            if inferred == expected_intent:
                correct += 1
            else:
                failures.append((label, sample[:40], expected_intent, inferred))

        accuracy = (correct / total) * 100.0
        self.assertGreaterEqual(
            accuracy, 95.0,
            f"Classification accuracy was {accuracy:.1f}% ({correct}/{total}). Failures: {failures}"
        )
        self.assertEqual(len(failures), 0, f"Unexpected misclassifications: {failures}")

    def test_ambiguous_cases_handling(self):
        """Verifies graceful handling of subtle and borderline inputs."""
        # 1. Pure math formula vs code assignment: y = mx + b must NOT be code
        self.assertEqual(infer_intent("y = mx + b"), "-explain")
        self.assertEqual(infer_intent("f(x) = x^2 - 4x + 3"), "-explain")

        # 2. Explanatory question containing code word: "explain what a function is"
        self.assertEqual(infer_intent("explain what a function is in programming"), "-explain")

        # 3. Explanatory question containing creation word: "explain how to create an index in postgres"
        self.assertEqual(infer_intent("explain how to create an index in postgres"), "-explain")

        # 4. English prose with words starting with type prefixes (e.g. 'international', 'integral')
        self.assertEqual(infer_intent("International trade agreements have shaped global logistics for decades."), "-explain")

        # 5. Single technical acronyms
        self.assertEqual(infer_intent("ACID"), "-explain")
        self.assertEqual(infer_intent("JWT"), "-explain")


class TestPromptQualityAndSpecializedGuidance(unittest.TestCase):
    """Verifies that generated prompts inject specialized guidance based on content type."""

    def test_math_prompt_specialized_guidance(self):
        prompt = build_intent_prompt("2x + 15 = 45", "-explain")
        self.assertIn("Mathematical problem or expression detected", prompt)
        self.assertIn("Solve it step-by-step", prompt)
        self.assertIn('"2x + 15 = 45"', prompt)

    def test_error_prompt_specialized_guidance(self):
        err = "TypeError: 'NoneType' object is not subscriptable"
        prompt = build_intent_prompt(err, "-code")
        self.assertIn("Programming error or stack trace detected", prompt)
        self.assertIn("Diagnose the root cause", prompt)
        self.assertIn("provide the exact actionable fix", prompt)

    def test_structured_data_prompt_specialized_guidance(self):
        data = '{"name": "Alice", "role": "admin", "permissions": ["read", "write"]}'
        prompt = build_intent_prompt(data, "-explain")
        self.assertIn("Structured data detected", prompt)
        self.assertIn("Interpret what this data represents concisely", prompt)

    def test_foreign_language_prompt_specialized_guidance(self):
        foreign = "Bonjour le monde, c'est une belle journée."
        prompt = build_intent_prompt(foreign, "-explain")
        self.assertIn("Foreign language content detected", prompt)
        self.assertIn("Provide an accurate, natural English translation", prompt)

    def test_rewrite_prompt_specialized_guidance(self):
        rewrite = "Rewrite this to sound more professional: hey boss cant make it today"
        prompt = build_intent_prompt(rewrite, "-create")
        self.assertIn("Specialized Task: Fulfill this rewriting/editing request directly", prompt)
        self.assertIn("Improve tone, grammar, and flow", prompt)

    def test_rough_notes_prompt_specialized_guidance(self):
        notes = "- draft marketing email\n- review pull request\n- sync with design team"
        prompt = build_intent_prompt(notes, "-create")
        self.assertIn("Synthesize and develop these rough notes or outline into a clean", prompt)


class TestStep81PriorityRefinements(unittest.TestCase):
    """
    Step 8.1 Regression Tests:
    Verifies that the 5-tier classification priority prevents long text from
    inadvertently hijacking mathematical word problems or idea development into Summarize.
    """

    def test_business_break_even_word_problem_priority(self):
        """
        Real-world failure #1: A 61-word business break-even problem asking to calculate
        values must be classified as Explain / solve_math, NOT Summarize.
        """
        break_even_sample = (
            "A boutique coffee roastery has fixed monthly operating costs of $12,000, "
            "which includes rent, equipment leasing, and administrative salaries. "
            "Each bag of specialty coffee costs $6.50 in direct materials and labor to produce, "
            "and sells at a retail price of $22.50. Calculate the break-even volume in units per month "
            "and determine the net profit if the roastery sells 1,200 bags."
        )
        analysis = analyze_content(break_even_sample)
        self.assertEqual(analysis.suggested_intent, "-explain")
        self.assertEqual(analysis.specialized_task, "solve_math")
        self.assertEqual(infer_intent(break_even_sample), "-explain")

        # Verify prompt instructions
        prompt = build_intent_prompt(break_even_sample, "-explain")
        self.assertIn("Mathematical problem or expression detected", prompt)
        self.assertIn("Solve it step-by-step", prompt)

    def test_college_application_idea_development_priority(self):
        """
        Real-world failure #2: A 56-word college application common app idea asking to develop
        an outline must be classified as Create / develop_idea, NOT Summarize.
        """
        college_app_sample = (
            "Idea for my college application common app essay: Focus on my experience "
            "repairing vintage mechanical typewriters in my grandfather's workshop during high school, "
            "and connect the precision, patience, and tactile problem-solving required to my ambition "
            "to study mechanical engineering and robotics. Develop this into a compelling structure and outline for my application essay."
        )
        analysis = analyze_content(college_app_sample)
        self.assertEqual(analysis.suggested_intent, "-create")
        self.assertEqual(analysis.specialized_task, "develop_idea")
        self.assertEqual(infer_intent(college_app_sample), "-create")

        # Verify prompt instructions
        prompt = build_intent_prompt(college_app_sample, "-create")
        self.assertIn("Concept or proposed idea development detected", prompt)
        self.assertIn("Develop, flesh out, and structure this", prompt)

    def test_negative_explicitly_asking_to_summarize_business_idea(self):
        """
        Negative test 1: Explicitly asking to summarise a business idea must trigger
        Summarize, not Create or Explain.
        """
        summarize_idea_sample = (
            "Summarize this business concept in two bullet points: A subscription service delivering "
            "locally roasted coffee beans on a bi-weekly cadence to remote workers across metropolitan areas, "
            "featuring customizable roast profiles, carbon-neutral shipping, and automated inventory prediction."
        )
        analysis = analyze_content(summarize_idea_sample)
        self.assertEqual(analysis.suggested_intent, "-summarize")
        self.assertEqual(analysis.specialized_task, "summarize_longform")
        self.assertEqual(infer_intent(summarize_idea_sample), "-summarize")

    def test_negative_explicitly_asking_to_explain_math_concept(self):
        """
        Negative test 2: Explicitly asking to explain a mathematical concept must trigger
        Explain / explain_concept, and NOT automatically solve or hallucinate calculations.
        """
        explain_concept_sample = (
            "Explain the mathematical concept of break-even analysis and how fixed costs relate to contribution margin."
        )
        analysis = analyze_content(explain_concept_sample)
        self.assertEqual(analysis.suggested_intent, "-explain")
        self.assertNotEqual(analysis.specialized_task, "solve_math")
        self.assertEqual(analysis.specialized_task, "explain_concept")
        self.assertEqual(infer_intent(explain_concept_sample), "-explain")


class TestStep82CodeReviewAndEdgeCaseDetection(unittest.TestCase):
    """
    Step 8.2 Regression and Edge-Case Detection Suite.
    Validates:
    1. Exact get_user bug regression (UnboundLocalError on empty list + incorrect return of last item).
    2. Distinction between explaining code and reviewing code for defects.
    3. Inspection instructions for undefined variables, incorrect return values, empty inputs,
       boundary conditions, unhandled exceptions, and incorrect assumptions.
    4. Actionable fix enforcement in prompts.
    5. Similar edge-case code samples (ZeroDivisionError on empty collection, mutable default arguments,
       unhandled dictionary keys, IndexError in loop boundaries).
    """

    def setUp(self):
        self.get_user_code = (
            "def get_user(users, user_id):\n"
            "    for user in users:\n"
            "        if user[\"id\"] == user_id:\n"
            "            return user\n\n"
            "    return user"
        )

    def test_exact_get_user_bug_classification_and_prompt(self):
        """
        Validates that the exact failed get_user snippet triggers -code with
        specialized_task='review_code' and comprehensive defect inspection instructions.
        """
        analysis = analyze_content(self.get_user_code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        self.assertEqual(infer_intent(self.get_user_code), "-code")

        prompt = build_intent_prompt(self.get_user_code, "-code")
        # 1. Undefined variables / scope leakage
        self.assertIn("Undefined variables and scope leakage", prompt)
        self.assertIn("UnboundLocalError", prompt)
        # 2. Incorrect return values
        self.assertIn("Incorrect return values", prompt)
        self.assertIn("safe sentinel like None", prompt)
        # 3. Empty inputs & boundary conditions
        self.assertIn("Empty inputs and boundary conditions", prompt)
        # 4. Actionable fix requirement
        self.assertIn("Provide the corrected code with the exact actionable fix", prompt)

    def test_distinguish_explaining_code_vs_reviewing_code(self):
        """
        Validates that Kya-Ray distinguishes between explicit requests to explain code
        and automatic or explicit review for code defects.
        """
        # Explaining code request
        explain_code_request = (
            f"Explain what this function does:\n{self.get_user_code}"
        )
        analysis_explain = analyze_content(explain_code_request)
        self.assertEqual(analysis_explain.suggested_intent, "-code")
        self.assertEqual(analysis_explain.specialized_task, "explain_code")
        prompt_explain = build_intent_prompt(explain_code_request, "-code")
        self.assertIn("Explain what the following code or terminal command actually does", prompt_explain)
        self.assertNotIn("Actively inspect for", prompt_explain)

        # Code review request (explicit directive)
        review_request = f"Review this code for bugs:\n{self.get_user_code}"
        analysis_review = analyze_content(review_request)
        self.assertEqual(analysis_review.suggested_intent, "-code")
        self.assertEqual(analysis_review.specialized_task, "review_code")
        prompt_review = build_intent_prompt(review_request, "-code")
        self.assertIn("Perform a rigorous code review of the following code for logic defects", prompt_review)

        # Code review request (raw source selection)
        raw_selection_analysis = analyze_content(self.get_user_code)
        self.assertEqual(raw_selection_analysis.specialized_task, "review_code")

    def test_edge_case_empty_collection_zero_division(self):
        """
        Validates review instructions for code vulnerable to ZeroDivisionError on empty inputs.
        """
        code = (
            "def calculate_average(scores):\n"
            "    total = sum(scores)\n"
            "    return total / len(scores)"
        )
        analysis = analyze_content(code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(code, "-code")
        self.assertIn("zero division", prompt)
        self.assertIn("Empty inputs and boundary conditions", prompt)

    def test_edge_case_mutable_default_argument(self):
        """
        Validates review instructions for code with mutable default arguments.
        """
        code = (
            "def add_item(item, items=[]):\n"
            "    items.append(item)\n"
            "    return items"
        )
        analysis = analyze_content(code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(code, "-code")
        self.assertIn("mutable default arguments", prompt)

    def test_edge_case_missing_dictionary_key_and_assumptions(self):
        """
        Validates review instructions for code assuming dictionary keys always exist.
        """
        code = (
            "def get_discounted_price(product):\n"
            "    return product[\"price\"] * (1 - product[\"discount\"])"
        )
        analysis = analyze_content(code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(code, "-code")
        self.assertIn("missing dictionary keys", prompt)

    def test_edge_case_loop_index_out_of_bounds(self):
        """
        Validates review instructions for code with off-by-one loop indexing.
        """
        code = (
            "def get_adjacent_pairs(items):\n"
            "    pairs = []\n"
            "    for i in range(len(items)):\n"
            "        pairs.append((items[i], items[i + 1]))\n"
            "    return pairs"
        )
        analysis = analyze_content(code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(code, "-code")
        self.assertIn("off-by-one", prompt)


if __name__ == "__main__":
    unittest.main()

