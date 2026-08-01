"""Application entrypoint with workspace extensions over the stable schedule core."""
from pathlib import Path
import sys

# Execute the proven schedule core in this module so existing deployments and
# tests can still override BASE_DIR, INPUT_DIR and related settings.
_core = Path(__file__).with_name("legacy_main.py")
exec(compile(_core.read_text(encoding="utf-8"), str(_core), "exec"), globals())

from web.backend.workspace_api import install_workspace_api  # noqa: E402

app = install_workspace_api(app, sys.modules[__name__])
