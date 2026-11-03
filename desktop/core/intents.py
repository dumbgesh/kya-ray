"""
desktop/core/intents.py - Intent taxonomy, heuristics, and deterministic code diagnostics.

Preserves the exact classification rules and heuristics from Kya-Ray:
- Core intents: -explain, -summarize, -code, -create
- Code detection: syntax indicators, error indicators, typed declarations, single line calls
- Deterministic code diagnostics: AST parsing, PyPI/stdlib package typo suggestions via difflib
- Creative output controls: quantity detection, conversational preamble stripping, single output trimming
"""

import ast
from dataclasses import dataclass, field
import difflib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

CORE_INTENTS = ("-explain", "-summarize", "-code", "-create")

# Content type identifiers
CONTENT_TYPE_SOURCE_CODE = "source_code"
CONTENT_TYPE_PROGRAMMING_ERROR = "programming_error"
CONTENT_TYPE_TERMINAL = "terminal_command"
CONTENT_TYPE_MATH = "math_expression"
CONTENT_TYPE_STRUCTURED_DATA = "structured_data"
CONTENT_TYPE_FOREIGN_LANGUAGE = "foreign_language"
CONTENT_TYPE_ROUGH_NOTES = "rough_notes"
CONTENT_TYPE_REWRITE = "rewrite_directive"
CONTENT_TYPE_IDEA = "idea_development"
CONTENT_TYPE_CREATIVE = "creative_request"
CONTENT_TYPE_LONG_FORM = "long_form_content"
CONTENT_TYPE_TECHNICAL_CONCEPT = "technical_concept"
CONTENT_TYPE_NATURAL_LANGUAGE = "natural_language"


@dataclass
class ContentAnalysis:
    """Rich semantic and structural content analysis result."""
    content_type: str
    suggested_intent: str
    confidence: float
    specialized_task: str
    summary_reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

# Terminal CLI tool names that signal terminal commands
CLI_COMMANDS = {
    "git", "npm", "npx", "pip", "docker", "docker-compose", "curl", "wget", "cd", "ls", "dir",
    "grep", "pytest", "python", "node", "cargo", "go", "kubectl", "make",
    "cat", "chmod", "chown", "sudo", "ssh", "powershell", "yarn", "pnpm",
    "dotnet", "find", "apt", "brew", "deno", "rustc", "gcc", "tar", "sed",
    "awk", "ps", "kill", "rm", "cp", "mv",
}

# Programming language keywords and patterns across Python, JS/TS, Go, Rust, Java, C/C++, SQL
CODE_KEYWORDS = {
    "def ", "class ", "function ", "return ", "import ",
    "const ", "let ", "var ", "public ", "private ", "protected ",
    "void ", "struct ", "async ", "await ", "try:",
    "except ", "catch ", "finally:", "lambda ", "fn ", "impl ",
    "func ", "package ", "defer ", "interface ", "export ",
    "pub fn ", "let mut ", "#include ", "SELECT ", "INSERT INTO ",
    "UPDATE ", "DELETE FROM ", "CREATE TABLE ",
}

# Error and traceback indicators
CODE_ERROR_INDICATORS = (
    "traceback (most recent call last)",
    "syntaxerror:",
    "typeerror:",
    "referenceerror:",
    "nameerror:",
    "indexerror:",
    "keyerror:",
    "valueerror:",
    "attributeerror:",
    "nullpointerexception",
    "uncaught error:",
    "uncaught typeerror:",
    "panic:",
    "segmentation fault",
    "at line ",
    "fatal:",
    "command not found",
    "no such file or directory",
    "error: ",
)

# Curated set of popular standard library and PyPI packages for deterministic typo detection
POPULAR_PYTHON_MODULES = {
    # Python Standard Library
    "sys", "os", "math", "json", "re", "time", "datetime", "typing", "collections",
    "itertools", "functools", "pathlib", "subprocess", "threading", "multiprocessing",
    "asyncio", "unittest", "logging", "urllib", "socket", "http", "sqlite3", "csv",
    "hashlib", "random", "io", "copy", "shutil", "tempfile", "glob", "pickle",
    "struct", "ctypes", "inspect", "ast", "dis", "pdb", "traceback", "gc",
    "contextlib", "dataclasses", "enum", "abc", "queue", "concurrent", "signal",
    "decimal", "fractions", "statistics", "difflib", "textwrap", "unicodedata",
    "email", "html", "xml", "zipfile", "tarfile", "gzip", "bz2", "lzma", "venv",
    "shlex", "base64", "secrets", "uuid", "platform",
    # Popular Third-Party Packages
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "requests", "httpx",
    "flask", "django", "fastapi", "uvicorn", "pydantic", "sqlalchemy", "pytest",
    "torch", "torchvision", "torchaudio", "tensorflow", "keras", "sklearn",
    "scikit-learn", "cv2", "pillow", "PIL", "yaml", "jinja2", "click", "rich",
    "celery", "redis", "pika", "boto3", "botocore", "google", "openai",
    "anthropic", "transformers", "datasets", "huggingface_hub", "polars",
    "pyarrow", "playwright", "selenium", "beautifulsoup4", "bs4", "scrapy",
    "networkx", "sympy", "tqdm", "pytz", "psutil", "alembic", "gevent", "wheel",
    "setuptools", "dotenv", "watchdog", "paramiko", "cryptography", "pyperclip",
    "pynput", "tkinter",
}

# Creation prompt trigger verbs and prefixes
CREATE_TRIGGERS = (
    "write a", "write an", "write me a", "write me an", "write me",
    "create a", "create an", "create me a", "create me an", "create me",
    "generate a", "generate an", "draft a", "draft an", "draft me a",
    "make a list of", "build a", "build an", "compose a", "compose an",
    "implement a", "implement an", "template for", "boilerplate for",
    "give me a", "give me an", "give me", "come up with", "suggest a",
    "suggest an", "suggest", "rewrite a", "rewrite an", "rewrite this",
    "rewrite as", "rewrite",
)

# Prefixes identifying explicit explanatory questions
EXPLAIN_QUESTION_PREFIXES = (
    "explain ", "explain how to ", "explain why ", "explain what ",
    "what is ", "what are ", "what was ", "what were ",
    "why is ", "why are ", "why do ", "why does ", "why did ",
    "how do ", "how does ", "how can ", "how to ",
    "tell me about ", "define ",
)

# Directives identifying explicit summarize requests
SUMMARIZE_TRIGGERS = (
    "summarize ", "summarise ", "summary of ", "tl;dr", "tldr",
    "give me a summary of", "provide a summary of", "briefly summarize",
)

