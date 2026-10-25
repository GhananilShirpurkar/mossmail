# Streamlit Community Cloud

Deploy `streamlit_app.py` from `GhananilShirpurkar/mossmail`, branch `main`, with Python 3.13 in Advanced settings. No secrets are required. The root `requirements.txt` installs the runtime dependencies. Keep the local-only `app.py` entrypoint for personal use.

The cloud entrypoint uses only the bundled synthetic messages. Each browser session gets its own temporary SQLite database, so visitors cannot change each other's inbox. Session state is disposable and is not durable cloud storage. It bypasses Ollama entirely and labels summaries as demo excerpts. The real local Gemma and separate Temporal worker remain available when running locally.

Streamlit's developer toolbar, Deploy control, and options menu are hidden by `client.toolbarMode="minimal"` and narrowly scoped CSS. The sidebar toggle and MossMail's own actions remain usable.

The README's original screenshots and video document the initial local Gemma demonstration. They may show Streamlit toolbar elements removed in this update.
