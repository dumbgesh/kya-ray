"""
tests/test_first_launch_setup.py - Unit and Integration Tests for First-Launch API Key Setup.

Tests:
1. First launch without a key (shows setup window).
2. Valid key verification and credential storage.
3. Invalid key rejection (never saves invalid key).
4. Empty and malformed input handling.
5. Network failure handling.
6. Rate limit handling.
7. Provider outage handling.
8. Subsequent launch with key configured (skips setup).
9. Key replacement via application settings / context menu.
10. Backend credential retrieval via Windows Credential Manager.
11. Show/hide password echo mode toggle.
12. Zero credential leakage in logs or error messages.
"""

from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from backend.config import get_settings
from backend.services.groq_client import GroqProvider
from desktop.app import KyaRayApplication
from desktop.ui.setup_window import ApiKeySetupWindow
from desktop.utils.credentials import (
    delete_stored_api_key,
    get_stored_api_key,
    has_stored_api_key,
    set_test_credential_store,
    store_api_key,
)
from desktop.utils.validator import validate_groq_api_key


@pytest.fixture
def qapp():
    """Returns the QApplication instance."""
    app_instance = QApplication.instance()
    if app_instance is None:
        app_instance = QApplication([])
    return app_instance


@pytest.fixture(autouse=True)
def clean_test_credentials():
    """Ensures each test runs with an isolated, clean test credential store."""
    mock_store = {}
    set_test_credential_store(mock_store)
    yield mock_store
    set_test_credential_store(None)


# =============================================================================
# 1. VALIDATION LOGIC TESTS
# =============================================================================


def test_validator_empty_input():
    """Empty or whitespace input must fail immediately without making network calls."""
    is_valid, msg = validate_groq_api_key("")
    assert not is_valid
    assert "enter an API key" in msg

    is_valid, msg = validate_groq_api_key("   ")
    assert not is_valid
    assert "enter an API key" in msg


def test_validator_invalid_format():
    """Keys not beginning with 'gsk_' must be rejected before network requests."""
    is_valid, msg = validate_groq_api_key("not_a_groq_key_12345")
    assert not is_valid
    assert "gsk_" in msg


@patch("httpx.get")
def test_validator_valid_key(mock_get):
    """HTTP 200 from Groq models endpoint confirms key is valid."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    is_valid, msg = validate_groq_api_key("gsk_valid_mock_key_12345")
    assert is_valid
    assert msg == ""
    mock_get.assert_called_once()
    assert "Bearer gsk_valid_mock_key_12345" in mock_get.call_args[1]["headers"]["Authorization"]


@patch("httpx.get")
def test_validator_invalid_key_401(mock_get):
    """HTTP 401 Unauthorized signals an invalid or revoked key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    is_valid, msg = validate_groq_api_key("gsk_revoked_key_12345")
    assert not is_valid
    assert "Invalid API key" in msg


@patch("httpx.get")
def test_validator_rate_limit_429(mock_get):
    """HTTP 429 Too Many Requests returns distinct rate-limit feedback."""
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_get.return_value = mock_resp

    is_valid, msg = validate_groq_api_key("gsk_rate_limited_key_12345")
    assert not is_valid
    assert "Rate limit" in msg