# Directives identifying explicit code review and defect inspection requests
CODE_REVIEW_TRIGGERS = (
    "review this code", "review code", "code review", "find bugs", "find the bug",
    "check for bugs", "inspect for bugs", "debug this code", "debug code",
    "spot the bug", "spot bugs", "identify bugs", "what is wrong with this code",
    "what's wrong with this code", "why is this code failing",
)

TYPED_DECLARATION_PREFIXES = (
    "int ", "float ", "double ", "char ", "bool ", "boolean ",
    "void ", "val ", "auto ", "mut ", "short ", "long ", "byte ",
    "uint ", "size_t ",
)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

CREATE_NOUNS_PATTERN = (
    r"(?:reasons?|options?|ideas?|examples?|lines?|items?|ways?|points?|alternatives?|"
    r"variations?|titles?|names?|prompts?|questions?|tips?|habits?|snacks?|quotes?|"
    r"jokes?|messages?|replies?|sentences?|paragraphs?|words?)"
)

ALTERNATIVE_LEAD_INS = (
    "i'd also", "i would also", "another option", "or you could say",
    "here is another", "second option", "alternatively,", "alternatively:",
    "or alternatively", "here's another",
)


def is_typed_declaration_or_code_line(line: str) -> bool:
    """
    Checks if a single stripped line represents a typed declaration or code statement.
    Anchored to line start to avoid false matches on English prose (e.g. 'international', 'integral').
    """
    stripped = line.strip()
    if not stripped:
        return False

    for prefix in TYPED_DECLARATION_PREFIXES:
        if stripped.startswith(prefix):
            remainder = stripped[len(prefix):].strip()
            if not remainder:
                return False
            tokens = remainder.split()
            first_ident = tokens[0].split("(")[0].rstrip(";,:=")
            if first_ident.isidentifier():
                if "=" in remainder or "(" in remainder or remainder.endswith(";") or len(tokens) == 1:
                    return True

    return False


def is_assignment_line(line: str) -> bool:
    """Checks if a line is a code assignment (e.g., 'sum = a + b', 'x = 42')."""
    stripped = line.strip().rstrip(";")
    if "=" not in stripped or "==" in stripped or "!=" in stripped or "<=" in stripped or ">=" in stripped:
        return False
    parts = stripped.split("=", 1)
    lhs = parts[0].strip()
    if lhs and all(part.isidentifier() for part in lhs.split(".")):
        rhs = parts[1].strip()
        if rhs and not rhs.endswith((".", "!", "?")):
            return True
    return False


def is_single_line_code_assignment_or_call(text: str) -> bool:
    """
    Checks if a single-line text represents a code assignment or instantiation,
    such as 'app = FastAPI()' or 'client = MongoClient("localhost")',
    distinguishing it from mathematical formulas like 'y = mx + b' or 'f(x) = x^2'.
    """
    stripped = text.strip().rstrip(";")
    if "\n" in stripped or "=" not in stripped:
        return False
    if "==" in stripped or "!=" in stripped or "<=" in stripped or ">=" in stripped:
        return False

    parts = stripped.split("=", 1)
    lhs = parts[0].strip()
    rhs = parts[1].strip()

    if not (lhs.isidentifier() or all(part.isidentifier() for part in lhs.split("."))):
        return False

    if "(" in rhs and rhs.endswith(")"):
        func_token = rhs.split("(", 1)[0].strip()
        if func_token.isidentifier() or all(part.isidentifier() for part in func_token.split(".")):
            return True

    return False


def strip_surrounding_quotes(text: str) -> str:
    """
    Removes surrounding outer matching quotes from generated responses
    if the entire response is enclosed in quotes, without removing internal quotes
    or markdown backticks.
    """
    if not text:
        return text
    stripped = text.strip()
    if len(stripped) >= 2:
        if (stripped.startswith('"') and stripped.endswith('"') and stripped.count('"') == 2) or \
           (stripped.startswith("'") and stripped.endswith("'") and stripped.count("'") == 2):
            return stripped[1:-1].strip()
        if stripped.startswith('“') and stripped.endswith('”'):
            return stripped[1:-1].strip()
    return stripped


def detect_create_quantity(text: str):
    """
    Determines requested quantity for creation prompts.
    Returns (quantity: int | None, is_explicit_multiple: bool):
      - Explicit quantity (e.g., '3 reasons', '5 healthy snacks') -> (N, True)
      - Plural list or collection (e.g., 'a list of', 'a few', 'several') -> (None, True)
      - Singular request (e.g., 'a cute pickup line', 'an email', default) -> (1, False)
    """
    raw = (text or "").strip().lower()

    # Check for digit quantities with optional adjective (e.g. "3 pickup lines", "5 healthy snacks", "10 examples")
    digit_match = re.search(r'\b(\d+)\s+(?:[a-z_\-]+\s+)?' + CREATE_NOUNS_PATTERN + r'\b', raw)
    if digit_match:
        return int(digit_match.group(1)), True

    # Check for digit alone if preceded by command verbs (e.g. "give me 3", "list of 5")
    digit_solo = re.search(r'\b(?:give me|list of|top|create|write)\s+(\d+)\b', raw)
    if digit_solo:
        return int(digit_solo.group(1)), True

    # Check for number words with optional adjective (e.g. "three reasons", "two cute pickup lines", "five snacks")
    word_pattern = r'\b(' + '|'.join(NUMBER_WORDS.keys()) + r')\s+(?:[a-z_\-]+\s+)?' + CREATE_NOUNS_PATTERN + r'\b'
    word_match = re.search(word_pattern, raw)
    if word_match:
        qty = NUMBER_WORDS[word_match.group(1)]
        return qty, (qty > 1)

    word_solo = re.search(r'\b(?:give me|list of|top|create|write)\s+(' + '|'.join(NUMBER_WORDS.keys()) + r')\b', raw)
    if word_solo:
        qty = NUMBER_WORDS[word_solo.group(1)]
        return qty, (qty > 1)

    # Check for general plural or list indicators without specific count
    if any(phrase in raw for phrase in ("a list of", "make a list", "give me a few", "give me some", "options for", "ideas for", "several", "multiple")):
        return None, True

    return 1, False


