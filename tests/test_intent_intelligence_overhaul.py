"""
tests/test_intent_intelligence_overhaul.py - Regression test suite for Intent Intelligence & Response Quality Overhaul.

Verifies:
1. Case A: Meeting notes / status updates correctly classify as -summarize (summarize_notes).
2. Case B: Story continuation correctly classifies as -create (continue_writing).
3. Case C: Code debugging correctly classifies as -code (review_code).
4. Narrative prose containing common English words ('return', 'let', 'catch', 'public') is never classified as code.
5. Leading and trailing action directives receive highest priority regardless of text length.
6. Proportionality and accuracy instructions are properly integrated into code review prompts.
7. Disambiguation between status reporting bullets and actionable drafting todo/idea bullets.
"""

import unittest
from backend.services.groq_client import SYSTEM_REASONING_PROMPT
from desktop.ai.prompts import build_intent_prompt, CODE_REVIEW_INSTRUCTIONS
from desktop.core.intents import (
    analyze_content,
    infer_intent,
    is_meeting_notes_or_status_updates,
    is_narrative_prose,
    CONTENT_TYPE_SOURCE_CODE,
    CONTENT_TYPE_CREATIVE,
    CONTENT_TYPE_LONG_FORM,
    CONTENT_TYPE_NATURAL_LANGUAGE,
)


