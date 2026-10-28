import json
import logging
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger("mossmail.credentials")

SERVICE_NAME = "mossmail"
DEFAULT_FALLBACK_FILE = Path(".local/credentials.json")
SUPPORTED_GEMINI_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
)


class InsecureStorageError(Exception):
    """Raised when secure OS keyring is unavailable and consent for fallback was not granted."""


class CredentialRemovalError(Exception):
    """Credential cleanup could not be verified; never include backend details."""


class CredentialStore:
    def __init__(
        self,
        fallback_path: Path | str | None = None,
        keyring_backend: Any | None = None,
    ):
        self.fallback_path = Path(
            fallback_path or os.getenv("MOSSMAIL_CREDS_FILE", DEFAULT_FALLBACK_FILE)
        )
        self._custom_keyring = keyring_backend

    @property
    def keyring(self):
        return self._custom_keyring or keyring.get_keyring()

    def is_keyring_usable(self) -> bool:
        """Check if a secure OS keyring backend is available and has non-zero priority."""
        try:
            kr = self.keyring
            name = kr.__class__.__name__
            if "fail" in name.lower() or "null" in name.lower():
                return False
            priority = getattr(kr, "priority", 0)
            return priority > 0
        except Exception:
            return False

    def get_secret(self, key_name: str) -> str | None:
        """Retrieve a secret, checking keyring first, then consented fallback file, then env."""
        # 1. Try OS keyring
        if self.is_keyring_usable():
            try:
                val = self.keyring.get_password(SERVICE_NAME, key_name)
                if val:
                    return val
            except (KeyringError, Exception):
                logger.info("keyring_read_unavailable")

        # 2. Try consented fallback file if it exists
        if self.fallback_path.exists():
            data = self._read_fallback_file()
            val = data.get(key_name)
            if val:
                return str(val)

        # 3. Environment variable fallback (useful for CI / scripting)
        env_mapping = {
            "gemini_api_key": "GEMINI_API_KEY",
            "gemini_model": "GEMINI_MODEL",
            "gmail_client_id": "GMAIL_CLIENT_ID",
            "gmail_client_secret": "GMAIL_CLIENT_SECRET",
            "gmail_refresh_token": "GMAIL_REFRESH_TOKEN",
        }
        env_var = env_mapping.get(key_name)
        if env_var and os.getenv(env_var):
            return os.getenv(env_var)

        return None

    def set_secret(
        self,
        key_name: str,
        secret_value: str,
        allow_unencrypted_file: bool = False,
    ) -> str:
        """Store a secret.

        If a secure OS keyring is available, saves there.
        If unavailable, refuses to save unless allow_unencrypted_file is True,
        in which case writes to the fallback file with mode 0600.
        Returns storage medium description: 'keyring' or 'unencrypted_file'.
        """
        secret_clean = secret_value.strip()
        if not secret_clean:
            raise ValueError("Secret cannot be empty")

        # Attempt to store in keyring
        if self.is_keyring_usable():
            try:
                self.keyring.set_password(SERVICE_NAME, key_name, secret_clean)
                self._prune_fallback_key(key_name)
                return "keyring"
            except (KeyringError, Exception):
                logger.info("keyring_write_failed")

        # Keyring unavailable or failed
        if not allow_unencrypted_file:
            raise InsecureStorageError(
                "A secure OS keyring is not available on this system. Refusing to save "
                "credentials. Explicit user consent is required to store credentials in an "
                f"unencrypted local file ({self.fallback_path}) with 0600 permissions. "
                "Note: filesystem permissions restrict access to your user account but do NOT "
                "provide encryption at rest."
            )

        # Write to fallback file with 0600 permissions
        self._write_fallback_file(key_name, secret_clean)
        return "unencrypted_file"

    def delete_secret(self, key_name: str) -> None:
        """Delete a secret from both the OS keyring and the fallback file."""
        # 1. Delete from keyring
        if self.is_keyring_usable():
            try:
                self.keyring.delete_password(SERVICE_NAME, key_name)
            except PasswordDeleteError:
                # A missing password is already removed, but verify that outcome.
                try:
                    if self.keyring.get_password(SERVICE_NAME, key_name):
                        raise CredentialRemovalError("Credential removal could not be verified.")
                except CredentialRemovalError:
                    raise
                except Exception:
                    raise CredentialRemovalError(
                        "Credential removal could not be verified."
                    ) from None
            except Exception:
                raise CredentialRemovalError(
                    "Keyring credential removal failed. Unlock the keyring and retry."
                ) from None

        # 2. Delete from fallback file
        if self.fallback_path.exists():
            data = self._read_fallback_file()
            if key_name in data:
                del data[key_name]
                # If no secrets remain besides warnings/metadata, remove file
                remaining_secrets = {k: v for k, v in data.items() if not k.startswith("_")}
                if remaining_secrets:
                    self._save_raw_fallback(data)
                else:
                    self._unlink_fallback()

    def get_storage_type(self, key_name: str) -> str | None:
        """Return where the secret is stored: 'keyring', 'unencrypted_file', 'env', or None."""
        if self.is_keyring_usable():
            try:
                if self.keyring.get_password(SERVICE_NAME, key_name):
                    return "keyring"
            except Exception:
                logger.info("keyring_status_unavailable")
        if self.fallback_path.exists():
            data = self._read_fallback_file()
            if key_name in data:
                return "unencrypted_file"
        env_mapping = {
            "gemini_api_key": "GEMINI_API_KEY",
            "gemini_model": "GEMINI_MODEL",
            "gmail_client_id": "GMAIL_CLIENT_ID",
            "gmail_client_secret": "GMAIL_CLIENT_SECRET",
            "gmail_refresh_token": "GMAIL_REFRESH_TOKEN",
        }
        env_var = env_mapping.get(key_name)
        if env_var and os.getenv(env_var):
            return "env"
        return None

    def _read_fallback_file(self) -> dict[str, Any]:
        try:
            content = self.fallback_path.read_text(encoding="utf-8")
            return json.loads(content)
        except (json.JSONDecodeError, OSError):
            logger.info("fallback_credential_read_error")
            return {}

    def _write_fallback_file(self, key_name: str, value: str) -> None:
        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure parent directory has 0700 permissions
        try:
            os.chmod(self.fallback_path.parent, 0o700)
        except OSError:
            pass

        data = self._read_fallback_file() if self.fallback_path.exists() else {}
        data["_warning"] = (
            "UNENCRYPTED CREDENTIAL FILE. Restrictive permissions (0600) applied. "
            "Permissions restrict access to your account but do not provide encryption at rest."
        )
        data[key_name] = value
        self._save_raw_fallback(data)

    def _prune_fallback_key(self, key_name: str) -> None:
        if self.fallback_path.exists():
            data = self._read_fallback_file()
            if key_name in data:
                del data[key_name]
                remaining_secrets = {k: v for k, v in data.items() if not k.startswith("_")}
                if remaining_secrets:
                    self._save_raw_fallback(data)
                else:
                    self._unlink_fallback()

    def _save_raw_fallback(self, data: dict[str, Any]) -> None:
        content = json.dumps(data, indent=2)
        # Write to temporary file in the same directory, fsync, and atomically replace
        temp_path = self.fallback_path.with_name(f"{self.fallback_path.name}.tmp.{os.getpid()}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(temp_path, flags, 0o600)
        try:
            with open(fd, "w", encoding="utf-8", closefd=False) as f:
                f.write(content)
                f.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, self.fallback_path)

    def _unlink_fallback(self) -> None:
        if self.fallback_path.exists():
            self.fallback_path.unlink()