def strip_conversational_preamble(text: str) -> str:
    """
    Removes common chatty conversational greetings and lead-in preambles
    specifically from creative generation outputs (e.g. 'I\'d be happy to provide...',
    'Here is a cute pickup line:').
    Does not alter genuine content if no preamble is present.
    """
    if not text:
        return text

    stripped = text.strip()

    pats = [
        r"^(?:I'd|I would) be happy to (?:provide|suggest|give|write|help you with)[^.\n]*\.\s*(?:How about:\s*|Here(?:'s| is)[^:\n]*:\s*)?",
        r"^(?:Sure|Certainly|Of course)[!.,]?\s*(?:Here(?:'s| is)[^:\n]*:?\s*)?",
        r"^(?:Here(?:'s| is) (?:a|an|one|the) [^:\n]*:\s*)",
        r"^(?:How about|What about):\s*",
    ]
    for pat in pats:
        m = re.match(pat, stripped, flags=re.IGNORECASE)
        if m:
            remainder = stripped[m.end():].strip()
            if remainder:
                stripped = remainder

    return stripped


def extract_single_creation_output(text: str) -> str:
    """
    For simple, singular creation requests, ensures only one finished output is returned,
    trimming redundant subsequent options or numbered lists while preserving multi-paragraph
    content (e.g., multi-paragraph emails or essays).
    """
    if not text:
        return text
    stripped = text.strip()

    # If format is "1. First line\n2. Second line..."
    lines = stripped.splitlines()
    if lines and (lines[0].startswith("1. ") or lines[0].startswith("1) ")):
        first_item_lines = [lines[0][3:].strip()]
        for line in lines[1:]:
            if re.match(r"^\d+[\.\)]\s+", line.strip()):
                break
            if line.strip():
                first_item_lines.append(line.strip())
            else:
                break
        return " ".join(first_item_lines)

    # If there are multiple paragraphs and any subsequent paragraph starts with an alternative lead-in
    paras = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    if len(paras) > 1:
        for idx in range(1, len(paras)):
            p_lower = paras[idx].lower().strip()
            if any(p_lower.startswith(lead) for lead in ALTERNATIVE_LEAD_INS):
                return "\n\n".join(paras[:idx])

    return stripped


def check_code_diagnostics(text: str) -> dict:
    """
    Performs deterministic static code analysis on a given text:
    1. Checks if the snippet can be parsed as Python via ast.parse.
    2. Identifies import statements and checks whether imported modules look like
       misspelled typos of well-known Python packages (e.g. 'panadas' -> 'pandas',
       'numppy' -> 'numpy').
    3. Guarantees unfamiliar modules without close matches are NOT flagged.
    4. Distinguishes Python code from shell commands and non-code prose/math.

    Returns dict:
      {
          "is_python": bool,
          "is_valid_python": bool,
          "syntax_error": str | None,
          "has_typo": bool,
          "typos": list of tuple (misspelled_name, suggested_match),
          "diagnostics_note": str | None,
      }
    """
    raw = (text or "").strip()
    result = {
        "is_python": False,
        "is_valid_python": False,
        "syntax_error": None,
        "has_typo": False,
        "typos": [],
        "diagnostics_note": None,
    }
    if not raw:
        return result

    # Check if text is a shell command (e.g., starts with CLI command name)
    first_token = raw.split()[0].lower() if raw.split() else ""
    if first_token in ("$", ">", "#") and len(raw.split()) > 1:
        first_token = raw.split()[1].lower()
    if first_token in CLI_COMMANDS:
        return result

    # Check for pure math equations that aren't programming code
    if any(raw.startswith(m) for m in ("y = mx + b", "f(x) =", "E = mc^2", "A = pi * r^2")):
        return result

    try:
        tree = ast.parse(raw)
        result["is_python"] = True
        result["is_valid_python"] = True

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    imported_modules.append(root_mod)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    imported_modules.append(root_mod)

        typos = []
        for mod in imported_modules:
            mod_lower = mod.lower()
            if mod_lower not in POPULAR_PYTHON_MODULES:
                matches = difflib.get_close_matches(mod_lower, POPULAR_PYTHON_MODULES, n=1, cutoff=0.75)
                if matches and matches[0] != mod_lower:
                    typos.append((mod, matches[0]))

        if typos:
            result["has_typo"] = True
            result["typos"] = typos
            typo_notes = [f"'{t[0]}' appears to be a typo for '{t[1]}'" for t in typos]
            result["diagnostics_note"] = (
                f"Static check detected likely import typo: {', '.join(typo_notes)}. "
                f"Point out the typo and suggest the correction separately; do not silently normalize it."
            )
        elif imported_modules or any(kw in raw for kw in ("def ", "class ", "async def ", "app = ", "return ", "=")):
            result["diagnostics_note"] = (
                "Static analysis confirms valid Python syntax. Inspect for logic defects, edge cases, and runtime behavior."
            )

    except SyntaxError as e:
        if any(kw in raw for kw in ("def ", "class ", "import ", "from ", "return ", "async def ")):
            result["is_python"] = True
            result["is_valid_python"] = False
            result["syntax_error"] = f"SyntaxError at line {e.lineno}: {e.msg}"
            result["diagnostics_note"] = f"Static analysis detected genuine syntax error: {e.msg} at line {e.lineno}."
    except Exception:
        pass

    return result


