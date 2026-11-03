"""
desktop/ai/prompts.py - Prompt formatting, intent-specific instructions, and response cleaning.

Handles intent instructions, code diagnostic integration, create prompt rules,
and terminal punctuation trimming / sentence cleaning.
"""

from desktop.core.intents import (
    analyze_content,
    check_code_diagnostics,
    detect_create_quantity,
)

INTENT_INSTRUCTIONS = {
    "-explain": (
        "Explain the following selected text accurately in simple, beginner-friendly language in 1 to 2 complete sentences. "
        "If the term is ambiguous or unfamiliar, acknowledge uncertainty and avoid inventing origins, people, places, or facts. "
        "Distinguish claims contained in selected text from verified facts; do not automatically endorse unsupported claims. "
        "Never invent command execution results, error messages, or reasons for failure. "
        "If the selection is genuinely ambiguous and alternate interpretations would materially change the outcome, concisely note the distinction. "
        "If the text contains a likely typo (such as 'CLRF' for 'CRLF' line endings), identify the typo and the likely intended term. "
        "Finish cleanly without trailing off or starting an incomplete sentence."
    ),
    "-summarize": (
        "Summarize the essential meaning of the following text in 1 to 2 short, complete sentences. "
        "Capture the key takeaways concisely and finish cleanly without trailing off or starting an incomplete sentence. "
        "Preserve important information, numbers, and constraints; avoid unsupported claims or invented facts."
    ),
    "-code": (
        "Explain what the following code or terminal command actually does in 1 to 2 complete sentences. "
        "Do not assume the input contains an error. If there is a clear, obvious syntax error or misspelled identifier, "
        "identify the typo and state the correction separately. "
        "Do not silently normalize misspelled imports as if they were valid packages. "
        "If the syntax is valid or no obvious error is found, explain the valid behavior without inventing errors or changes. "
        "The input is only provided as text: do not claim it was executed or run, and never invent command execution results, error messages, or reasons for failure. "
        "Finish cleanly without trailing off or starting an incomplete sentence."
    ),
    "-create": (
        "Fulfill the following writing, drafting, or creation request directly and concisely. "
        "Ensure the response satisfies the intended objective while preserving the user's core meaning and constraints. "
        "Treat requests as legitimate without deception. "
        "Generate the requested text directly without conversational preamble, finishing cleanly without trailing off."
    ),
}


CODE_REVIEW_INSTRUCTIONS = (
    "Perform a rigorous code review of the following code for logic defects, execution flow, edge cases, and runtime bugs.\n"
    "Actively inspect for logic defects, edge cases, and runtime bugs:\n"
    "- Control flow and logical errors (not just syntax).\n"
    "- Undefined variables and scope leakage (e.g. referencing a loop variable outside the loop when the iterable might be empty, raising UnboundLocalError/NameError).\n"
    "- Incorrect return values (e.g. returning the last item or arbitrary state when no match is found instead of a safe sentinel like None or raising an error).\n"
    "- Empty inputs and boundary conditions (including empty, missing, invalid, or unexpected inputs, zero division, off-by-one indices).\n"
    "- Unhandled exceptions, missing dictionary keys, mutable default arguments, or incorrect type assumptions.\n\n"
    "Proportionality & Accuracy Requirements:\n"
    "1. Proportional length: Scale the response to the complexity of the snippet. For short snippets or single functions, be concise and direct (typically 1–2 brief paragraphs or bullet points plus the corrected code). Do not write disproportionately long essays.\n"
    "2. Accuracy: Analyse only the code and context provided. Never invent syntax errors, runtime errors, static-analysis warnings, or phantom bugs.\n"
    "3. Distinguish confirmed defects (e.g. ZeroDivisionError on empty collections, UnboundLocalError) from optional style improvements or potential enhancements.\n"
    "4. State each defect clearly and explain why it occurs under specific conditions (including boundary cases like empty collections).\n"
    "5. Provide the corrected code with the exact actionable fix.\n"
    "6. Never claim code was executed unless an execution tool ran it.\n"
    "7. If the code is genuinely defect-free with clean edge-case handling, concisely explain what it does and confirm it handles boundary conditions safely without inventing errors."
)

CODE_EXPLAIN_INSTRUCTIONS = (
    "Explain what the following code or terminal command actually does in simple, clear language in 1 to 2 complete sentences. "
    "Describe its purpose, logic, and expected inputs and outputs without inventing execution results. "
    "Finish cleanly without trailing off."
)


def clean_truncated_sentence(text: str) -> str:
    """
    Ensures answers do not end with an arbitrary unfinished sentence fragment.
    If the response contains complete sentences followed by a trailing fragment
    without terminal punctuation, trims the trailing fragment.
    """
    if not text:
        return text

    stripped = text.strip()
    # Check if the stripped text already ends cleanly with terminal punctuation or code delimiters
    terminal_endings = (".", "!", "?", '."', ".'", '!"', "?'", '!)', '?)', '.)', "```", "`")
    if any(stripped.endswith(end) for end in terminal_endings):
        return stripped

    # Search for the last valid terminal punctuation mark
    last_punct_idx = -1
    for i, char in enumerate(stripped):
        if char in {".", "!", "?"}:
            # Avoid splitting on decimal points in numbers (e.g., 3.14)
            if i > 0 and i < len(stripped) - 1 and stripped[i - 1].isdigit() and stripped[i + 1].isdigit():
                continue
            last_punct_idx = i

    if last_punct_idx != -1:
        # Include any closing quotes, parentheses, brackets immediately following the punctuation
        end_idx = last_punct_idx + 1
        while end_idx < len(stripped) and stripped[end_idx] in ('"', "'", ")", "]", "}"):
            end_idx += 1
        return stripped[:end_idx].strip()

    return stripped


