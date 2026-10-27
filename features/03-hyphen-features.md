# Feature 03: Hyphen Features (Context-Based Intent System)

## Status
`Planned`

---

## Purpose
The Hyphen Features system defines Kya-Ray's context-aware intent taxonomy. Rather than requiring users to manually select operational modes (such as "Code Mode", "Explain Mode", or "Summarize Mode"), Kya-Ray is designed to infer the user's intended task directly from the highlighted content and available contextual cues.

> [!IMPORTANT]
> **Internal Intent Identifiers**: Labels such as `-explain`, `-summarize`, and `-code` are internal system tags used by classification prompts and orchestration modules. **They are not commands that users are required to type or remember.** Furthermore, intent identifiers must be completely decoupled from user-facing response text (the user should never see `-explain:` prefixed to their answer).

---

## Intent Classification Principles

1. **Context-Driven Inference**: The system should determine the right intent automatically from the structure, syntax, and semantics of the selection.
2. **Short Text Caution**: Short text alone must not trigger high-confidence assumption. A single ambiguous word or fragment (e.g., "yield", "closure", "lambda") could be a programming keyword, a financial concept, or an everyday vocabulary word. In such cases, the system must provide a cautious, well-grounded explanation or ask a brief clarification.
3. **No Fact Invention**: When surrounding context is insufficient, the model must **never invent facts or assumptions** to fill the gaps.
4. **Safe Fallbacks on Low Confidence**: When classification confidence is low, the system should choose a safe, neutral response (typically a concise explanation) or present a concise choice of follow-ups.
5. **Context Sensitivity in Code**: A code snippet may need explanation, debugging, review, or refactoring depending on whether it contains syntax errors, stack traces, unfinished boilerplate, or benchmark logic.

---

## The Eight Core Intents

The initial version of Kya-Ray focuses on eight fundamental intents:

```
                  ┌───────────────┐
                  │ Captured Text │
                  └───────┬───────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
    [Reading & Analysis]        [Action & Generation]
     • -explain                  • -code
     • -summarize                • -create
     • -compare                  • -complete
                                 • -suggest
                                 • -rewrite
```

---

### 1. `-explain`
* **Purpose**: Demystify unfamiliar words, specialized jargon, formulas, or complex concepts in simple, accessible terms.
* **When Selected**: The selection contains a difficult word, technical term, legal phrase, idiom, or brief conceptual paragraph.
* **Expected Input**: 1 to 50 words representing an unfamiliar concept, term, or concise snippet.
* **Expected Output**: A 2 to 3 sentence explanation written in beginner-friendly, plain language.
* **Example**:
  * *Input*: `"Orthogonal persistence"`
  * *Output*: `"Orthogonal persistence means that data in a computer program is saved automatically without the programmer having to write special code to load or store it. Whether an object stays saved is completely independent of the object's type or how it was created."*
* **Ambiguities / Edge Cases**: Polysemous words (words with multiple meanings like "thread", "pipeline", "yield"). The model must either ground the definition in visible cues or mention the two primary interpretations briefly.

---

### 2. `-summarize`
* **Purpose**: Condense long passages, articles, emails, or logs down to their essential points without losing critical meaning.
* **When Selected**: The selection is substantial in length (typically 150+ words, multi-paragraph, or long bulleted text).
* **Expected Input**: Medium-to-long text block (articles, documentation pages, meeting notes).
* **Expected Output**: A bulleted or brief paragraph summary highlighting key decisions, takeaways, or actions.
* **Example**:
  * *Input*: A 500-word software changelog describing version updates.
  * *Output*: A 3-bullet summary highlighting the breaking changes, bug fixes, and upgrade instructions.
* **Ambiguities / Edge Cases**: Text that is already extremely concise; summarizing dense code without explaining its functionality.

---

### 3. `-compare`
* **Purpose**: Objectively analyze two or more contrasting concepts, frameworks, options, or data sets, highlighting key trade-offs.
* **When Selected**: The selection mentions multiple alternatives (e.g., "PostgreSQL vs MongoDB", "REST vs GraphQL", "Option A vs Option B"), or lists conflicting approaches.
* **Expected Input**: Phrases, lists, or paragraphs referencing at least two distinct subjects.
* **Expected Output**: A clear breakdown of core differences, pros/cons, and recommended situational choices.
* **Example**:
  * *Input*: `"TCP vs UDP"`
  * *Output*: `"TCP is connection-oriented and guarantees reliable, in-order packet delivery, making it ideal for web browsing and file transfers. UDP is connectionless and prioritizes minimal latency over reliability, making it better suited for live streaming and gaming."*
* **Ambiguities / Edge Cases**: Comparing entities that share names with unrelated subjects; text that appears to be a list but is not an explicit comparison.

---

### 4. `-code`
* **Purpose**: Assist the user with programming logic, syntax, debugging, and code comprehension.
* **When Selected**: The selection contains syntactically structured code, terminal outputs, stack traces, or pseudo-code.
* **Sub-Intents**:
  * `-code:explain`: Explains what an unfamiliar function, regex, or algorithm does.
  * `-code:debug`: Analyzes an error message, stack trace, or buggy function and identifies the fix.
  * `-code:refactor`: Improves readability, efficiency, or typing of valid code.
