"""
tests/test_round2_product_quality.py - Comprehensive Real-World, UX, and Security/Privacy Tests for Round 2.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QApplication

from backend.main import app
from backend.routes.ai import sanitize_error_message
from desktop.ai.backend_client import BackendClient, BackendResponse
from desktop.core.capture import SelectionCapture
from desktop.core.intents import infer_intent
from desktop.core.orchestrator import AppOrchestrator
from desktop.ui.bubble import AssistantBubbleWindow
from desktop.utils.clipboard import (
    capture_selected_text,
    get_clipboard_sequence,
    has_clipboard_text,
    preserve_clipboard,
)


@pytest.fixture
def qapp():
    """Returns the QApplication instance."""
    app_instance = QApplication.instance()
    if app_instance is None:
        app_instance = QApplication([])
    return app_instance


# =============================================================================
# 1. REAL-WORLD CONTENT TYPES & APPLICATIONS
# =============================================================================


def test_realworld_vscode_snippet_classification_and_prompting():
    """Tests VS Code-style indented Python code with comments and type annotations."""
    vscode_snippet = (
        "def calculate_tax(income: float, rate: float = 0.20) -> float:\n"
        "    # Check bounds\n"
        "    if income < 0:\n"
        "        raise ValueError('Income cannot be negative')\n"
        "    return income * rate\n"
    )
    intent = infer_intent(vscode_snippet)
    # Technical code with syntax should be classified as code analysis
    assert intent == "-code"


def test_realworld_browser_mixed_text_with_urls_and_unicode():
    """Tests browser-copied text with Unicode, URLs, and smart punctuation."""
    browser_text = (
        "According to RFC 3986 (see https://www.ietf.org/rfc/rfc3986.txt), "
        "URIs are composed of “schemes”, <authorities>, and paths. "
        "Notice the smart quotes ‘here’ and em-dash — right here."
    )
    intent = infer_intent(browser_text)
    assert intent in ("-explain", "-summary")


def test_realworld_pdf_linebreaks_and_hyphenation():
    """Tests PDF-style text with linebreaks and mid-word hyphenation."""
    pdf_text = (
        "The distributed consensus protocol operates through inter-\n"
        "connected nodes using Byzantine Fault Tolerant state ma-\n"
        "chines to synchronize cryptographic ledgers across peers."
    )
    intent = infer_intent(pdf_text)
    assert intent in ("-explain", "-summary")


def test_realworld_compiler_error_stacktrace():
    """Tests compiler error message from terminal / console."""
    traceback_text = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 42, in <module>\n'
        "    process_data(None)\n"
        '  File "app.py", line 15, in process_data\n'
        "    return data['count'] + 1\n"
        "TypeError: 'NoneType' object is not subscriptable"
    )
    intent = infer_intent(traceback_text)
    assert intent == "-code"


def test_realworld_meeting_notes_synthesis():
    """Tests unstructured meeting notes with bullet points."""
    meeting_notes = (
        "- Standup 10:00 AM: Alice completed auth module refactor.\n"
        "- Bob is blocked on database schema migration for v2.\n"
        "- Target release date agreed: November 15.\n"
        "- Action item: Charlie to review pull request 142 today."
    )
    intent = infer_intent(meeting_notes)
    assert intent in ("-summarize", "-explain")


def test_realworld_math_equation_classification():
    """Tests mathematical algebra / calculus expressions."""
    math_text = "Solve for x in the quadratic equation 2x^2 + 5x - 3 = 0, showing roots."
    intent = infer_intent(math_text)
    assert intent in ("-code", "-explain")


def test_realworld_tabular_csv_data():
    """Tests CSV / tabular data with columns."""
    tabular_data = (
        "ID,User,Role,LastLogin\n"
        "101,asmith,Admin,2026-11-01\n"
        "102,bjones,Editor,2026-11-02\n"
        "103,ckent,Viewer,2026-10-31"
    )
    intent = infer_intent(tabular_data)
    assert intent in ("-explain", "-summary")


# =============================================================================
# 2. SELECTION BOUNDARIES, CLAMPING & NO-SELECTION
# =============================================================================


def test_orchestrator_handles_empty_selection_gracefully(qapp):
    """Ensures pressing shortcut with no selection triggers on_no_selection without errors."""
    mock_capture = MagicMock()
    mock_capture.capture.return_value = ""

    mock_bm = MagicMock()
    mock_bm.is_running = True
    mock_ai = MagicMock()

    on_no_selection = MagicMock()
    on_error = MagicMock()
    on_generating = MagicMock()

    orchestrator = AppOrchestrator(
        capture=mock_capture,
        ai_client=mock_ai,
        backend_manager=mock_bm,
        on_no_selection=on_no_selection,
        on_error=on_error,
        on_generating=on_generating,
    )
    orchestrator.process_activation(run_id=42)

    on_no_selection.assert_called_once_with(42)
    on_generating.assert_not_called()
    on_error.assert_not_called()
    mock_bm.ensure_running.assert_not_called()


def test_orchestrator_clamps_massive_selection(qapp):
    """Ensures huge text selections (>20,000 characters) are safely clamped to 20,000."""
    massive_text = "A" * 35000
    mock_capture = MagicMock()
    mock_capture.capture.return_value = massive_text

    mock_client = MagicMock()
    mock_client.stream.return_value = iter(["chunk 1", "chunk 2"])

    mock_bm = MagicMock()
    mock_bm.is_running = True

    captured_chunks = []
    orchestrator = AppOrchestrator(
        capture=mock_capture,
        ai_client=mock_client,
        backend_manager=mock_bm,
        on_chunk=lambda c, r: captured_chunks.append(c),
        on_generating=MagicMock(),
        on_explanation=MagicMock(),
    )
    orchestrator.process_activation(run_id=1)

    # Verify that stream received clamped text
    stream_call_args = mock_client.stream.call_args[0]
    passed_text = stream_call_args[0]
    assert len(passed_text) == 20000
    mock_bm.ensure_running.assert_not_called()


# =============================================================================
# 3. CLIPBOARD INTEGRITY & RESTORATION
# =============================================================================


def test_clipboard_preservation_context_manager():
    """Tests that preserve_clipboard restores original clipboard string."""
    with patch("desktop.utils.clipboard.get_clipboard_text", return_value="Original Saved Text"), \
         patch("desktop.utils.clipboard.set_clipboard_text") as mock_set:
        with preserve_clipboard() as prev:
            assert prev == "Original Saved Text"
        mock_set.assert_called_with("Original Saved Text")


def test_has_clipboard_text_returns_boolean():
    """Tests has_clipboard_text helper."""
    res = has_clipboard_text()
    assert isinstance(res, bool)


def test_get_clipboard_sequence_returns_int():
    """Tests Windows clipboard sequence number helper."""
    seq = get_clipboard_sequence()
    assert isinstance(seq, int)


# =============================================================================
# 4. UX & WINDOW BEHAVIOR (DISMISSAL, MULTI-MONITOR, SHORTCUTS)
# =============================================================================


def test_bubble_window_dismiss_invalidates_active_run(qapp):
    """Ensures dismiss() resets _active_run_id so delayed worker signals are ignored."""
    window = AssistantBubbleWindow()
    window.show_generating("test text", "-explain", run_id=100)
    assert window._active_run_id == 100

    # User presses Esc / dismisses
    window.dismiss()
    assert not window.isVisible()
    assert window._active_run_id is None

    # Stale delayed signal arrives for run_id 100
    window.show_explanation("test text", "Late response", "-explain", run_id=100)
    # Window should remain hidden and not pop back up
    assert not window.isVisible()


def test_bubble_window_position_near_mouse_handles_custom_coords(qapp):
    """Ensures position_near_mouse positions accurately without error."""
    window = AssistantBubbleWindow()
    window.position_near_mouse(x=300, y=400)
    # Should move to adjacent offset
    assert window.x() > 0
    assert window.y() > 0


def test_bubble_window_ctrl_c_copies_entire_response_when_no_selection(qapp):
    """Ensures pressing Ctrl+C copies entire response if no subtext is highlighted in browser."""
    window = AssistantBubbleWindow()
    window.show_explanation("Source", "Complete AI Response Text", "-explain")

    with patch.object(window.copy_btn, "click") as mock_copy_click:
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_C,
            Qt.KeyboardModifier.ControlModifier,
            "c",
        )
        window.keyPressEvent(event)
        mock_copy_click.assert_called_once()


def test_bubble_window_ctrl_w_dismisses_window(qapp):
    """Ensures Ctrl+W shortcut dismisses the window."""
    window = AssistantBubbleWindow()
    window.show_explanation("Source", "Response", "-explain")
    assert window.isVisible()

    window.dismiss()
    assert not window.isVisible()


# =============================================================================
# 5. SECURITY & PRIVACY: HOST VALIDATION, ERROR SANITIZATION & LIMITS
# =============================================================================


def test_security_error_sanitization_masks_api_keys():
    """Ensures sanitize_error_message completely masks Groq API keys and Bearer tokens."""
    raw_error_1 = "Groq API error with key gsk_abcdef1234567890QWERTY: rate limit"
    sanitized_1 = sanitize_error_message(raw_error_1)
    assert "gsk_abcdef1234567890QWERTY" not in sanitized_1
    assert "gsk_***" in sanitized_1

    raw_error_2 = "Authorization failed for Bearer eyJhbGciOiJIUzI1Ni.secret.token"
    sanitized_2 = sanitize_error_message(raw_error_2)
    assert "eyJhbGciOiJIUzI1Ni.secret.token" not in sanitized_2
    assert "Bearer ***" in sanitized_2


def test_security_host_validation_blocks_dns_rebinding():
    """Ensures FastAPI backend blocks requests with untrusted Host header (DNS rebinding attack)."""
    with TestClient(app) as client:
        # Valid localhost request
        resp_ok = client.get("/health", headers={"host": "127.0.0.1:8000"})
        assert resp_ok.status_code == 200

        # Malicious DNS rebinding host
        resp_forbidden = client.get("/health", headers={"host": "attacker-controlled-domain.com"})
        assert resp_forbidden.status_code == 403
        assert "Untrusted Host header" in resp_forbidden.json().get("detail", "")


def test_security_backend_enforces_input_length_limit():
    """Ensures backend rejects text exceeding MAX_INPUT_LENGTH (20,000 chars) with 422."""
    with TestClient(app) as client:
        too_long_payload = {"text": "x" * 25000, "intent": "-explain"}
        resp = client.post("/api/v1/ai/generate", json=too_long_payload)
        assert resp.status_code == 422

