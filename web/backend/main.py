"""ASGI entrypoint for Planner Solving."""
from web.backend.app_factory import create_app

app = create_app()

__all__ = ["app", "create_app"]