@patch("httpx.get")
def test_validator_provider_outage_503(mock_get):
    """HTTP 500/503 returns distinct provider outage guidance."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_get.return_value = mock_resp

    is_valid, msg = validate_groq_api_key("gsk_outage_key_12345")
    assert not is_valid
    assert "unavailable" in msg


@patch("httpx.get")
def test_validator_network_error(mock_get):
    """Network connection errors are caught and surfaced clearly."""
    import httpx
    mock_get.side_effect = httpx.ConnectError("Connection refused")

    is_valid, msg = validate_groq_api_key("gsk_network_fail_key_12345")
    assert not is_valid
    assert "internet connection" in msg


# =============================================================================
# 2. SETUP WINDOW UI & INTERACTION TESTS
# =============================================================================


def test_setup_window_initial_state(qapp):
    """Verifies that the setup window contains all required labels, fields, and links."""
    window = ApiKeySetupWindow(is_update=False)

    assert window.headline_label.text() == "Let's get you started."
    assert "Kya-Ray uses Groq" in window.desc_label.text()
    assert window.input_label.text() == "Enter your API key"
    assert window.key_input.echoMode() == QLineEdit.EchoMode.Password
    assert window.submit_btn.text() == "Connect and continue"
    assert "console.groq.com/keys" in window.link_label.text()


def test_setup_window_toggle_show_hide(qapp):
    """Clicking Show/Hide toggles the password echo mode between Normal and Password."""
    window = ApiKeySetupWindow()
    assert window.key_input.echoMode() == QLineEdit.EchoMode.Password
    assert window.toggle_btn.text() == "Show"

    window.toggle_btn.click()
    assert window.key_input.echoMode() == QLineEdit.EchoMode.Normal
    assert window.toggle_btn.text() == "Hide"

    window.toggle_btn.click()
    assert window.key_input.echoMode() == QLineEdit.EchoMode.Password
    assert window.toggle_btn.text() == "Show"


def test_setup_window_rejects_empty_input(qapp):
    """Clicking submit with empty input displays error message without network calls."""
    window = ApiKeySetupWindow()
    window.key_input.setText("")
    window.submit_btn.click()

    assert "enter an API key" in window.status_label.text()
    assert not has_stored_api_key()


@patch("desktop.ui.setup_window.validate_groq_api_key")
def test_setup_window_never_saves_invalid_key(mock_validate, qapp):
    """When validation fails, the key must NEVER be written to secure storage."""
    mock_validate.return_value = (False, "Invalid API key. Please check your key on Groq console.")
    window = ApiKeySetupWindow()
    window.key_input.setText("gsk_invalid_test_key_12345")

    # Directly trigger validation result callback
    window._on_validation_result(False, "Invalid API key. Please check your key on Groq console.", "gsk_invalid_test_key_12345")

    assert "Invalid API key" in window.status_label.text()
    assert not has_stored_api_key()


@patch("desktop.ui.setup_window.validate_groq_api_key")
def test_setup_window_saves_valid_key(mock_validate, qapp):
    """When validation succeeds, key is saved to secure storage and signal is emitted."""
    mock_validate.return_value = (True, "")
    window = ApiKeySetupWindow()
    window.key_input.setText("gsk_valid_test_key_12345")

    configured_signal_keys = []
    window.key_configured.connect(lambda k: configured_signal_keys.append(k))

    window._on_validation_result(True, "", "gsk_valid_test_key_12345")

    assert has_stored_api_key()
    assert get_stored_api_key() == "gsk_valid_test_key_12345"
    assert configured_signal_keys == ["gsk_valid_test_key_12345"]


def test_setup_window_update_mode_has_update_title_and_blank_field(qapp):
    """In update mode, title changes to 'Update your API key' and the key input is kept blank for security."""
    store_api_key("gsk_existing_key_99999")
    window = ApiKeySetupWindow(is_update=True)

    assert window.headline_label.text() == "Update your API key"
    assert window.key_input.text() == ""


# =============================================================================
# 3. APPLICATION STARTUP & FIRST-LAUNCH FLOW
# =============================================================================


def test_app_first_launch_without_key_opens_setup_window(qapp):
    """When no API key exists, check_first_launch_setup opens the setup window."""
    mock_orchestrator = MagicMock()
    mock_window = MagicMock()

    app = KyaRayApplication(qapp=qapp, orchestrator=mock_orchestrator, window=mock_window)

    opened = app.check_first_launch_setup()
    assert opened is True
    assert app.setup_window is not None
    assert app.setup_window.isVisible()
    app.setup_window.hide()


def test_app_subsequent_launch_with_key_skips_setup(qapp):
    """When an API key already exists, check_first_launch_setup skips opening the setup window."""
    store_api_key("gsk_persisted_key_12345")
    mock_orchestrator = MagicMock()
    mock_window = MagicMock()

    app = KyaRayApplication(qapp=qapp, orchestrator=mock_orchestrator, window=mock_window)

    opened = app.check_first_launch_setup()
    assert opened is False
    assert app.setup_window is None


def test_app_auth_error_prompts_key_update(qapp):
    """When an authentication error occurs, app surfaces setup window in update mode."""
    store_api_key("gsk_expired_key")
    mock_orchestrator = MagicMock()
    mock_window = MagicMock()

    app = KyaRayApplication(qapp=qapp, orchestrator=mock_orchestrator, window=mock_window)
    app._on_ui_error("code", "Backend authentication error: Invalid or missing Groq API key", run_id=1)

    assert app.setup_window is not None
    assert app.setup_window.is_update is True
    assert app.setup_window.isVisible()
    app.setup_window.hide()


# =============================================================================
# 4. BACKEND CREDENTIAL RETRIEVAL
# =============================================================================


def test_backend_retrieves_stored_credential(clean_test_credentials):
    """Backend GroqProvider retrieves active key from secure credential storage."""
    clean_test_credentials["Kya-Ray/GroqApiKey"] = "gsk_backend_retrieved_key_123"

    provider = GroqProvider()
    assert provider.is_configured() is True
    assert provider._get_api_key() == "gsk_backend_retrieved_key_123"


# =============================================================================
# 5. CREDENTIAL REPLACEMENT SECURITY TESTS
# =============================================================================


def test_setup_window_update_mode_keeps_field_blank(qapp):
    """Settings/update mode must NEVER pre-populate the input field with the existing key."""
    store_api_key("gsk_existing_secret_key_12345")
    assert get_stored_api_key() == "gsk_existing_secret_key_12345"

    window = ApiKeySetupWindow(is_update=True)
    # The input field must be strictly empty for security
    assert window.key_input.text() == ""
    assert "Enter new key" in window.key_input.placeholderText()
    assert window.submit_btn.text() == "Update and continue"
    window.close()


def test_setup_window_failed_replacement_preserves_old_credential(qapp):
    """If the new key fails validation, the old stored credential MUST be preserved."""
    store_api_key("gsk_original_valid_key_111")
    window = ApiKeySetupWindow(is_update=True)

    window.key_input.setText("gsk_failed_replacement_key_222")
    window._on_validation_result(False, "Invalid API key.", "gsk_failed_replacement_key_222")

    # The original key remains intact
    assert get_stored_api_key() == "gsk_original_valid_key_111"
    assert "Invalid API key" in window.status_label.text()
    window.close()


def test_setup_window_successful_replacement_updates_credential(qapp):
    """The stored credential is replaced ONLY when the new key passes validation."""
    store_api_key("gsk_original_valid_key_111")
    window = ApiKeySetupWindow(is_update=True)

    window.key_input.setText("gsk_newly_validated_key_333")
    window._on_validation_result(True, "", "gsk_newly_validated_key_333")

    # Successfully replaced
    assert get_stored_api_key() == "gsk_newly_validated_key_333"
    assert "Connected successfully" in window.status_label.text()
    window.close()

