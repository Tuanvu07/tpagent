"""TPAgent web server: FastAPI REST + WebSocket + single-page UI. Run `python -m tpagent.server`."""
from .app import create_app
from .settings import Settings

__all__ = ["create_app", "Settings"]
