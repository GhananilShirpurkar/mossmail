"""Read-only Gmail provider with OAuth 2.0 PKCE and loopback redirection."""

import base64
import hashlib
import logging
import secrets
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from mossmail.credentials import CredentialStore
from mossmail.email_parser import parse_email_to_message
from mossmail.mailbox.base import MailboxProvider, MessageMetadata
from mossmail.models import Message

logger = logging.getLogger("mossmail.mailbox.gmail")

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class OAuthError(Exception):
    """Base exception for OAuth failures."""


class TokenRevokedError(OAuthError):
    """Raised when refresh token is revoked, expired, or invalid."""


class AuthenticationRequiredError(OAuthError):
    """Raised when Gmail is not authenticated or refresh token is missing."""


class ScopeViolationError(OAuthError):
    """Raised when an attempt is made to request non-read-only scopes."""


class GmailAPIError(Exception):
    """Base exception for Gmail API request failures."""


class RateLimitError(GmailAPIError):
    """Raised when Gmail API returns rate limit (HTTP 429)."""


def generate_pkce_pair() -> tuple[str, str]:
    """Generate high-entropy PKCE code_verifier and S256 code_challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scope: str = GMAIL_READONLY_SCOPE,
) -> str:
    """Construct Google OAuth 2.0 authorization URL for desktop app with PKCE."""
    if scope != GMAIL_READONLY_SCOPE:
        raise ScopeViolationError(
            f"MossMail only permits '{GMAIL_READONLY_SCOPE}'; rejected scope '{scope}'."
        )

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


class _LoopbackCallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler to capture authorization code from Google redirect."""

    def log_message(self, format, *args):
        # Suppress default server log to prevent leaking query params
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        params = parse_qs(parsed.query)

        server: _LoopbackServer = self.server  # type: ignore
        server.query_params = params

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if "error" in params:
            err = params["error"][0]
            body = (
                "<html><body style='font-family:sans-serif;text-align:center;padding:50px;'>"
                f"<h2 style='color:#c0392b;'>Gmail Authorization Denied</h2>"
                f"<p>Reason: {err}</p><p>You can close this tab and return to MossMail.</p>"
                "</body></html>"
            )
        else:
            body = (
                "<html><body style='font-family:sans-serif;text-align:center;padding:50px;'>"
                "<h2 style='color:#27ae60;'>Gmail Connected Successfully</h2>"
                "<p>MossMail has received read-only authorization. "
                "You can close this tab and return to the application.</p>"
                "</body></html>"
            )
        self.wfile.write(body.encode())


def extract_code_from_redirect(redirect_text: str, expected_state: str | None = None) -> str:
    """Extract authorization code from a redirect URL or raw authorization code.

    Kept for backwards compatibility and standalone redirect URL parsing.
    """
    cleaned = redirect_text.strip()
    if not cleaned:
        raise OAuthError("Redirect URL or authorization code cannot be empty.")
    if "code=" in cleaned or cleaned.startswith("http"):
        parsed = urlparse(cleaned)
        params = parse_qs(parsed.query)
        if "error" in params:
            err = params["error"][0]
            raise OAuthError(f"Google OAuth authorization denied: {err}")
        codes = params.get("code")
        if not codes:
            raise OAuthError("No authorization code found in the redirect URL.")
        if expected_state and params.get("state") != [expected_state]:
            raise OAuthError("OAuth state parameter mismatch (possible CSRF attempt).")
        return codes[0]
    return cleaned