def is_math_expression(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Identifies mathematical expressions, equations, arithmetic calculations,
    and calculus/algebra notation, distinguishing them from code assignments.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}

    # LaTeX and mathematical symbols
    math_symbols = (
        r"\int", r"\sum", r"\sqrt", r"\frac", r"\partial", r"\lim",
        r"\theta", r"\pi", r"\pm", r"\approx", r"\neq", r"\leq", r"\geq",
        r"\times", r"\div", r"\in", r"\infty", "±", "≈", "≠", "≤", "≥", "×", "÷", "π", "√", "∫", "∑",
    )
    if any(sym in raw for sym in math_symbols):
        return True, "math_symbols", {"has_latex": any(sym.startswith("\\") for sym in math_symbols if sym in raw)}

    # Direct calculation or solve verbs
    if re.match(r"^(?:calculate|evaluate|solve|compute|simplify|find\s+the\s+derivative\s+of|integrate)\s+", raw, re.IGNORECASE):
        return True, "math_directive", {}

    # Standard mathematical formulas and physics equations
    known_formulas = (
        "y = mx + b", "f(x) =", "g(x) =", "h(x) =", "e = mc^2",
        "a^2 + b^2 = c^2", "dy/dx =", "a = pi * r^2", "v = u + at",
    )
    raw_lower = raw.lower()
    if any(raw_lower.startswith(f) for f in known_formulas):
        return True, "known_formula", {}

    # Function notation: e.g., f(x) = x^2 - 4x + 3
    if re.match(r"^[a-zA-Z]\([a-zA-Z]\)\s*=", raw):
        return True, "function_definition", {}

    # Calculus / math function operators
    if re.search(r"\b(?:dy/dx|\^|sqrt|sin|cos|tan|log|ln)\b", raw_lower) and any(c in raw for c in ("=", "+", "-", "*", "/", "^")):
        return True, "math_operators", {}

    # Clean arithmetic expressions: e.g. "(144 / 12) * 5 + 7^2" or "25 * 1.18 - 45"
    if re.match(r"^[0-9x\s\+\-\*\/\^\(\)\=\.\%\,]+$", raw) and any(op in raw for op in "+-*/^%="):
        # Exclude plain comma-separated numbers (e.g. "1, 2, 3") unless operators present
        if any(op in raw for op in "+-*/^%="):
            tokens = raw.split()
            # If it contains equals, check if it's an equation
            return True, "arithmetic_expression", {}

    # Quantitative / financial / algebraic word problems asking to calculate, find, or determine values
    action_calc_patterns = (
        r"\b(?:calculate|determine|evaluate|compute|find the|solve for|find)\b",
        r"\b(?:how many|what is the break-even|what is the total|what is the net profit|what is the probability|what is the volume)\b",
    )
    math_quant_terms = (
        r"\b(?:break-even|fixed costs?|variable costs?|costs?|profit|margin|revenue|price|volume|units|rate|interest|probability|discount|per unit)\b"
    )
    has_calc_action = any(re.search(pat, raw, re.IGNORECASE) for pat in action_calc_patterns)
    has_quant_terms = bool(re.search(math_quant_terms, raw, re.IGNORECASE))
    has_numbers = bool(re.search(r"[\$€£₹]?\d+[\d,]*\.?\d*", raw))

    if has_calc_action and (has_quant_terms or has_numbers):
        # Ensure it's not merely asking to explain a concept without a calculation
        is_concept_question = raw_lower.startswith("explain ") and not any(
            term in raw_lower for term in ("calculate", "determine", "how many", "find the", "solve")
        )
        if not is_concept_question:
            return True, "quantitative_word_problem", {"has_calc_action": True, "has_quant_terms": has_quant_terms}

    return False, "", {}


def is_structured_data(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Identifies structured data formats: JSON, YAML, CSV, TSV, and Markdown tables.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}

    # JSON Object or Array
    if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith("[") and raw.endswith("]")):
        try:
            parsed = json.loads(raw)
            return True, "json", {"is_array": isinstance(parsed, list), "keys_count": len(parsed) if isinstance(parsed, (dict, list)) else 0}
        except Exception:
            # Check for JSON fragment
            if re.search(r'"[a-zA-Z0-9_\-]+"\s*:\s*', raw):
                return True, "json_fragment", {}

    raw_lines = [line for line in raw.splitlines() if line.strip()]
    stripped_lines = [line.strip() for line in raw_lines]

    if len(raw_lines) >= 2:
        # Markdown table
        if all(line.startswith("|") and line.endswith("|") for line in stripped_lines[:2]) and any("---" in line for line in stripped_lines):
            return True, "markdown_table", {"rows": len(raw_lines)}

        # CSV / TSV
        for sep in (",", "\t"):
            counts = [line.count(sep) for line in stripped_lines]
            if counts[0] >= 1 and all(c == counts[0] for c in counts):
                return True, "csv" if sep == "," else "tsv", {"columns": counts[0] + 1, "rows": len(raw_lines)}

        # YAML (first line is a key:, subsequent lines have indentation or list items)
        if any(re.match(r"^[a-zA-Z0-9_\-]+:\s*", line) for line in stripped_lines):
            if any(line.startswith("  ") or line.startswith("    ") or line.startswith("\t") or line.startswith("- ") for line in raw_lines[1:]):
                return True, "yaml", {"lines": len(raw_lines)}

    return False, "", {}


def is_foreign_language(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Detects foreign-language text using non-Latin Unicode script density
    or explicit translation directives.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}

    raw_lower = raw.lower()

    # Explicit translation requests
    translation_prefixes = (
        "translate to english:", "translate into english:", "translate this:",
        "traduis en anglais:", "traduce al inglés:", "traduzir para o inglês:",
        "übersetze ins englische:",
    )
    if any(raw_lower.startswith(prefix) for prefix in translation_prefixes):
        return True, "translation_directive", {}

    # Check non-Latin Unicode scripts:
    # CJK (\u4e00-\u9fff), Kana (\u3040-\u30ff), Hangul (\uac00-\ud7af),
    # Cyrillic (\u0400-\u04ff), Arabic (\u0600-\u06ff), Devanagari (\u0900-\u097f),
    # Greek (\u0370-\u03ff), Hebrew (\u0590-\u05ff)
    non_latin_pattern = re.compile(
        r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff\u0900-\u097f\u0370-\u03ff\u0590-\u05ff]"
    )
    non_latin_chars = non_latin_pattern.findall(raw)
    alpha_chars = [c for c in raw if c.isalpha()]

    if len(non_latin_chars) >= 2 and len(alpha_chars) > 0:
        ratio = len(non_latin_chars) / len(alpha_chars)
        if ratio >= 0.25:
            return True, "non_latin_script", {"matched_chars": len(non_latin_chars), "ratio": round(ratio, 2)}

    # Latin-based foreign common phrases / greetings
    latin_foreign_markers = (
        "¿cómo estás", "bonjour", "merci beaucoup", "s'il vous plaît",
        "danke schön", "guten tag", "auf wiedersehen", "arigato",
        "buenos días", "hasta luego", "por favor", "grazie mille",
    )
    if any(marker in raw_lower for marker in latin_foreign_markers):
        return True, "foreign_phrases", {}

    return False, "", {}


