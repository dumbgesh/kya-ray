"""
tests/test_step9_generalised_reasoning.py - Evaluation suite for Step 9 Generalised Reasoning & Verification.

Evaluates:
1. Development Set:
   - Multi-language programming defects (JS unawaited promise, Go missing defer close, Python file leak, SQL injection).
   - Unfamiliar mathematical word problems (combinatorics/probability, rate & volume geometry).
   - Business & product idea development.
   - Explanatory technical concepts vs code creation.
2. Held-Out Evaluation Set (Unseen inputs to prevent overfitting):
   - Unseen language constructs (Rust string slicing, TypeScript interface constraints).
   - Unseen logic boundary defects (Binary search high boundary IndexError).
   - Unseen quantitative financial math (Compound interest with monthly compounding).
   - Empty, malformed, and ambiguous inputs with adaptive uncertainty.
3. Verification Standards:
   - Code verification (flow, logic bugs, boundary conditions, actionable fixes, no false execution claims).
   - Math verification (calculations, units, final results, sufficient working).
   - Data verification (schema relationships, no invented values).
   - Creative & Rewriting verification (objective fulfillment, original meaning preserved).
   - System Reasoning Prompt verification across backend messaging.
"""

import unittest
from backend.services.groq_client import GroqProvider, SYSTEM_REASONING_PROMPT
from desktop.ai.prompts import build_intent_prompt, INTENT_INSTRUCTIONS
from desktop.core.intents import (
    analyze_content,
    infer_intent,
    CONTENT_TYPE_SOURCE_CODE,
    CONTENT_TYPE_MATH,
    CONTENT_TYPE_IDEA,
    CONTENT_TYPE_TECHNICAL_CONCEPT,
    CONTENT_TYPE_NATURAL_LANGUAGE,
)