class _LoopbackServer(HTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.query_params: dict[str, list[str]] = {}


def find_available_loopback_port(preferred_port: int = 8080) -> int:
    """Find an available port on 127.0.0.1, trying preferred_port, preferred_port+1, or dynamic."""
    for candidate in (preferred_port, preferred_port + 1, 0):
        try:
            with HTTPServer(("127.0.0.1", candidate), BaseHTTPRequestHandler) as s:
                return int(s.server_address[1])
        except OSError:
            continue
    return preferred_port


def run_loopback_receiver(
    port: int = 8080, timeout_seconds: float = 60.0
) -> dict[str, list[str]]:
    """Run local loopback server to receive the OAuth redirect code.

    Binds strictly to 127.0.0.1.
    """
    server = _LoopbackServer(("127.0.0.1", port), _LoopbackCallbackHandler)
    server.timeout = 1.0

    start_time = time.time()
    try:
        while time.time() - start_time < timeout_seconds:
            server.handle_request()
            if server.query_params:
                break
    finally:
        server.server_close()

    return server.query_params


class GmailProvider(MailboxProvider):
    """Read-only Gmail mailbox provider using official OAuth 2.0 PKCE desktop flow."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        credential_store: CredentialStore | None = None,
        client: httpx.Client | None = None,
    ):
        self.cred_store = credential_store or CredentialStore()
        self.client_id = client_id or self.cred_store.get_secret("gmail_client_id") or ""
        self.client_secret = (
            client_secret or self.cred_store.get_secret("gmail_client_secret") or ""
        )
        self._cached_access_token: str | None = None
        self._access_token_expires_at: float = 0.0
        self._custom_client = client

    def start_auth_flow(self, port: int = 8080) -> tuple[str, str, str, str]:
        """Initiate OAuth PKCE flow. Returns (auth_url, verifier, state, redirect_uri)."""
        if not self.client_id:
            raise AuthenticationRequiredError("Gmail Client ID is missing.")
        actual_port = find_available_loopback_port(port)
        redirect_uri = f"http://127.0.0.1:{actual_port}/"
        verifier, challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(32)
        auth_url = build_authorization_url(
            client_id=self.client_id,
            redirect_uri=redirect_uri,
            code_challenge=challenge,
            state=state,
        )
        return auth_url, verifier, state, redirect_uri

    def authenticate_via_loopback(
        self,
        port: int = 8080,
        timeout_seconds: float = 120.0,
        open_browser: bool = True,
        allow_unencrypted_fallback: bool = False,
        auth_info: tuple[str, str, str, str] | None = None,
    ) -> dict[str, str]:
        """Perform automated Google OAuth 2.0 PKCE loopback authentication."""
        if auth_info:
            auth_url, verifier, state, redirect_uri = auth_info
        else:
            auth_url, verifier, state, redirect_uri = self.start_auth_flow(port=port)

        if open_browser:
            import webbrowser

            try:
                webbrowser.open(auth_url)
            except Exception:
                logger.info("browser_launch_failed")

        actual_port = int(urlparse(redirect_uri).port or port)
        params = run_loopback_receiver(port=actual_port, timeout_seconds=timeout_seconds)

        if not params:
            raise OAuthError(
                "Authentication timed out or loopback receiver was cancelled before callback."
            )

        if "error" in params:
            err = params["error"][0]
            raise OAuthError(f"Google OAuth authorization denied: {err}")

        codes = params.get("code")
        if not codes:
            raise OAuthError("No authorization code received from Google OAuth callback.")

        # CSRF Protection: Validate state parameter
        received_states = params.get("state")
        if not received_states or received_states[0] != state:
            raise OAuthError("OAuth state parameter mismatch (CSRF protection failed).")

        code = codes[0]
        return self.exchange_code_for_tokens(
            code=code,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            allow_unencrypted_fallback=allow_unencrypted_fallback,
        )

    def is_connected(self) -> bool:
        """Return True if Gmail refresh token is present in the credential store."""
        token = self.cred_store.get_secret("gmail_refresh_token")
        return bool(token and self.client_id)

    def exchange_code_for_tokens(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        allow_unencrypted_fallback: bool = False,
    ) -> dict[str, str]:
        """Exchange authorization code and PKCE verifier for OAuth tokens."""
        if not self.client_id:
            raise AuthenticationRequiredError("Gmail Client ID is missing.")

        payload = {
            "client_id": self.client_id,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret

        try:
            with httpx.Client(timeout=15.0, trust_env=False) as own:
                c = self._custom_client or own
                resp = c.post(GOOGLE_TOKEN_URL, data=payload)
                if resp.status_code != 200:
                    logger.info("gmail_token_exchange_failed", extra={"status": resp.status_code})
                    raise OAuthError(
                        f"Failed to exchange OAuth code for tokens (HTTP {resp.status_code})."
                    )
                data = resp.json()
        except httpx.HTTPError as e:
            logger.info("gmail_token_exchange_network_error")
            raise OAuthError("Network error during OAuth token exchange.") from e

        # Validate that granted scope strictly matches or is within read-only scope
        granted_scope = data.get("scope", "")
        if "mail.google.com" in granted_scope or "gmail.modify" in granted_scope:
            raise ScopeViolationError(
                "Excessive OAuth scope granted by server. "
                "MossMail strictly rejects modification scopes."
            )

        refresh_token = data.get("refresh_token")
        if refresh_token:
            self.cred_store.set_secret(
                "gmail_refresh_token",
                refresh_token,
                allow_unencrypted_file=allow_unencrypted_fallback,
            )
        if self.client_id:
            self.cred_store.set_secret(
                "gmail_client_id",
                self.client_id,
                allow_unencrypted_file=allow_unencrypted_fallback,
            )
        if self.client_secret:
            self.cred_store.set_secret(
                "gmail_client_secret",
                self.client_secret,
                allow_unencrypted_file=allow_unencrypted_fallback,
            )

        access_token = data.get("access_token", "")
        expires_in = float(data.get("expires_in", 3600))
        self._cached_access_token = access_token
        self._access_token_expires_at = time.time() + max(0.0, expires_in - 60)

        return {"status": "authenticated"}

    def get_valid_access_token(self) -> str:
        """Return a valid cached access token or refresh it via Google OAuth endpoint."""
        now = time.time()
        if self._cached_access_token and now < self._access_token_expires_at:
            return self._cached_access_token

        refresh_token = self.cred_store.get_secret("gmail_refresh_token")
        if not refresh_token:
            raise AuthenticationRequiredError(
                "Gmail is not connected. Please connect your Gmail account in Settings."
            )

        client_id = self.client_id or self.cred_store.get_secret("gmail_client_id")
        if not client_id:
            raise AuthenticationRequiredError("Gmail Client ID is missing.")

        payload = {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        client_secret = self.client_secret or self.cred_store.get_secret("gmail_client_secret")
        if client_secret:
            payload["client_secret"] = client_secret

        try:
            with httpx.Client(timeout=15.0, trust_env=False) as own:
                c = self._custom_client or own
                resp = c.post(GOOGLE_TOKEN_URL, data=payload)
                if resp.status_code == 400:
                    is_json = resp.headers.get("content-type") == "application/json"
                    err_json = resp.json() if is_json else {}
                    if err_json.get("error") == "invalid_grant":
                        logger.info("gmail_token_revoked")
                        raise TokenRevokedError(
                            "Gmail refresh token has been revoked or expired. "
                            "Please reconnect in Settings."
                        )
                    raise OAuthError("OAuth token refresh rejected by Google.")
                if resp.status_code != 200:
                    logger.info("gmail_token_refresh_failed", extra={"status": resp.status_code})
                    raise OAuthError(f"OAuth token refresh failed with HTTP {resp.status_code}.")

                data = resp.json()
        except httpx.HTTPError as e:
            logger.info("gmail_token_refresh_network_error")
            raise OAuthError("Network error during OAuth token refresh.") from e

        access_token = data.get("access_token")
        if not access_token:
            raise OAuthError("Token refresh response did not contain an access token.")

        expires_in = float(data.get("expires_in", 3600))
        self._cached_access_token = access_token
        self._access_token_expires_at = now + max(0.0, expires_in - 60)
        return access_token

    def list_messages(
        self, limit: int = 20, page_token: str | None = None
    ) -> tuple[list[MessageMetadata], str | None]:
        """List messages in the inbox (read-only). Returns (metadata_list, next_page_token)."""
        token = self.get_valid_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        params: dict[str, str] = {
            "maxResults": str(min(max(1, limit), 100)),
            "q": "in:inbox",
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            with httpx.Client(timeout=20.0, trust_env=False) as own:
                c = self._custom_client or own
                resp = c.get(f"{GMAIL_API_BASE}/messages", headers=headers, params=params)
                if resp.status_code == 429:
                    raise RateLimitError(
                        "Gmail API rate limit reached. Please wait before retrying."
                    )
                if resp.status_code in (401, 403):
                    logger.info("gmail_list_unauthorized", extra={"status": resp.status_code})
                    raise AuthenticationRequiredError(
                        "Gmail access unauthorized or token expired."
                    )
                if resp.status_code != 200:
                    raise GmailAPIError(
                        f"Gmail API list messages failed with HTTP {resp.status_code}."
                    )
                data = resp.json()
        except httpx.HTTPError as e:
            logger.info("gmail_list_network_error")
            raise GmailAPIError("Network error connecting to Gmail API.") from e

        messages_raw = data.get("messages", [])
        next_page = data.get("nextPageToken")
        result: list[MessageMetadata] = []
        for item in messages_raw:
            msg_id = item.get("id")
            thread_id = item.get("threadId", msg_id)
            if msg_id:
                result.append(MessageMetadata(id=msg_id, thread_id=thread_id))
        return result, next_page

    def get_message_raw(self, provider_id: str) -> bytes:
        """Fetch raw RFC 822 message bytes from Gmail API (read-only)."""
        token = self.get_valid_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        params = {"format": "raw"}
        try:
            with httpx.Client(timeout=25.0, trust_env=False) as own:
                c = self._custom_client or own
                url = f"{GMAIL_API_BASE}/messages/{provider_id}"
                resp = c.get(url, headers=headers, params=params)
                if resp.status_code == 429:
                    raise RateLimitError("Gmail API rate limit reached.")
                if resp.status_code == 404:
                    raise GmailAPIError(f"Message '{provider_id}' not found in mailbox.")
                if resp.status_code in (401, 403):
                    raise AuthenticationRequiredError(
                        "Gmail access unauthorized or token expired."
                    )
                if resp.status_code != 200:
                    raise GmailAPIError(
                        f"Gmail API get message failed with HTTP {resp.status_code}."
                    )
                data = resp.json()
        except httpx.HTTPError as e:
            logger.info("gmail_get_raw_network_error")
            raise GmailAPIError("Network error fetching raw email from Gmail.") from e

        raw_b64 = data.get("raw", "")
        if not raw_b64:
            return b""
        # Pad base64url string if needed
        padding = 4 - (len(raw_b64) % 4)
        if padding != 4:
            raw_b64 += "=" * padding
        return base64.urlsafe_b64decode(raw_b64)

    def get_message(self, provider_id: str) -> Message:
        """Fetch raw bytes and parse into a domain Message object."""
        token = self.get_valid_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        # Fetch metadata format first for threadId and internalDate
        params = {"format": "metadata"}
        thread_id = None
        internal_date = None
        try:
            with httpx.Client(timeout=20.0, trust_env=False) as own:
                c = self._custom_client or own
                url = f"{GMAIL_API_BASE}/messages/{provider_id}"
                resp = c.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    meta = resp.json()
                    thread_id = meta.get("threadId")
                    raw_ms = meta.get("internalDate")
                    if raw_ms:
                        internal_date = datetime.fromtimestamp(int(raw_ms) / 1000, tz=UTC)
        except Exception:
            pass

        raw_bytes = self.get_message_raw(provider_id)
        return parse_email_to_message(
            raw_bytes,
            provider_id=provider_id,
            thread_id=thread_id or provider_id,
            internal_date=internal_date,
        )

    def disconnect(self) -> None:
        """Revoke refresh token (best effort) and clear credentials from store."""
        refresh_token = self.cred_store.get_secret("gmail_refresh_token")
        if refresh_token:
            try:
                with httpx.Client(timeout=10.0, trust_env=False) as own:
                    c = self._custom_client or own
                    c.post(GOOGLE_REVOKE_URL, data={"token": refresh_token})
            except Exception:
                pass

        self.cred_store.delete_secret("gmail_refresh_token")
        self.cred_store.delete_secret("gmail_client_id")
        self.cred_store.delete_secret("gmail_client_secret")
        self._cached_access_token = None
        self._access_token_expires_at = 0.0