* **Expected Input**: 1 to 100 lines of source code, configuration files, SQL queries, or stack traces.
* **Expected Output**: Concise analysis followed by a clean, corrected code block if applicable.
* **Example**:
  * *Input*: `IndexError: list index out of range at line 42 in worker.py`
  * *Output*: `"This error occurs because the list has fewer elements than the index being accessed. Verify that the list is non-empty before indexing, or use `list.get()` or a bounds check."*
* **Ambiguities / Edge Cases**: Natural language mixed with code (markdown documentation); pseudocode; identifying whether the user wants an explanation or a refactored fix.

---

### 5. `-create`
* **Purpose**: Generate a new tangible artifact (e.g., an email draft, a docstring, a unit test, a markdown table) derived from the selected context.
* **When Selected**: The input contains an explicit request, specification notes, or raw bullet points meant to be transformed into a finished work product.
* **Expected Input**: Outline points, requirements, bug reports, or rough notes.
* **Expected Output**: A formatted, ready-to-use artifact.
* **Example**:
  * *Input*: `"Write a unit test for a function `add(a, b)` that checks negative numbers."*
  * *Output*: A complete Python `unittest.TestCase` block covering positive and negative edge cases.
* **Ambiguities / Edge Cases**: Distinguishing between the user asking for an explanation of an artifact versus generating the artifact itself.

---

### 6. `-complete`
* **Purpose**: Continue, finish, or fill in unfinished sentences, code functions, or documentation blocks while adhering to the established tone and syntax.
* **When Selected**: The selection ends abruptly, contains `TODO` markers, or is an unclosed code block or trailing sentence.
* **Expected Input**: Incomplete sentence, unfinished Python function, or partial outline.
* **Expected Output**: The logical completion that blends seamlessly with the prefix.
* **Example**:
  * *Input*: `def calculate_tax(income, rate):\n    # TODO: calculate net after standard deduction`
  * *Output*: Completed function implementation preserving indentation and variable naming style.
* **Ambiguities / Edge Cases**: Ambiguous trajectory; multiple divergent ways to complete a thought. The completion must remain conservative and directly relevant.

---

### 7. `-suggest`
* **Purpose**: Provide actionable recommendations, optimizations, or relevant next steps based on the reviewed content.
* **When Selected**: The selection describes a project plan, architectural design, draft text, or problem description without an explicit question.
* **Expected Input**: Draft ideas, design proposals, or procedural outlines.
* **Expected Output**: 2 to 4 concise, prioritized suggestions for improvement.
* **Example**:
  * *Input*: `"We are querying the user database on every keystroke in our autocomplete search bar."*
  * *Output*: `"1. Implement debouncing (e.g., 300ms) to reduce request frequency.\n2. Add in-memory or Redis caching for frequent queries.\n3. Ensure database search columns are properly indexed."*
* **Ambiguities / Edge Cases**: Unsolicited critique when the user simply wanted a summary; suggestions must be constructive, concise, and non-presumptuous.

---

### 8. `-rewrite`
* **Purpose**: Polish, format, rephrase, or adapt tone (e.g., more professional, more concise, active voice) while preserving core meaning.
* **When Selected**: The user highlights draft text that is colloquial, wordy, or unpolished.
* **Expected Input**: Draft paragraphs, awkward sentences, or conversational messages.
* **Expected Output**: Clean, revised text presented ready to copy.
* **Example**:
  * *Input*: `"Hey can u pls look at this pr when u get a sec kinda urgent thx"`
  * *Output*: `"Could you please review this pull request when you have a moment? It is time-sensitive. Thank you."*
* **Ambiguities / Edge Cases**: Changing technical terminology during rewriting; altering the original intent or factual claims.

---

## Candidate Intents (Future Evaluation)

The following intents are recognized as valuable candidates but are kept secondary until the 8 core intents are stabilized:

| Candidate Intent | Target Function |
| :--- | :--- |
| **`-debug`** | Dedicated deep debugging for complex multi-file or system crashes. |
| **`-review`** | Code or prose review analyzing adherence to style guides and best practices. |
| **`-extract`** | Pull structured data (JSON, dates, emails, table data) out of unstructured text. |
| **`-translate`** | Multi-lingual language translation or code dialect translation. |
| **`-teach`** | Socratic learning mode breaking down foundational principles step-by-step. |
| **`-steps`** | Convert complex instructions into an explicit step-by-step checklist. |
| **`-analyze`** | Statistical or logical scrutiny of an argument, dataset, or performance trace. |
| **`-answer`** | Direct, factual answers to explicit interrogative questions. |

---

## Current Implementation Status
* **Current Prototype**: [`prototype/main.py`](../prototype/main.py#L143-L146) currently uses a single hardcoded explanation prompt:
  ```python
  prompt = (
      "Explain the following selected text concisely and in simple, beginner-friendly terms "
      f"(2 to 3 sentences max):\n\n\"{text.strip()}\""
  )
  ```
* **Intent Classifier**: **Not implemented yet.** Intent classification logic, classifier prompt routing, and intent dispatching are scheduled for Stage 3 and Stage 4 of the [Roadmap](08-roadmap.md).

---

## Acceptance Criteria
- [ ] Classification pipeline infers core intents without user modal selection (`Planned`).
- [ ] Intent tags remain internal and are never rendered to user UI (`Planned`).
- [ ] Ambiguous or short text falls back safely to `-explain` or prompts for clarification (`Planned`).
- [ ] Code selections distinguish between explanation, debugging, and refactoring (`Planned`).
- [ ] Zero hallucinations or fact-inventions on underspecified selections (`Planned`).

---

## Open Questions
- **Open question**: Should intent classification be performed by a lightweight zero-shot classification prompt using the same local model (`llama3.2:1b`), or via deterministic regex/heuristics combined with local model verification?
- **Open question**: Should the UI offer subtle interactive "chips" (e.g., `[Summarize]`, `[Code Fix]`, `[Rewrite]`) allowing the user to override an inferred intent with a single click?
