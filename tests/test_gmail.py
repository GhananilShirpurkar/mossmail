"""Tests for GmailProvider, OAuth PKCE flow, and RFC 822 parsing."""

import base64
from urllib.parse import unquote

import httpx
import pytest

from mossmail.credentials import CredentialStore
from mossmail.mailbox.gmail import (
    GmailProvider,
    OAuthError,
    RateLimitError,
    ScopeViolationError,
    TokenRevokedError,
    build_authorization_url,
    extract_code_from_redirect,
    generate_pkce_pair,
)
from mossmail.models import Message


class MockKeyring:
    def __init__(self, priority=5):
        self.priority = priority
        self.vault = {}

    def get_password(self, service, username):
        return self.vault.get((service, username))

    def set_password(self, service, username, password):
        self.vault[(service, username)] = password

    def delete_password(self, service, username):
        self.vault.pop((service, username), None)


def test_pkce_generation():
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43
    assert "=" not in challenge  # S256 challenge must be unpadded base64url


def test_build_authorization_url_strict_scope():
    url = build_authorization_url(
        client_id="test-client-id.apps.googleusercontent.com",
        redirect_uri="http://127.0.0.1:8080/",
        code_challenge="test-challenge",
        state="csrf-state-123",
    )
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=test-client-id" in url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly" in url
    assert "code_challenge=test-challenge" in url
    assert "code_challenge_method=S256" in url
    assert "state=csrf-state-123" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_build_authorization_url_rejects_broader_scopes():
    with pytest.raises(ScopeViolationError, match="only permits"):
        build_authorization_url(
            client_id="test-client-id",
            redirect_uri="http://127.0.0.1:8080/",
            code_challenge="challenge",
            state="state",
            scope="https://mail.google.com/",
        )

    with pytest.raises(ScopeViolationError, match="only permits"):
        build_authorization_url(
            client_id="test-client-id",
            redirect_uri="http://127.0.0.1:8080/",
            code_challenge="challenge",
            state="state",
            scope="https://www.googleapis.com/auth/gmail.modify",
        )


def test_extract_code_from_redirect():
    # 1. Full redirect URL with matching state
    url = "http://127.0.0.1:8080/?code=4/0Atest_code&state=expected_state"
    code = extract_code_from_redirect(url, expected_state="expected_state")
    assert code == "4/0Atest_code"

    # 2. State mismatch triggers OAuthError
    with pytest.raises(OAuthError, match="state parameter mismatch"):
        extract_code_from_redirect(url, expected_state="wrong_state")

    # 3. Access denied error in redirect URL
    denied_url = "http://127.0.0.1:8080/?error=access_denied&state=expected_state"
    with pytest.raises(OAuthError, match="authorization denied: access_denied"):
        extract_code_from_redirect(denied_url, expected_state="expected_state")

    # 4. Bare code string fallback
    assert extract_code_from_redirect("4/0Araw_code_only") == "4/0Araw_code_only"

    # 5. Empty input
    with pytest.raises(OAuthError, match="cannot be empty"):
        extract_code_from_redirect("   ")