def is_narrative_prose(text: str) -> bool:
    """
    Detects literary, fiction, story dialogue, or narrative natural language prose.
    Ensures that narrative text containing common English words like 'return', 'let', 'catch',
    or punctuation is not erroneously classified as source code.
    """
    raw = (text or "").strip()
    if not raw:
        return False

    # Check for absence of unambiguous code markers
    has_unambiguous_code = bool(re.search(
        r'^\s*(?:def\s+|async\s+def\s+|class\s+|function\s+|func\s+|fn\s+|impl\s+|import\s+|from\s+\w+\s+import)',
        raw, re.MULTILINE
    ))
    if has_unambiguous_code:
        return False

    # Check for dialogue quotes
    has_quotes = bool(re.search(r'["\'“”‘’][A-Z][^"\'“”‘’]+["\'“”‘’]', raw))

    # Narrative vocabulary characteristic of stories, fiction, or literary descriptions
    narrative_terms = (
        r"\b(?:whispered|screamed|gasped|shivered|shadows?|darkness|alleyway|revolver|"
        r"detective|corridor|footsteps?|pavement|silence|doorway|night|mist|rain|"
        r"clung|stared?|staring|glanced?|murmured?|creaked?|flickered?|trembled?|breath|gaze|"
        r"room|desk|door|window|hallway|heart|mind|eyes|voice|silent|sudden)\b"
    )
    narrative_matches = len(re.findall(narrative_terms, raw, re.IGNORECASE))

    # Multiple natural sentences ending with punctuation followed by capital letters
    sentences = [s.strip() for s in re.split(r'[.!?]+\s+', raw) if s.strip()]
    has_multiple_sentences = len(sentences) >= 2

    # Pronoun / natural language prose flow
    pronoun_count = len(re.findall(r"\b(?:she|he|her|his|they|them|their|i|my|we|our)\b", raw, re.IGNORECASE))

    return (narrative_matches >= 2 or (has_quotes and has_multiple_sentences) or (has_multiple_sentences and pronoun_count >= 2))


def is_meeting_notes_or_status_updates(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Identifies meeting notes, project status updates, progress reports, or schedules.
    Distinguishes informational notes intended for summarisation from requests to create something new.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}

    # Never treat source code as meeting notes
    if any(line.strip().startswith((
        "def ", "class ", "function ", "async def ", "public class ", "import ", "interface ",
        "func ", "pub fn ", "package ", "export default ", "SELECT ", "while ",
    )) for line in raw.splitlines()):
        return False, "", {}

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    bullet_prefixes = ("- ", "* ", "• ", "1. ", "2. ", "3. ", "- [ ] ")
    bullet_lines = [l for l in lines if any(l.startswith(bp) for bp in bullet_prefixes)]

    raw_lower = raw.lower()
    has_meeting_header = any(raw_lower.startswith(p) for p in ("meeting notes", "minutes:", "standup:", "status update:", "sync notes:"))

    # Require either at least 2 bullet points or an explicit meeting header
    if len(bullet_lines) < 2 and not has_meeting_header:
        return False, "", {}

    if any(raw_lower.startswith(p) for p in ("todo:", "ideas:", "draft:", "outline:", "idea:")):
        return False, "", {}

    status_keywords = (
        r"\b(?:complete|completed|% complete|percent complete|\b\d+%\b|"
        r"postponed|delayed|in progress|on track|off track|behind schedule|"
        r"begins?|starts?|target is|deadline|milestone|scheduled|target release|"
        r"released|shipped|approved|pending|blocked|resolved|status:?|update:?|"
        r"sync|standup|sprint \d+|q[1-4]|testing begins|deployment target)\b"
    )

    status_matches = 0
    imperative_verb_starts = 0

    imperative_verbs = (
        "fix", "add", "finalize", "ping", "set up", "setup", "buy", "call", "file",
        "deploy", "implement", "create", "write", "update", "refactor", "test",
        "send", "check", "review", "clean", "remove", "delete", "build"
    )

    lines_to_check = bullet_lines if bullet_lines else lines
    for line in lines_to_check:
        clean = line.lstrip("-*•1234567890. []").strip().lower()
        if re.search(status_keywords, clean):
            status_matches += 1
        words = clean.split()
        if words and words[0] in imperative_verbs:
            imperative_verb_starts += 1

    if status_matches >= 2 or (status_matches >= 1 and imperative_verb_starts == 0 and len(bullet_lines) >= 2):
        return True, "meeting_notes", {"status_matches": status_matches}

    return False, "", {}


def is_code_construct(raw: str) -> bool:
    """
    Validates whether keywords appear in genuine programming language syntax context
    rather than coincidental occurrences in natural language prose.
    """
    unambiguous_patterns = (
        r'^\s*(?:def|async\s+def|class|function|async\s+function|func|fn|pub\s+fn|impl|package)\s+[a-zA-Z_]\w*',
        r'^\s*#include\s+[<"].+[>"]',
        r'^\s*(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE)\s+',
        r'^\s*(?:import\s+[a-zA-Z_]\w*|from\s+[a-zA-Z_]\w*\s+import\s+)',
        r'^\s*export\s+(?:default|const|function|class|let|var)\s+',
    )
    for pat in unambiguous_patterns:
        if re.search(pat, raw, re.MULTILINE | re.IGNORECASE):
            return True

    # Variable declaration in JS/TS/Go/Rust
    if re.search(r'^\s*(?:let(?:\s+mut)?|const|var)\s+[a-zA-Z_$]\w*\s*[:=]', raw, re.MULTILINE):
        return True

    # Indented or solo code return statement (not English prose 'no return', 'return to', etc.)
    for m in re.finditer(r'(?:^|\n)\s{2,}return(?:\s+[^;\n]+|;|\s*$)', raw):
        expr = m.group(0).strip()[6:].strip()
        if not re.match(r'^(?:to|from|of|home|back|with|for|in|on|at|the|a|an)\b', expr, re.IGNORECASE):
            return True

    if re.search(r'^\s*try:\s*$', raw, re.MULTILINE) or re.search(r'\bcatch\s*\([^\)]*\)', raw):
        return True

    return False


