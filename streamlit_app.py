"""Public landing page: never access shared private state or credentials."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("app.py")), init_globals={"HOSTED_PREVIEW": True})
