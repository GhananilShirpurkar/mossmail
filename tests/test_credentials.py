import json
import logging
import stat

import httpx
import pytest

from mossmail.credentials import (
    CredentialStore,
    InsecureStorageError,
    validate_gemini_key,
)


class MockKeyring:
    def __init__(self, priority=5, fail_on_write=False):
        self.priority = priority
        self.fail_on_write = fail_on_write
        self.vault = {}

    def get_password(self, service, username):
        return self.vault.get((service, username))

    def set_password(self, service, username, password):
        if self.fail_on_write:
            from keyring.errors import KeyringError

            raise KeyringError("Keyring unavailable")
        self.vault[(service, username)] = password

    def delete_password(self, service, username):
        self.vault.pop((service, username), None)


class DummyFailKeyring:
    priority = 0

    def get_password(self, service, username):
        return None

    def set_password(self, service, username, password):
        from keyring.errors import NoKeyringError

        raise NoKeyringError("No keyring")

    def delete_password(self, service, username):
        pass


def test_keyring_success_store_and_retrieve(tmp_path):
    mock_kr = MockKeyring(priority=5)
    store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    assert store.is_keyring_usable() is True
    medium = store.set_secret("gemini_api_key", "sk-test-12345")
    assert medium == "keyring"
    assert store.get_secret("gemini_api_key") == "sk-test-12345"
    assert store.get_storage_type("gemini_api_key") == "keyring"

    # Fallback file was not created because keyring worked
    assert not (tmp_path / "creds.json").exists()

    # Delete secret
    store.delete_secret("gemini_api_key")
    assert store.get_secret("gemini_api_key") is None


def test_empty_secret_rejected(tmp_path):
    mock_kr = MockKeyring()
    store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)
    with pytest.raises(ValueError, match="Secret cannot be empty"):
        store.set_secret("gemini_api_key", "   ")


def test_insecure_keyring_refuses_without_explicit_consent(tmp_path):
    mock_kr = DummyFailKeyring()
    store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    assert store.is_keyring_usable() is False
    with pytest.raises(InsecureStorageError, match="Explicit user consent is required"):
        store.set_secret("gemini_api_key", "sk-secret-key", allow_unencrypted_file=False)

    # File must not be created without consent
    assert not (tmp_path / "creds.json").exists()


def test_fallback_file_with_explicit_consent_and_permissions(tmp_path):
    mock_kr = DummyFailKeyring()
    creds_file = tmp_path / "nested" / "creds.json"
    store = CredentialStore(fallback_path=creds_file, keyring_backend=mock_kr)

    medium = store.set_secret("gemini_api_key", "sk-secret-key", allow_unencrypted_file=True)
    assert medium == "unencrypted_file"
    assert store.get_storage_type("gemini_api_key") == "unencrypted_file"
    assert store.get_secret("gemini_api_key") == "sk-secret-key"

    # Verify file mode is 0600 (owner read/write only)
    mode = creds_file.stat().st_mode
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0  # No group or other permissions
    assert mode & stat.S_IRUSR and mode & stat.S_IWUSR

    # Verify parent directory has restrictive permissions (0700)
    parent_mode = creds_file.parent.stat().st_mode
    assert parent_mode & (stat.S_IRWXO) == 0

    # Verify warning marker is present in json
    content = json.loads(creds_file.read_text(encoding="utf-8"))
    assert "_warning" in content
    assert "not provide encryption at rest" in content["_warning"]

    # Delete secret removes the file when empty
    store.delete_secret("gemini_api_key")
    assert not creds_file.exists()


def test_malformed_fallback_file_fails_safe(tmp_path):
    mock_kr = DummyFailKeyring()
    creds_file = tmp_path / "creds.json"
    creds_file.write_text("NOT VALID JSON! {{{", encoding="utf-8")

    store = CredentialStore(fallback_path=creds_file, keyring_backend=mock_kr)
    assert store.get_secret("gemini_api_key") is None


def test_env_var_fallback(tmp_path, monkeypatch):
    mock_kr = DummyFailKeyring()
    store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)
    monkeypatch.setenv("GEMINI_API_KEY", "env-secret-key")

    assert store.get_secret("gemini_api_key") == "env-secret-key"
    assert store.get_storage_type("gemini_api_key") == "env"


def test_validate_gemini_key_success():
    def mock_handler(request: httpx.Request):
        assert request.headers.get("x-goog-api-key") == "valid-key"
        assert "/models/gemini-3.8-flash" in str(request.url)
        return httpx.Response(200, json={"name": "models/gemini-3.8-flash"})

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    ok, msg = validate_gemini_key("valid-key", model="gemini-3.8-flash", client=client)
    assert ok is True
    assert "validated successfully" in msg


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_validate_gemini_key_unauthorized(status_code):
    def mock_handler(request: httpx.Request):
        return httpx.Response(status_code, json={"error": "unauthorized"})

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    ok, msg = validate_gemini_key("bad-key", client=client)
    assert ok is False
    assert "Invalid or unauthorized" in msg
    assert "bad-key" not in msg  # Secret is not leaked in error message


def test_validate_gemini_key_unsupported_model():
    ok, msg = validate_gemini_key("key", model="obsolete-model-3")
    assert ok is False
    assert "not in supported models" in msg


