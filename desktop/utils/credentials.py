"""
desktop/utils/credentials.py - Secure Credential Storage for Kya-Ray.

Stores and retrieves the Groq API key using the Windows Credential Manager
(advapi32.dll: CredWriteW, CredReadW, CredDeleteW).

Security Properties:
- Credentials are encrypted using the Windows Data Protection architecture
  bound to the active Windows user profile.
- Credentials persist across reboots without writing plaintext keys to disk.
- Zero plaintext .env required for production operation.
- Isolated per Windows user.
- Provides mockable storage fallback for headless testing and non-Windows environments.
"""

import ctypes
import os
import sys
from typing import Optional

# Windows Credential Manager Constants
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_TARGET_NAME = "Kya-Ray/GroqApiKey"
CRED_USERNAME = "Kya-Ray Desktop"

# In-memory mock storage (for automated test environments or when explicitly enabled)
_test_credential_store: Optional[dict] = None


def set_test_credential_store(store: Optional[dict]) -> None:
    """Configures or clears an in-memory test credential dictionary for mocking."""
    global _test_credential_store
    _test_credential_store = store


def is_windows() -> bool:
    """Checks if operating system is Windows."""
    return sys.platform == "win32" or os.name == "nt"


if is_windows():
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]


def store_api_key(api_key: str, target_name: str = CRED_TARGET_NAME) -> bool:
    """
    Securely saves the Groq API key into Windows Credential Manager.
    Returns True upon success, False otherwise.
    """
    cleaned = (api_key or "").strip()
    if not cleaned:
        return False

    global _test_credential_store
    if _test_credential_store is not None:
        _test_credential_store[target_name] = cleaned
        return True

    if not is_windows():
        return False

    try:
        advapi32 = ctypes.windll.advapi32
        secret_bytes = cleaned.encode("utf-8")
        blob = (ctypes.c_byte * len(secret_bytes))(*secret_bytes)

        cred = CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target_name
        cred.Comment = "Kya-Ray Desktop AI Assistant Groq API Key"
        cred.CredentialBlobSize = len(secret_bytes)
        cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = CRED_USERNAME

        success = advapi32.CredWriteW(ctypes.byref(cred), 0)
        return bool(success)
    except Exception:
        return False


def get_stored_api_key(target_name: str = CRED_TARGET_NAME) -> Optional[str]:
    """
    Retrieves the Groq API key from Windows Credential Manager.
    Falls back to environment variable or .env if no credential is in Credential Manager.
    Returns None if not found or empty.
    """
    global _test_credential_store
    if _test_credential_store is not None:
        key = _test_credential_store.get(target_name)
        return key.strip() if (key and key.strip()) else None

    if is_windows():
        try:
            advapi32 = ctypes.windll.advapi32
            pcred = ctypes.POINTER(CREDENTIALW)()
            res = advapi32.CredReadW(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred))
            if res and pcred:
                raw_bytes = ctypes.string_at(
                    pcred.contents.CredentialBlob,
                    pcred.contents.CredentialBlobSize,
                )
                secret = raw_bytes.decode("utf-8", errors="ignore").strip()
                advapi32.CredFree(pcred)
                if secret:
                    return secret
        except Exception:
            pass

    # Secondary fallback for development environments (.env or os.environ)
    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    if env_key:
        return env_key

    return None


def delete_stored_api_key(target_name: str = CRED_TARGET_NAME) -> bool:
    """
    Removes the stored Groq API key from Windows Credential Manager.
    Returns True if successfully removed or was not present.
    """
    global _test_credential_store
    if _test_credential_store is not None:
        _test_credential_store.pop(target_name, None)
        return True

    if not is_windows():
        return True

    try:
        advapi32 = ctypes.windll.advapi32
        res = advapi32.CredDeleteW(target_name, CRED_TYPE_GENERIC, 0)
        return bool(res)
    except Exception:
        return False


def has_stored_api_key(target_name: str = CRED_TARGET_NAME) -> bool:
    """Returns True if a non-empty API key is available via Credential Manager or fallback."""
    key = get_stored_api_key(target_name=target_name)
    return bool(key and key.strip())