def build_intent_prompt(text: str, intent: str) -> str:
    """Formats the intent-specific instruction prefix, specialized guidance, and user text."""
    prefix = INTENT_INSTRUCTIONS.get(intent, INTENT_INSTRUCTIONS["-explain"])

    extra_guidance = ""
    analysis = analyze_content(text)

    if intent == "-code":
        diag = check_code_diagnostics(text)
        diag_note = f"\n{diag['diagnostics_note']}" if diag.get("diagnostics_note") else ""
        if analysis.specialized_task == "review_code":
            return f"{CODE_REVIEW_INSTRUCTIONS}{diag_note}\n\n\"{text.strip()}\""
        elif analysis.specialized_task == "explain_code":
            return f"{CODE_EXPLAIN_INSTRUCTIONS}{diag_note}\n\n\"{text.strip()}\""
        elif analysis.specialized_task == "diagnose_error":
            extra_guidance = (
                "\nSpecialized Task: Programming error or stack trace detected. "
                "Diagnose the root cause concisely, state what triggered it, and provide the exact actionable fix."
            )
        elif analysis.specialized_task == "explain_terminal":
            extra_guidance = (
                "\nSpecialized Task: Terminal command detected. "
                "Explain the command, flags, and expected operation concisely."
            )
        elif diag_note:
            extra_guidance = diag_note
    elif intent == "-create":
        qty, is_multiple = detect_create_quantity(text)
        if analysis.specialized_task == "rewrite_and_polish":
            extra_guidance = (
                "\nSpecialized Task: Fulfill this rewriting/editing request directly. "
                "Improve tone, grammar, and flow, outputting only the polished draft without conversational preamble."
            )
        elif analysis.specialized_task == "develop_idea":
            extra_guidance = (
                "\nSpecialized Task: Concept or proposed idea development detected. "
                "Develop, flesh out, and structure this into a compelling, actionable outline or draft directly without conversational preamble."
            )
        elif analysis.specialized_task == "continue_writing":
            extra_guidance = (
                "\nSpecialized Task: Continue the narrative or text seamlessly from where it left off, "
                "matching its tone, style, and pacing directly without conversational preamble or meta-commentary."
            )
        elif analysis.specialized_task == "expand_notes":
            extra_guidance = (
                "\nSpecialized Task: Synthesize and develop these rough notes or outline into a clean, "
                "well-structured draft directly without conversational preamble."
            )
        elif not is_multiple and qty == 1:
            extra_guidance = (
                "\nProvide exactly ONE finished output directly without multiple options or alternatives. "
                "Do not include conversational preamble. "
                "Output only the created text, finishing cleanly with terminal punctuation."
            )
        elif is_multiple and qty is not None:
            extra_guidance = (
                f"\nProvide exactly {qty} options directly, respecting the requested quantity. "
                "Do not include conversational preamble. "
                "Output only the requested items directly, finishing cleanly."
            )
        else:
            extra_guidance = (
                "\nProvide the requested content directly and concisely. "
                "Do not include conversational preamble. "
                "Output only the requested items directly, finishing cleanly."
            )
    elif intent == "-summarize":
        if analysis.specialized_task == "summarize_notes":
            extra_guidance = (
                "\nSpecialized Task: Meeting notes, status updates, or progress report detected. "
                "Synthesize and summarize the key progress, decisions, dates, and blockers concisely."
            )
    elif intent == "-explain":
        if analysis.specialized_task == "solve_math":
            extra_guidance = (
                "\nSpecialized Task: Mathematical problem or expression detected. "
                "Solve it step-by-step concisely, showing the formula or core calculation if helpful, "
                "and state the exact final result clearly.\n"
                "Verification standards:\n"
                "- Check calculations and underlying assumptions.\n"
                "- Verify units and state the exact final result clearly.\n"
                "- Show sufficient working without unnecessary verbosity."
            )
        elif analysis.specialized_task == "interpret_data":
            extra_guidance = (
                "\nSpecialized Task: Structured data detected (JSON/YAML/CSV/table). "
                "Interpret what this data represents concisely, explaining key attributes and schema relationships.\n"
                "Verification standards:\n"
                "- Check structure, schema relationships, and possible inconsistencies.\n"
                "- Avoid inventing missing values or extrapolating unstated fields."
            )
        elif analysis.specialized_task == "translate_and_explain":
            extra_guidance = (
                "\nSpecialized Task: Foreign language content detected. "
                "Provide an accurate, natural English translation followed by a brief, helpful note on its meaning or context."
            )
        elif analysis.specialized_task == "explain_concept":
            extra_guidance = (
                "\nSpecialized Task: Technical concept or term detected. "
                "Explain the concept clearly and concisely in simple, beginner-friendly terms."
            )

    return f"{prefix}{extra_guidance}\n\n\"{text.strip()}\""

