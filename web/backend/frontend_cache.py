"""Cache policy for the unversioned frontend entrypoint and ES modules."""
from __future__ import annotations

from fastapi import FastAPI, Request


def install_frontend_cache_policy(app: FastAPI) -> None:
    """Prevent mixed frontend versions after an offline update.

    Frontend module names are stable between releases. Revalidating HTML and
    assets avoids a browser combining a new index.html with stale JavaScript,
    while conditional requests still keep normal reloads inexpensive.
    """

    @app.middleware("http")
    async def frontend_cache_policy(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in {"/", "/index.html"} or path.endswith("/index.html"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