def detect_explicit_action_directive(text: str) -> Optional[ContentAnalysis]:
    """
    Extracts explicit user action instructions located at start, end, or standalone.
    Ensures user intent takes precedence over passive content characteristics.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return None

    first_line = lines[0]
    last_line = lines[-1]

    continuation_pattern = (
        r"^(?:continue(?:\s+writing|\s+from\s+here)?(?:\s+(?:the|this|on|with))?\s*"
        r"(?:story|narrative|scene|text|draft|paragraph|poem|plot|dialogue|piece|excerpt)?|"
        r"what happens next\??|take it from here|keep going|write (?:the )?(?:next|rest|continuation)|"
        r"finish (?:the|this) (?:story|narrative)|complete (?:the|this) (?:story|narrative))$"
    )

    code_review_pattern = (
        r"^(?:review this code|review code|code review|find (?:the )?bugs?|spot (?:the )?bugs?|"
        r"check for bugs|inspect for bugs|debug this code|debug code|debug this|debug|"
        r"what(?:'s| is) wrong with this(?: code)?\??|why is this (?:code )?failing\??|"
        r"why does this (?:code )?fail\??|find errors?|fix this (?:code|error|bug))$"
    )

    summarize_pattern = (
        r"^(?:(?:please )?summarize\b.*|(?:please )?summarise\b.*|"
        r"summary of .*|give me a summary.*|"
        r"provide a summary.*|briefly summarize.*|"
        r"tl;?dr|recap\b.*|key takeaways.*)$"
    )

    rewrite_pattern = (
        r"^(?:rewrite\b.*|make this (?:more )?(?:polite|concise|professional|better).*|"
        r"rephrase\b.*|paraphrase\b.*|polish this.*|fix grammar.*)$"
    )

    # Check last line first (most common for trailing instructions like 'Continue the story')
    candidates = [last_line]
    if len(lines) > 1:
        candidates.append(first_line)

    for cand in candidates:
        cand_clean = cand.strip("\"'`“”‘’ ").rstrip(".!?:;,")
        cand_lower = cand_clean.lower()

        if re.match(continuation_pattern, cand_lower):
            return ContentAnalysis(
                content_type=CONTENT_TYPE_CREATIVE,
                suggested_intent="-create",
                confidence=0.98,
                specialized_task="continue_writing",
                summary_reason=f"Detected explicit continuation directive: '{cand}'.",
            )
        if re.match(code_review_pattern, cand_lower):
            return ContentAnalysis(
                content_type=CONTENT_TYPE_SOURCE_CODE,
                suggested_intent="-code",
                confidence=0.98,
                specialized_task="review_code",
                summary_reason=f"Detected explicit code review/debugging directive: '{cand}'.",
            )
        if re.match(summarize_pattern, cand_lower):
            return ContentAnalysis(
                content_type=CONTENT_TYPE_LONG_FORM,
                suggested_intent="-summarize",
                confidence=0.98,
                specialized_task="summarize_longform",
                summary_reason=f"Detected explicit summarization directive: '{cand}'.",
            )
        if re.match(rewrite_pattern, cand_lower):
            return ContentAnalysis(
                content_type=CONTENT_TYPE_REWRITE,
                suggested_intent="-create",
                confidence=0.98,
                specialized_task="rewrite_and_polish",
                summary_reason=f"Detected explicit rewrite/polishing directive: '{cand}'.",
            )

    return None


def is_rough_notes_or_rewrite(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Identifies rough ideas, bullet outlines to develop, or explicit rewriting/polishing directives.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}

    # Meeting notes or status updates should be summarized, not treated as rough notes to expand
    if is_meeting_notes_or_status_updates(raw)[0]:
        return False, "", {}

    raw_lower = raw.lower()

    # Explicit rewrite / polish requests
    rewrite_patterns = (
        "rewrite this", "rewrite to sound", "rewrite in", "rewrite as", "rewrite",
        "make this more", "make this polite", "make this concise", "make this professional", "make this",
        "rephrase", "paraphrase", "fix grammar", "improve this writing", "improve this paragraph",
        "polish this draft", "polish this", "proofread and edit", "proofread",
    )
    if any(pat in raw_lower for pat in rewrite_patterns):
        return True, "rewrite", {}

    # Rough bullet outlines (< 15 words per line, 2+ bullet lines)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    bullet_prefixes = ("- ", "* ", "• ", "1. ", "2. ", "3. ", "- [ ] ")
    if len(lines) >= 2:
        bullet_lines = [l for l in lines if any(l.startswith(bp) for bp in bullet_prefixes)]
        if len(bullet_lines) >= 2 and len(bullet_lines) / len(lines) >= 0.6:
            # Check that lines are short fragments/notes
            avg_words = sum(len(l.split()) for l in bullet_lines) / len(bullet_lines)
            if avg_words <= 15:
                return True, "rough_notes", {"bullet_count": len(bullet_lines), "avg_words": round(avg_words, 1)}

    # Prefixes indicating draft / idea notes
    if any(raw_lower.startswith(p) for p in ("notes:", "todo:", "ideas:", "draft:", "outline:")):
        return True, "notes_prefix", {}

    return False, "", {}


def is_idea_development(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Identifies proposed application ideas, business concepts, or product proposals
    intended to be developed into outlines, essays, drafts, or structured plans.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}

    idea_markers = (
        r"\b(?:idea for|concept for|proposal for|project idea|app idea|application idea|"
        r"startup idea|business idea|essay idea|college application|college app|"
        r"common app|personal statement|product idea|feature idea|pitch:|product concept|"
        r"business concept|project proposal|system concept)\b"
    )
    develop_directives = (
        r"\b(?:develop this|develop into|develop a|develop an|flesh this out|flesh out|expand on this|expand into|"
        r"create a plan|turn this into|structure and outline|outline for my|outline for an?|draft a pitch|"
        r"build an outline|help me structure|create an outline)\b"
    )

    has_idea_marker = bool(re.search(idea_markers, raw, re.IGNORECASE))
    has_develop_directive = bool(re.search(develop_directives, raw, re.IGNORECASE))

    if has_idea_marker or has_develop_directive:
        return True, "idea_development", {
            "has_marker": has_idea_marker,
            "has_directive": has_develop_directive,
        }

    return False, "", {}


def is_programming_error(text: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Identifies programming errors, tracebacks, compiler diagnostics, and exceptions.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "", {}
    raw_lower = raw.lower()

    for err in CODE_ERROR_INDICATORS:
        if err in raw_lower:
            return True, "known_error_indicator", {"indicator": err}

    extra_error_patterns = (
        "panic: runtime error:", "fatal error:", "segmentation fault",
        "npm err!", "caused by:", "exception in thread", "[error]",
    )
    for err in extra_error_patterns:
        if err in raw_lower:
            return True, "system_error", {"indicator": err}

    # Compiler diagnostics: e.g. "error[E0308]:", "TS2322:", "line 15: error:"
    if re.search(r"(?:error\[E\d+\]|TS\d+|line\s+\d+:\s*error:?)", raw, re.IGNORECASE):
        return True, "compiler_diagnostic", {}

    return False, "", {}


def analyze_content(text: str) -> ContentAnalysis:
    """
    Performs comprehensive structural and semantic content analysis with strict priority:
    1. Explicit user instructions and action requests.
    2. Mathematical problems and programming errors.
    3. Creation, development and rewriting requests.
    4. Content-type-specific interpretation (code, data, foreign language).
    5. Long-form summarisation as a fallback.
    6. Default conceptual/general explanation.
    """
    if not text or not text.strip():
        return ContentAnalysis(
            content_type=CONTENT_TYPE_NATURAL_LANGUAGE,
            suggested_intent="-explain",
            confidence=1.0,
            specialized_task="explain_general",
            summary_reason="Empty or whitespace text defaults to explain.",
        )

    raw = text.strip()
    lower = raw.lower()
    first_line = lower.splitlines()[0].strip() if lower.splitlines() else lower
    words = raw.split()
    word_count = len(words)
    is_prose = is_narrative_prose(raw)

    # ---------------------------------------------------------
    # PRIORITY 1: Explicit user instructions and action requests
    # ---------------------------------------------------------
    action_directive = detect_explicit_action_directive(raw)
    if action_directive is not None:
        return action_directive

    is_explanatory_question = any(lower.startswith(p) for p in EXPLAIN_QUESTION_PREFIXES)

    # 1A. Explicit summarize directive (e.g. 'summarize this', 'tl;dr', 'summary of')
    if any(lower.startswith(trigger) for trigger in SUMMARIZE_TRIGGERS):
        return ContentAnalysis(
            content_type=CONTENT_TYPE_LONG_FORM,
            suggested_intent="-summarize",
            confidence=0.98,
            specialized_task="summarize_longform",
            summary_reason="Explicit summarize directive prefix.",
        )

    # 1B. Explicit rewrite / editing requests (e.g. 'rewrite this...', 'make this more...', 'fix grammar')
    is_rough, rough_type, rough_meta = is_rough_notes_or_rewrite(raw)
    if is_rough and not is_explanatory_question and rough_type == "rewrite":
        return ContentAnalysis(
            content_type=CONTENT_TYPE_REWRITE,
            suggested_intent="-create",
            confidence=0.96,
            specialized_task="rewrite_and_polish",
            summary_reason="Detected explicit rewrite/polishing directive.",
            metadata=rough_meta,
        )

    # 1C. Explicit creation directives (e.g. 'write a...', 'draft a...', 'give me 3...')
    if not is_explanatory_question:
        for trigger in CREATE_TRIGGERS:
            if lower.startswith(trigger) or (word_count < 30 and (f" {trigger} " in f" {lower} " or lower.startswith(trigger))):
                return ContentAnalysis(
                    content_type=CONTENT_TYPE_CREATIVE,
                    suggested_intent="-create",
                    confidence=0.96,
                    specialized_task="generate_artifact",
                    summary_reason=f"Explicit creative/drafting trigger: '{trigger}'.",
                )

    # 1D. Explicit code review / bug inspection directives
    for trigger in CODE_REVIEW_TRIGGERS:
        if lower.startswith(trigger) or (word_count < 40 and f" {trigger} " in f" {lower} "):
            return ContentAnalysis(
                content_type=CONTENT_TYPE_SOURCE_CODE,
                suggested_intent="-code",
                confidence=0.98,
                specialized_task="review_code",
                summary_reason=f"Explicit code review trigger: '{trigger}'.",
            )

    # ---------------------------------------------------------
    # PRIORITY 2: Mathematical problems and programming errors
    # ---------------------------------------------------------
    # 2A. Programming errors, exceptions, compiler diagnostics, and stack traces -> -code
    is_err, err_type, err_meta = is_programming_error(raw)
    if is_err:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_PROGRAMMING_ERROR,
            suggested_intent="-code",
            confidence=0.98,
            specialized_task="diagnose_error",
            summary_reason=f"Detected error log or traceback ({err_type}).",
            metadata=err_meta,
        )

    # 2B. Mathematical expressions, equations, and quantitative word problems -> -explain
    is_math, math_type, math_meta = is_math_expression(raw)
    if is_math and not is_prose:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_MATH,
            suggested_intent="-explain",
            confidence=0.95,
            specialized_task="solve_math",
            summary_reason=f"Detected mathematical expression or problem ({math_type}).",
            metadata=math_meta,
        )

    # ---------------------------------------------------------
    # PRIORITY 3: Meeting notes, status updates, or progress reports -> -summarize
    # ---------------------------------------------------------
    is_meeting, meeting_type, meeting_meta = is_meeting_notes_or_status_updates(raw)
    if is_meeting and not is_explanatory_question:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_LONG_FORM,
            suggested_intent="-summarize",
            confidence=0.96,
            specialized_task="summarize_notes",
            summary_reason="Detected meeting notes, status updates, or progress report.",
            metadata=meeting_meta,
        )

    # ---------------------------------------------------------
    # PRIORITY 4: Creation, development and rewriting requests
    # ---------------------------------------------------------
    # 4A. Rewrite & polish directives -> -create
    is_rough, rough_type, rough_meta = is_rough_notes_or_rewrite(raw)
    if is_rough and not is_explanatory_question and rough_type == "rewrite":
        return ContentAnalysis(
            content_type=CONTENT_TYPE_REWRITE,
            suggested_intent="-create",
            confidence=0.95,
            specialized_task="rewrite_and_polish",
            summary_reason="Detected explicit rewrite/polishing directive.",
            metadata=rough_meta,
        )

    # 4B. Proposed application ideas, business concepts, or project proposals to develop -> -create
    is_idea, idea_type, idea_meta = is_idea_development(raw)
    if is_idea and not is_explanatory_question:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_IDEA,
            suggested_intent="-create",
            confidence=0.94,
            specialized_task="develop_idea",
            summary_reason="Detected proposed idea or concept development request.",
            metadata=idea_meta,
        )

    # 4C. Rough notes and bullet outlines -> -create
    if is_rough and not is_explanatory_question and rough_type in ("rough_notes", "notes_prefix") and not is_meeting:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_ROUGH_NOTES,
            suggested_intent="-create",
            confidence=0.90,
            specialized_task="expand_notes",
            summary_reason=f"Detected rough outline or notes fragment ({rough_type}).",
            metadata=rough_meta,
        )

    # ---------------------------------------------------------
    # PRIORITY 5: Content-type-specific interpretation
    # ---------------------------------------------------------
    if not is_prose:
        # 5A. Explicit code syntax, symbols, typed declarations -> -code
        has_code_symbols = (
            ("=>" in raw) or
            ("===" in raw) or
            ("!==" in raw) or
            ("{" in raw and "}" in raw and "\n" in raw) or
            (raw.endswith(";") and ("=" in raw or "(" in raw)) or
            is_single_line_code_assignment_or_call(raw)
        )
        if has_code_symbols:
            task = "explain_code" if is_explanatory_question else "review_code"
            reason = "Explicit question explaining code." if is_explanatory_question else "Detected programming language syntax symbols."
            return ContentAnalysis(
                content_type=CONTENT_TYPE_SOURCE_CODE,
                suggested_intent="-code",
                confidence=0.96,
                specialized_task=task,
                summary_reason=reason,
            )

        has_explicit_code_def = any(
            line.strip().startswith((
                "def ", "class ", "function ", "async def ", "public class ", "import ", "interface ",
                "func ", "pub fn ", "package ", "export default ", "export function ", "export const ",
                "SELECT ", "INSERT INTO ", "UPDATE ", "DELETE FROM ", "CREATE TABLE ",
            ))
            or (line.strip().startswith("from ") and " import " in line)
            or is_typed_declaration_or_code_line(line)
            for line in raw.splitlines()
        )
        if has_explicit_code_def:
            task = "explain_code" if is_explanatory_question else "review_code"
            reason = "Explicit question explaining code." if is_explanatory_question else "Detected function/class definition or typed code declaration."
            return ContentAnalysis(
                content_type=CONTENT_TYPE_SOURCE_CODE,
                suggested_intent="-code",
                confidence=0.96,
                specialized_task=task,
                summary_reason=reason,
            )

        # Multiline code block signals (>= 2 lines with assignments or typed statements)
        raw_lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if len(raw_lines) >= 2:
            code_signal_lines = sum(
                1 for line in raw_lines
                if is_typed_declaration_or_code_line(line) or is_assignment_line(line)
            )
            if code_signal_lines >= 2:
                task = "explain_code" if is_explanatory_question else "review_code"
                reason = "Explicit question explaining code." if is_explanatory_question else "Detected multiline code statements with assignments."
                return ContentAnalysis(
                    content_type=CONTENT_TYPE_SOURCE_CODE,
                    suggested_intent="-code",
                    confidence=0.94,
                    specialized_task=task,
                    summary_reason=reason,
                )

        # 5B. Terminal commands (< 30 words) -> -code
        first_token = first_line.split()[0] if first_line.split() else ""
        if first_token in ("$", ">", "#") and len(first_line.split()) > 1:
            first_token = first_line.split()[1]
        is_cli = first_token in CLI_COMMANDS
        if first_token == "make" and len(first_line.split()) > 1:
            second_token = first_line.split()[1].lower()
            if second_token in ("this", "a", "an", "me", "it", "the", "sure", "more", "them", "us"):
                is_cli = False
        if is_cli and word_count < 30:
            return ContentAnalysis(
                content_type=CONTENT_TYPE_TERMINAL,
                suggested_intent="-code",
                confidence=0.92,
                specialized_task="explain_terminal",
                summary_reason=f"Detected CLI terminal command '{first_token}'.",
            )

        # 5C. Code keywords in code syntax context -> -code
        if not is_explanatory_question and is_code_construct(raw):
            return ContentAnalysis(
                content_type=CONTENT_TYPE_SOURCE_CODE,
                suggested_intent="-code",
                confidence=0.90,
                specialized_task="review_code",
                summary_reason="Detected code keyword construct.",
            )

    # 5D. Structured data (JSON, YAML, CSV, Markdown table) -> -explain
    is_data, data_type, data_meta = is_structured_data(raw)
    if is_data:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_STRUCTURED_DATA,
            suggested_intent="-explain",
            confidence=0.92,
            specialized_task="interpret_data",
            summary_reason=f"Detected structured data format ({data_type}).",
            metadata=data_meta,
        )

    # 4E. Foreign language text -> -explain
    is_foreign, foreign_type, foreign_meta = is_foreign_language(raw)
    if is_foreign:
        return ContentAnalysis(
            content_type=CONTENT_TYPE_FOREIGN_LANGUAGE,
            suggested_intent="-explain",
            confidence=0.92,
            specialized_task="translate_and_explain",
            summary_reason=f"Detected foreign language or translation prompt ({foreign_type}).",
            metadata=foreign_meta,
        )

    # ---------------------------------------------------------
    # PRIORITY 5: Long-form summarisation as a fallback
    # ---------------------------------------------------------
    # Substantial informational/narrative prose (word_count >= 45, or meeting minutes, or multi-paragraph >= 20 words)
    has_bullets = any(line.strip().startswith(("-", "*", "•")) for line in raw.splitlines())
    has_multiple_paragraphs = len([p for p in raw.split("\n\n") if p.strip()]) >= 2
    is_meeting_notes = lower.startswith("meeting notes") or lower.startswith("minutes:")
    if word_count >= 45 or is_meeting_notes or ((has_multiple_paragraphs or has_bullets) and word_count >= 20):
        return ContentAnalysis(
            content_type=CONTENT_TYPE_LONG_FORM,
            suggested_intent="-summarize",
            confidence=0.90,
            specialized_task="summarize_longform",
            summary_reason=f"Substantial content length ({word_count} words) with no higher-priority action.",
        )

    # ---------------------------------------------------------
    # PRIORITY 6: Default to -explain
    # ---------------------------------------------------------
    is_concept = (
        bool(re.search(
            r"\b(?:concept|theory|principle|definition|meaning|difference|architecture|"
            r"mechanism|api|http|tcp|ip|oauth|jwt|rest|graphql|sql|nosql|docker|k8s|cloud|dns|mathematical)\b",
            lower,
        ))
        or any(lower.startswith(p) for p in ("explain ", "what is ", "what are ", "why is ", "why are ", "how does ", "how do "))
    )
    return ContentAnalysis(
        content_type=CONTENT_TYPE_TECHNICAL_CONCEPT if is_concept else CONTENT_TYPE_NATURAL_LANGUAGE,
        suggested_intent="-explain",
        confidence=0.85,
        specialized_task="explain_concept" if is_concept else "explain_general",
        summary_reason="Concept, phrase, or question defaulted to explain.",
    )


def infer_intent(text: str) -> str:
    """
    Infers the user's intended task from the highlighted content without
    requiring manual mode selection.

    Returns one of:
      - '-code': For terminal commands, code snippets, stack traces, errors.
      - '-create': For explicit artifact/content generation prompts.
      - '-summarize': For long prose, multi-paragraph text, meeting notes.
      - '-explain': For concepts, short terms, idioms, questions, and defaults.
    """
    analysis = analyze_content(text)
    return analysis.suggested_intent

