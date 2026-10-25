"""Community Cloud entrypoint: synthetic, session-isolated, no local inference calls."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), init_globals={"HOSTED_DEMO": True})
