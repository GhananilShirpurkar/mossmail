# Deployment boundary

Run MossMail as a single-user local app, bound to loopback. `app.py` uses persisted local state and never seeds fictional messages. `streamlit_app.py` is a public landing page with local run instructions: it never opens credentials, databases, or integrations.

The old Community Cloud sandbox and synthetic session behavior are retired in this source version. Historical hosted screenshots and videos do not describe current behavior. This repository has no per-user authentication, credential namespace, or database tenancy. Do not deploy this entrypoint as a public shared service with personal credentials. Desktop OAuth also requires a browser on the same machine as the loopback listener.

See [first-run setup](setup.md) and the README for supported local configuration.