def test_token_exchange_success(tmp_path):
    mock_kr = MockKeyring()
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert "oauth2.googleapis.com/token" in str(request.url)
        data = dict(httpx.QueryParams(request.read().decode("utf-8")))
        assert data["client_id"] == "test-client-id"
        assert data["code"] == "auth-code-123"
        assert data["code_verifier"] == "test-verifier"
        assert data["grant_type"] == "authorization_code"

        return httpx.Response(
            200,
            json={
                "access_token": "ya29.test_access_token",
                "refresh_token": "1//test_refresh_token",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(
        client_id="test-client-id",
        credential_store=cred_store,
        client=client,
    )

    res = provider.exchange_code_for_tokens(
        code="auth-code-123",
        code_verifier="test-verifier",
        redirect_uri="http://127.0.0.1:8080/",
    )
    assert res["status"] == "authenticated"
    assert provider.is_connected() is True
    assert cred_store.get_secret("gmail_refresh_token") == "1//test_refresh_token"
    assert provider.get_valid_access_token() == "ya29.test_access_token"


def test_token_exchange_rejects_broader_scope_from_server(tmp_path):
    mock_kr = MockKeyring()
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.token",
                "refresh_token": "1//refresh",
                "expires_in": 3600,
                "scope": "https://mail.google.com/ https://www.googleapis.com/auth/gmail.readonly",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(
        client_id="test-client-id",
        credential_store=cred_store,
        client=client,
    )

    with pytest.raises(ScopeViolationError, match="Excessive OAuth scope"):
        provider.exchange_code_for_tokens(
            code="code", code_verifier="verifier", redirect_uri="http://127.0.0.1:8080/"
        )


def test_token_refresh_success(tmp_path):
    mock_kr = MockKeyring()
    mock_kr.set_password("mossmail", "gmail_client_id", "test-client-id")
    mock_kr.set_password("mossmail", "gmail_refresh_token", "1//valid-refresh")
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    def handler(request: httpx.Request):
        assert "oauth2.googleapis.com/token" in str(request.url)
        data = dict(httpx.QueryParams(request.read().decode("utf-8")))
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "1//valid-refresh"

        return httpx.Response(
            200,
            json={
                "access_token": "ya29.new_refreshed_token",
                "expires_in": 3600,
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credential_store=cred_store, client=client)

    token = provider.get_valid_access_token()
    assert token == "ya29.new_refreshed_token"


def test_token_refresh_revoked_error(tmp_path):
    mock_kr = MockKeyring()
    mock_kr.set_password("mossmail", "gmail_client_id", "test-client-id")
    mock_kr.set_password("mossmail", "gmail_refresh_token", "1//revoked-refresh")
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    def handler(request: httpx.Request):
        return httpx.Response(
            400,
            headers={"content-type": "application/json"},
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credential_store=cred_store, client=client)

    with pytest.raises(TokenRevokedError, match="revoked or expired"):
        provider.get_valid_access_token()


def test_list_messages_and_pagination(tmp_path):
    mock_kr = MockKeyring()
    mock_kr.set_password("mossmail", "gmail_client_id", "test-client-id")
    mock_kr.set_password("mossmail", "gmail_refresh_token", "1//refresh")
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    def handler(request: httpx.Request):
        if "oauth2.googleapis.com/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        assert "gmail.googleapis.com/gmail/v1/users/me/messages" in str(request.url)
        assert request.headers.get("authorization") == "Bearer ya29.token"
        assert "q=in%3Ainbox" in str(request.url)

        return httpx.Response(
            200,
            json={
                "messages": [
                    {"id": "msg_001", "threadId": "thread_001"},
                    {"id": "msg_002", "threadId": "thread_002"},
                ],
                "nextPageToken": "page_token_abc",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credential_store=cred_store, client=client)

    items, next_page = provider.list_messages(limit=10)
    assert len(items) == 2
    assert items[0].id == "msg_001"
    assert items[0].thread_id == "thread_001"
    assert items[1].id == "msg_002"
    assert next_page == "page_token_abc"


def test_list_messages_rate_limit(tmp_path):
    mock_kr = MockKeyring()
    mock_kr.set_password("mossmail", "gmail_client_id", "test-client-id")
    mock_kr.set_password("mossmail", "gmail_refresh_token", "1//refresh")
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    def handler(request: httpx.Request):
        if "oauth2.googleapis.com/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        return httpx.Response(429, json={"error": "Rate limit exceeded"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credential_store=cred_store, client=client)

    with pytest.raises(RateLimitError, match="rate limit reached"):
        provider.list_messages(limit=10)


def test_get_message_raw_and_parsed(tmp_path):
    mock_kr = MockKeyring()
    mock_kr.set_password("mossmail", "gmail_client_id", "test-client-id")
    mock_kr.set_password("mossmail", "gmail_refresh_token", "1//refresh")
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    # Build raw RFC 822 email bytes
    raw_rfc822 = (
        b"From: Alice <alice@example.com>\r\n"
        b"To: Bob <bob@example.com>\r\n"
        b"Subject: Meeting Notes & Action Items\r\n"
        b"Date: Sun, 25 Oct 2026 12:00:00 +0000\r\n"
        b"Message-ID: <msg123@example.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Here are the meeting notes. Let me know what you think.\r\n"
    )
    raw_b64 = base64.urlsafe_b64encode(raw_rfc822).decode("ascii")

    def handler(request: httpx.Request):
        if "oauth2.googleapis.com/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        if "format=metadata" in str(request.url):
            return httpx.Response(
                200,
                json={"id": "msg_001", "threadId": "thread_abc", "internalDate": "1792929600000"},
            )
        if "format=raw" in str(request.url):
            return httpx.Response(200, json={"id": "msg_001", "raw": raw_b64})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credential_store=cred_store, client=client)

    msg: Message = provider.get_message("msg_001")
    assert msg.id == "msg_001"
    assert msg.thread_id == "thread_abc"
    assert msg.sender == "alice@example.com"
    assert msg.sender_name == "Alice"
    assert msg.subject == "Meeting Notes & Action Items"
    assert "Here are the meeting notes" in msg.body
    assert msg.has_attachments is False
    assert msg.parse_uncertain is False


def test_disconnect_clears_stored_secrets(tmp_path):
    mock_kr = MockKeyring()
    mock_kr.set_password("mossmail", "gmail_client_id", "my-client-id")
    mock_kr.set_password("mossmail", "gmail_refresh_token", "1//refresh-secret")
    cred_store = CredentialStore(fallback_path=tmp_path / "creds.json", keyring_backend=mock_kr)

    revoked_tokens = []

    def handler(request: httpx.Request):
        if "oauth2.googleapis.com/revoke" in str(request.url):
            revoked_tokens.append(request.read().decode("utf-8"))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credential_store=cred_store, client=client)
    assert provider.is_connected() is True

    provider.disconnect()

    assert provider.is_connected() is False
    assert cred_store.get_secret("gmail_refresh_token") is None
    assert cred_store.get_secret("gmail_client_id") is None
    assert len(revoked_tokens) == 1
    assert "1//refresh-secret" in unquote(revoked_tokens[0])


def test_gmail_provider_has_no_mutation_methods():
    """Verify that GmailProvider contains no write, send, delete, or modify methods."""
    forbidden = {"send", "draft", "delete", "trash", "modify", "batch_modify", "update"}
    for attr in dir(GmailProvider):
        assert attr.lower() not in forbidden, f"Forbidden mutation method '{attr}' found!"