class TestStep9DevelopmentEvaluation(unittest.TestCase):
    """Development evaluation set across multi-language code, math, and product ideas."""

    def test_javascript_async_defect_detection(self):
        """
        JavaScript async function missing await on state persistence call.
        Should trigger -code with review_code specialized task.
        """
        js_code = (
            "async function updateUserBalance(userId, amount) {\n"
            "    const user = await getUser(userId);\n"
            "    user.balance += amount;\n"
            "    saveUser(user);\n"
            "    return user.balance;\n"
            "}"
        )
        analysis = analyze_content(js_code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(js_code, "-code")
        self.assertIn("Actively inspect for logic defects", prompt)
        self.assertIn("Control flow and logical errors", prompt)
        self.assertIn("Provide the corrected code with the exact actionable fix", prompt)

    def test_go_resource_leak_detection(self):
        """
        Go function failing to close opened file handle (missing defer f.Close()).
        Should trigger -code with review_code specialized task.
        """
        go_code = (
            "func processFile(filename string) (int, error) {\n"
            "    f, err := os.Open(filename)\n"
            "    if err != nil {\n"
            "        return 0, err\n"
            "    }\n"
            "    data, err := io.ReadAll(f)\n"
            "    return len(data), err\n"
            "}"
        )
        analysis = analyze_content(go_code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(go_code, "-code")
        self.assertIn("resource leaks", SYSTEM_REASONING_PROMPT)
        self.assertIn("Actively inspect for logic defects", prompt)

    def test_sql_injection_vulnerability_detection(self):
        """
        Unsafe SQL string formatting.
        Should trigger -code with review_code.
        """
        sql_query = "SELECT * FROM users WHERE email = '\" + user_email + \"' AND status = 'active';"
        analysis = analyze_content(sql_query)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")

    def test_unfamiliar_probability_word_problem(self):
        """
        Combinatorics / probability calculation without replacement.
        Should trigger -explain with solve_math.
        """
        math_problem = (
            "A bag contains 5 red, 7 green, and 8 blue marbles. If two marbles are drawn "
            "at random without replacement, calculate the probability that both are blue, "
            "and determine the probability of drawing at least one green marble."
        )
        analysis = analyze_content(math_problem)
        self.assertEqual(analysis.suggested_intent, "-explain")
        self.assertEqual(analysis.specialized_task, "solve_math")
        prompt = build_intent_prompt(math_problem, "-explain")
        self.assertIn("Mathematical problem or expression detected", prompt)
        self.assertIn("Verification standards", prompt)
        self.assertIn("Check calculations and underlying assumptions", prompt)
        self.assertIn("Verify units and state the exact final result clearly", prompt)

    def test_geometry_rate_word_problem(self):
        """
        Cylindrical tank volume and fill time calculation.
        Should trigger -explain with solve_math.
        """
        geom_problem = (
            "A cylindrical water tank has a radius of 3.5 meters and a height of 10 meters. "
            "Determine its total volume in cubic meters and calculate the time in minutes "
            "required to fill it completely if water is pumped at a rate of 250 liters per minute."
        )
        analysis = analyze_content(geom_problem)
        self.assertEqual(analysis.suggested_intent, "-explain")
        self.assertEqual(analysis.specialized_task, "solve_math")

    def test_product_concept_development(self):
        """
        Edge AI drone startup concept.
        Should trigger -create with develop_idea.
        """
        startup_idea = (
            "Product concept: Autonomous edge-AI drone inspecting offshore wind turbine blades "
            "using thermal computer vision, reporting micro-cracks directly to maintenance teams "
            "over satellite uplink. Develop a comprehensive value proposition, technical architecture, "
            "and go-to-market strategy."
        )
        analysis = analyze_content(startup_idea)
        self.assertEqual(analysis.suggested_intent, "-create")
        self.assertEqual(analysis.specialized_task, "develop_idea")
        prompt = build_intent_prompt(startup_idea, "-create")
        self.assertIn("Concept or proposed idea development detected", prompt)
        self.assertIn("Develop, flesh out, and structure this", prompt)


class TestStep9HeldOutEvaluation(unittest.TestCase):
    """Held-out evaluation set containing novel, unseen samples across domains."""

    def test_held_out_binary_search_boundary_defect(self):
        """
        Unseen boundary condition defect in binary search:
        'high = len(arr)' causes IndexError on mid access when target >= last element.
        """
        code = (
            "def binary_search(arr, target):\n"
            "    low = 0\n"
            "    high = len(arr)\n"
            "    while low <= high:\n"
            "        mid = (low + high) // 2\n"
            "        if arr[mid] == target:\n"
            "            return mid\n"
            "        elif arr[mid] < target:\n"
            "            low = mid + 1\n"
            "        else:\n"
            "            high = mid - 1\n"
            "    return -1"
        )
        analysis = analyze_content(code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")
        prompt = build_intent_prompt(code, "-code")
        self.assertIn("Empty inputs and boundary conditions", prompt)
        self.assertIn("off-by-one", prompt)

    def test_held_out_rust_defect_free_function(self):
        """
        Rust string slicing function.
        Should trigger -code with review_code, verifying defect-free behavior safely.
        """
        rust_code = (
            "pub fn first_word(s: &str) -> &str {\n"
            "    let bytes = s.as_bytes();\n"
            "    for (i, &item) in bytes.iter().enumerate() {\n"
            "        if item == b' ' {\n"
            "            return &s[0..i];\n"
            "        }\n"
            "    }\n"
            "    &s[..]\n"
            "}"
        )
        analysis = analyze_content(rust_code)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.specialized_task, "review_code")

    def test_held_out_compound_interest_financial_math(self):
        """
        Compound interest financial math problem.
        Should trigger -explain with solve_math.
        """
        finance_problem = (
            "An investor deposits $25,000 into a high-yield certificate of deposit earning "
            "an annual interest rate of 4.8% compounded monthly. Calculate the balance after 5 years "
            "and determine the total interest earned."
        )
        analysis = analyze_content(finance_problem)
        self.assertEqual(analysis.suggested_intent, "-explain")
        self.assertEqual(analysis.specialized_task, "solve_math")
        prompt = build_intent_prompt(finance_problem, "-explain")
        self.assertIn("Check calculations and underlying assumptions", prompt)

    def test_held_out_empty_and_whitespace_input(self):
        """
        Graceful handling of empty/whitespace input:
        Must default safely to -explain without raising unhandled exceptions.
        """
        analysis_empty = analyze_content("")
        self.assertEqual(analysis_empty.suggested_intent, "-explain")
        self.assertEqual(analysis_empty.specialized_task, "explain_general")

        analysis_spaces = analyze_content("   \n\t  ")
        self.assertEqual(analysis_spaces.suggested_intent, "-explain")

    def test_held_out_ambiguous_entity_with_adaptive_uncertainty(self):
        """
        Ambiguous single-entity selection ('Mercury').
        Should trigger -explain with explain_concept / explain_general, and prompt instructions
        must guide adaptive uncertainty rather than hallucinating singular certainty.
        """
        analysis = analyze_content("Mercury")
        self.assertEqual(analysis.suggested_intent, "-explain")
        prompt = build_intent_prompt("Mercury", "-explain")
        self.assertIn("acknowledge uncertainty", prompt)
        self.assertIn("alternate interpretations would materially change the outcome", prompt)

    def test_held_out_explain_vs_create_distinction(self):
        """
        Query containing creative words but asking for an explanation of a concept:
        'Explain how to design a distributed cache without creating bottlenecks.'
        Must trigger -explain, NOT -create.
        """
        query = "Explain how to design a distributed cache without creating bottlenecks."
        analysis = analyze_content(query)
        self.assertEqual(analysis.suggested_intent, "-explain")
        self.assertNotEqual(analysis.suggested_intent, "-create")


class TestStep9VerificationStandards(unittest.TestCase):
    """Verifies that task-specific verification guidelines are present in prompts and provider."""

    def test_system_reasoning_prompt_verification_standards(self):
        """Validates that GroqProvider incorporates all 5 task verification standards in the system prompt."""
        provider = GroqProvider(api_key="mock_key", model="qwen/qwen3.8-27b")
        messages = provider._build_messages("test input", "-explain")
        system_content = messages[0]["content"]

        # 1. Deep comprehension & objective inference
        self.assertIn("Deep Comprehension", system_content)
        self.assertIn("Objective Inference", system_content)
        # 2. Consequence & assumption reasoning
        self.assertIn("Consequence & Assumption Reasoning", system_content)
        # 3. Adaptive uncertainty
        self.assertIn("Adaptive Uncertainty", system_content)
        # 4. Task Verification Standards (Code, Math, Data, Creative, Explanation/Summary)
        self.assertIn("Code: Inspect execution flow and control paths", system_content)
        self.assertIn("Mathematics: Verify step-by-step arithmetic", system_content)
        self.assertIn("Data: Verify schema structures", system_content)
        self.assertIn("Creation & Rewriting: Fulfill the user's intended objective", system_content)
        self.assertIn("Explanation & Summary: Distinguish claims from verified facts", system_content)

    def test_code_verification_prompt_prohibits_false_execution_claim(self):
        """Validates that code review prompt instructs model never to claim execution took place."""
        prompt = build_intent_prompt("def foo(): return 42", "-code")
        self.assertIn("Never claim code was executed unless an execution tool ran it", prompt)

    def test_creative_verification_preserves_user_meaning(self):
        """Validates that creative prompt instructs model to preserve user's intended meaning."""
        self.assertIn(
            "Ensure the response satisfies the intended objective while preserving the user's core meaning and constraints",
            INTENT_INSTRUCTIONS["-create"],
        )

    def test_summarization_verification_preserves_numbers_and_avoids_unsupported_claims(self):
        """Validates that summarization prompt preserves critical metrics and forbids unsupported claims."""
        self.assertIn(
            "Preserve important information, numbers, and constraints; avoid unsupported claims or invented facts",
            INTENT_INSTRUCTIONS["-summarize"],
        )


if __name__ == "__main__":
    unittest.main()