def test_validate_gemini_key_timeout(caplog):
    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("Timeout", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    with caplog.at_level(logging.INFO, logger="mossmail.credentials"):
        ok, msg = validate_gemini_key("my-secret-key-123", client=client)

    assert ok is False
    assert "timed out" in msg.casefold()
    assert "my-secret-key-123" not in caplog.text  # No key leakage in logs


def test_validate_gemini_key_network_error(caplog):
    def network_err_handler(request: httpx.Request):
        raise httpx.ConnectError("Connection failed", request=request)

    client = httpx.Client(transport=httpx.MockTransport(network_err_handler))
    with caplog.at_level(logging.INFO, logger="mossmail.credentials"):
        ok, msg = validate_gemini_key("my-secret-key-456", client=client)

    assert ok is False
    assert "network error" in msg.casefold()
    assert "my-secret-key-456" not in caplog.text


def test_prune_unencrypted_fallback_when_saving_to_keyring(tmp_path):
    creds_file = tmp_path / "creds.json"
    dummy_kr = DummyFailKeyring()
    # 1. Initially saved to unencrypted fallback file
    store_file = CredentialStore(fallback_path=creds_file, keyring_backend=dummy_kr)
    store_file.set_secret("gemini_api_key", "old-secret", allow_unencrypted_file=True)
    assert creds_file.exists()

    # 2. Later, working keyring becomes available
    working_kr = MockKeyring(priority=5)
    store_keyring = CredentialStore(fallback_path=creds_file, keyring_backend=working_kr)
    medium = store_keyring.set_secret("gemini_api_key", "new-secret")

    assert medium == "keyring"
    assert store_keyring.get_secret("gemini_api_key") == "new-secret"
    # Unencrypted copy must be pruned from disk
    assert not creds_file.exists()


def test_broken_keyring_fails_safe(tmp_path):
    class BrokenKeyring:
        @property
        def priority(self):
            raise RuntimeError("D-Bus initialization error")

    store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=BrokenKeyring())
    assert store.is_keyring_usable() is False


def test_validate_gemini_key_rejects_deprecated_or_gated_models():
    # gemini-2.0 and 1.5 families are shut down; 2.5 is gated/uncertain
    for model in (
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "unknown-model",
    ):
        ok, msg = validate_gemini_key("key", model=model)
        assert ok is False
        assert "not in supported models" in msg


def test_keyring_write_failure_does_not_prune_fallback_file(tmp_path):
    creds_file = tmp_path / "creds.json"
    dummy_kr = DummyFailKeyring()
    # 1. Existing credential in fallback file
    store = CredentialStore(fallback_path=creds_file, keyring_backend=dummy_kr)
    store.set_secret("gemini_api_key", "existing-secret", allow_unencrypted_file=True)
    assert creds_file.exists()

    # 2. Keyring backend fails on write
    failing_kr = MockKeyring(priority=5, fail_on_write=True)
    store_fail = CredentialStore(fallback_path=creds_file, keyring_backend=failing_kr)

    with pytest.raises(InsecureStorageError):
        store_fail.set_secret("gemini_api_key", "new-attempt", allow_unencrypted_file=False)

    # The existing fallback file must NOT be pruned or corrupted
    assert creds_file.exists()
    assert store.get_secret("gemini_api_key") == "existing-secret"


def test_keyring_read_failure_falls_back_to_file(tmp_path):
    class KeyringReadFail:
        priority = 5

        def get_password(self, service, username):
            raise RuntimeError("Keyring locked or unavailable")

    creds_file = tmp_path / "creds.json"
    dummy_kr = DummyFailKeyring()
    store_init = CredentialStore(fallback_path=creds_file, keyring_backend=dummy_kr)
    store_init.set_secret("gemini_api_key", "file-secret", allow_unencrypted_file=True)

    store_read_fail = CredentialStore(fallback_path=creds_file, keyring_backend=KeyringReadFail())
    # Should catch read failure safely and read from fallback file
    assert store_read_fail.get_secret("gemini_api_key") == "file-secret"


def test_deletion_when_credentials_in_both_stores(tmp_path):
    creds_file = tmp_path / "creds.json"
    # Pre-populate fallback file directly
    creds_file.write_text('{"gemini_api_key": "in-file"}', encoding="utf-8")
    mock_kr = MockKeyring(priority=5)
    mock_kr.set_password("mossmail", "gemini_api_key", "in-keyring")

    store = CredentialStore(fallback_path=creds_file, keyring_backend=mock_kr)
    store.delete_secret("gemini_api_key")

    assert mock_kr.get_password("mossmail", "gemini_api_key") is None
    assert not creds_file.exists()


def test_env_var_precedence_overridden_by_keyring_and_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-secret")
    creds_file = tmp_path / "creds.json"
    dummy_kr = DummyFailKeyring()

    # 1. Fallback file takes precedence over env var when keyring is unusable
    store_file = CredentialStore(fallback_path=creds_file, keyring_backend=dummy_kr)
    store_file.set_secret("gemini_api_key", "file-secret", allow_unencrypted_file=True)
    assert store_file.get_secret("gemini_api_key") == "file-secret"
    assert store_file.get_storage_type("gemini_api_key") == "unencrypted_file"

    # 2. Keyring takes precedence over both fallback file and env var
    mock_kr = MockKeyring(priority=5)
    mock_kr.set_password("mossmail", "gemini_api_key", "keyring-secret")

    store_keyring = CredentialStore(fallback_path=creds_file, keyring_backend=mock_kr)
    assert store_keyring.get_secret("gemini_api_key") == "keyring-secret"
    assert store_keyring.get_storage_type("gemini_api_key") == "keyring"


def test_failed_keyring_removal_is_not_silent(tmp_path):
    from mossmail.credentials import CredentialRemovalError

    class LockedKeyring(MockKeyring):
        def delete_password(self, service, username):
            raise RuntimeError("sensitive-backend-detail")

    kr = LockedKeyring()
    store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=kr)
    store.set_secret("gemini_api_key", "private-key")
    with pytest.raises(CredentialRemovalError) as error:
        store.delete_secret("gemini_api_key")
    assert "private-key" not in str(error.value)
    assert "sensitive-backend-detail" not in str(error.value)
    assert store.get_secret("gemini_api_key") == "private-key"