def validate_gemini_key(
    api_key: str,
    model: str = "gemini-3.8-flash",
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> tuple[bool, str]:
    """Validate a Gemini API key using a minimal metadata request that sends no email content."""
    clean_key = api_key.strip()
    if not clean_key:
        return False, "API key cannot be empty."

    clean_model = model[7:] if model.startswith("models/") else model
    if clean_model not in SUPPORTED_GEMINI_MODELS:
        models_str = ", ".join(SUPPORTED_GEMINI_MODELS)
        return False, f"Model '{clean_model}' is not in supported models: {models_str}."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}"
    headers = {
        "x-goog-api-key": clean_key,
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as own:
            c = client or own
            response = c.get(url, headers=headers)
            if response.status_code == 200:
                return True, f"Key validated successfully for {clean_model}."
            if response.status_code in (400, 401, 403):
                return False, "Invalid or unauthorized Gemini API key."
            if response.status_code == 404:
                return False, f"Model '{clean_model}' not found on Google Gemini API."
            return False, f"Google Gemini API returned status code {response.status_code}."
    except httpx.TimeoutException:
        logger.info("gemini_validation_timeout")
        return False, "Connection to Google Gemini API timed out."
    except httpx.HTTPError:
        logger.info("gemini_validation_network_error")
        return False, "Network error while connecting to Google Gemini API."
    except Exception:
        logger.info("gemini_validation_unexpected_error")
        return False, "Unexpected error during Gemini key validation."