class TestIntentIntelligenceOverhaul(unittest.TestCase):
    """Verifies generalised intent classification and task understanding."""

    def test_case_a_meeting_notes_status_updates(self):
        """Case A: Project status notes with bullet points must trigger -summarize."""
        notes = (
            "- Backend API development is 80% complete.\n"
            "- Authentication is postponed.\n"
            "- Testing begins Friday.\n"
            "- Deployment target is November 15."
        )
        is_meeting, kind, meta = is_meeting_notes_or_status_updates(notes)
        self.assertTrue(is_meeting)
        self.assertEqual(kind, "meeting_notes")

        analysis = analyze_content(notes)
        self.assertEqual(analysis.suggested_intent, "-summarize")
        self.assertEqual(analysis.content_type, CONTENT_TYPE_LONG_FORM)
        self.assertEqual(analysis.specialized_task, "summarize_notes")
        self.assertEqual(infer_intent(notes), "-summarize")

        prompt = build_intent_prompt(notes, "-summarize")
        self.assertIn("Meeting notes, status updates, or progress report detected", prompt)
        self.assertIn("key progress, decisions, dates, and blockers", prompt)

    def test_case_b_story_continuation_directive(self):
        """Case B: Narrative excerpt with trailing continuation directive must trigger -create."""
        story_input = (
            "The shadows lengthened across the wet pavement as Detective Vance reached for his revolver. "
            "A sudden sound echoed from the dark alleyway behind him.\n"
            "Continue the story"
        )
        analysis = analyze_content(story_input)
        self.assertEqual(analysis.suggested_intent, "-create")
        self.assertEqual(analysis.content_type, CONTENT_TYPE_CREATIVE)
        self.assertEqual(analysis.specialized_task, "continue_writing")
        self.assertEqual(infer_intent(story_input), "-create")

        prompt = build_intent_prompt(story_input, "-create")
        self.assertIn("Continue the narrative or text seamlessly", prompt)
        self.assertIn("matching its tone, style, and pacing", prompt)

    def test_case_b_story_continuation_variants(self):
        """Validates that various continuation expressions at the end are recognized."""
        variants = [
            "What happens next?",
            "Continue writing",
            "\"Continue the narrative\"",
            "Continue this",
            "Take it from here",
            "Write the continuation",
            "Complete the story",
            "Keep going",
        ]
        for v in variants:
            with self.subTest(variant=v):
                text = f"She opened the rusted iron lock and peered inside.\n{v}"
                analysis = analyze_content(text)
                self.assertEqual(analysis.suggested_intent, "-create")
                self.assertEqual(analysis.specialized_task, "continue_writing")

    def test_case_c_code_debugging_and_proportionality(self):
        """Case C: Programming function with boundary defect must trigger -code review."""
        code_input = (
            "def calculate_average(numbers):\n"
            "    total = 0\n\n"
            "    for number in numbers:\n"
            "        total += number\n\n"
            "    return total / len(numbers)\n\n"
            "print(calculate_average([]))"
        )
        analysis = analyze_content(code_input)
        self.assertEqual(analysis.suggested_intent, "-code")
        self.assertEqual(analysis.content_type, CONTENT_TYPE_SOURCE_CODE)
        self.assertEqual(analysis.specialized_task, "review_code")
        self.assertEqual(infer_intent(code_input), "-code")

        prompt = build_intent_prompt(code_input, "-code")
        # Ensure proportionality instructions are present
        self.assertIn("Proportionality & Accuracy Requirements", prompt)
        self.assertIn("Proportional length: Scale the response to the complexity of the snippet", prompt)
        self.assertIn("For short snippets or single functions, be concise and direct", prompt)
        self.assertIn("Analyse only the code and context provided", prompt)
        self.assertIn("Never invent syntax errors, runtime errors, static-analysis warnings", prompt)
        self.assertIn("Distinguish confirmed defects", prompt)

    def test_narrative_prose_with_english_keywords_not_code(self):
        """Narrative prose with words like 'return', 'let', 'catch' must not be classified as code."""
        prose_samples = [
            (
                "She knew there was no return. The cold mist clung to her skin as she stepped through the door. "
                "'Don't let him see you,' she whispered to herself."
            ),
            (
                "Detective Miller arrived at the public library in the dead of night. "
                "He tried to catch his breath as the shadow crossed the window."
            ),
            (
                "Staring into the void, she considered the private letters left on the desk. "
                "There was a constant hum in the room."
            ),
        ]
        for prose in prose_samples:
            with self.subTest(sample=prose[:40]):
                self.assertTrue(is_narrative_prose(prose))
                analysis = analyze_content(prose)
                self.assertNotEqual(analysis.suggested_intent, "-code")
                self.assertNotEqual(analysis.content_type, CONTENT_TYPE_SOURCE_CODE)

    def test_trailing_action_directives_precedence(self):
        """Trailing directives override passive content characteristics."""
        samples = [
            (
                "def calculate_tax(income):\n    return income * 0.2\nWhy is this failing?",
                "-code",
                "review_code",
            ),
            (
                "The quarterly financial results were delivered this morning.\nPlease summarize this",
                "-summarize",
                "summarize_longform",
            ),
            (
                "Hey boss, cannot make it today feeling unwell.\nRewrite this to sound professional",
                "-create",
                "rewrite_and_polish",
            ),
        ]
        for text, expected_intent, expected_task in samples:
            with self.subTest(intent=expected_intent):
                analysis = analyze_content(text)
                self.assertEqual(analysis.suggested_intent, expected_intent)
                self.assertEqual(analysis.specialized_task, expected_task)

    def test_distinguish_status_notes_from_actionable_todos(self):
        """Status notes summarize; actionable todos/drafts create/expand."""
        # Informational status notes -> -summarize
        status_notes = (
            "- Database migration is 100% complete.\n"
            "- Front-end refactoring is on track.\n"
            "- QA testing begins Monday.\n"
            "- Target release is December 1."
        )
        analysis_status = analyze_content(status_notes)
        self.assertEqual(analysis_status.suggested_intent, "-summarize")
        self.assertEqual(analysis_status.specialized_task, "summarize_notes")

        # Actionable task list -> -create (expand_notes)
        action_todos = (
            "TODO:\n"
            "- implement oauth token refresh\n"
            "- add unit tests for billing\n"
            "- ship build to production"
        )
        analysis_todos = analyze_content(action_todos)
        self.assertEqual(analysis_todos.suggested_intent, "-create")
        self.assertEqual(analysis_todos.specialized_task, "expand_notes")

    def test_system_reasoning_prompt_contains_proportionality_and_accuracy(self):
        """Verifies backend system prompt enforces proportionality and non-hallucination."""
        self.assertIn("Proportionality: Scale response length to snippet complexity", SYSTEM_REASONING_PROMPT)
        self.assertIn("Analyse only the provided code without inventing syntax errors", SYSTEM_REASONING_PROMPT)
        self.assertIn("Distinguish confirmed defects", SYSTEM_REASONING_PROMPT)


if __name__ == "__main__":
    unittest.main()

