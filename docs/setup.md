# First-run setup

Start `streamlit run app.py --server.address 127.0.0.1` from the repository with the virtual environment active. Setup is optional and dismissible. **Skip for now** and **Close setup** persist dismissal; **Settings → Reopen setup** restores it without touching messages or credentials. **Set up now** opens integration configuration; **Finish setup** leaves it even if you skipped integrations.

## Gmail Desktop OAuth

Use your own Google Cloud project. Enable Gmail API, configure an OAuth consent screen and test users where applicable, and create a Desktop app OAuth client. Enter its client ID and issued secret in Settings. Existing secrets are not prefilled. Save configuration now or connect immediately.

Connection opens Google's consent page and waits up to 90 seconds for a callback on a dynamically chosen loopback port. This flow requires the browser and application on the same machine. State and PKCE are checked before exchanging the code. Only the exact Gmail read-only scope is accepted. A callback alone does not mean connection succeeded; check MossMail for the final result.

After connecting, synchronize manually. Each sync imports at most 20 recent inbox messages; duplicates retain local decisions. A successful empty result is distinct from a failed request. Partial imports remain local, and errors request retry. Expired access or denied permission requires reconnecting; network failures require checking connectivity. Disconnect preserves imported messages.

Gmail status means credentials are present until a sync validates access. Google testing-mode refresh tokens may expire; account/project restrictions and OAuth verification requirements must be checked with Google for your deployment. This application has no public multi-user OAuth hosting flow.

## AI and privacy

Gemini is optional. A saved API key is validated using a model metadata request, without email. Select a model your account supports. Local Ollama is also optional; run its service and install your chosen model separately. Provider preference persists. Inference happens only after **Generate summary**. Missing models, credentials, failed requests, and malformed responses display real original-message excerpts with an explanation, not AI success.

Only bounded subject/reply text enters the Gemini prompt; that text can itself contain sensitive data. AI recommendations cannot execute actions or override policy. Deterministic triage remains available offline.

## Storage and later changes

Credentials use the OS keyring where available. The UI requires explicit consent before falling back to an unencrypted mode-0600 credential file; no consent is inferred from dismissal or setup completion. Keyring failure with no consent leaves the operation unsuccessful. Model preferences stored through the credential store follow the same consent rule.

Set `MOSSMAIL_DB` to change the SQLite location; `MOSSMAIL_CREDS_FILE` changes only the fallback credential-file location. Keyring credentials use the existing `mossmail` service namespace. Messages and settings survive restart. Keep backups protected because SQLite message bodies are unencrypted. Existing prototype data is retained rather than silently deleted.

Reconfigure in Settings at any time. Environment credentials must be changed/unset externally and the app restarted. File/keyring credential removal and Gmail disconnect never delete the inbox database. Remote token revocation is best effort; revoke MossMail in Google account permissions if needed.
