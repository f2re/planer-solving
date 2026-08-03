"""Keep the administrator signed in when resetting their own password."""
from __future__ import annotations

import os
import re

from fastapi import FastAPI, Request

from web.backend.app_context import ApplicationContext
from web.backend.auth import SESSION_COOKIE

RESET_PATH = re.compile(r"^/api/admin/users/([^/]+)/reset-password$")


def install_password_reset_session(app: FastAPI, context: ApplicationContext) -> None:
    @app.middleware("http")
    async def restore_self_session_after_reset(request: Request, call_next):
        response = await call_next(request)
        match = RESET_PATH.fullmatch(request.url.path)
        actor = getattr(request.state, "actor", None)
        if (
            request.method == "POST"
            and match
            and response.status_code < 400
            and actor
            and str(actor.get("id")) == match.group(1)
        ):
            token = context.workspace_repository.create_session(match.group(1))
            response.set_cookie(
                SESSION_COOKIE,
                token,
                httponly=True,
                samesite="lax",
                secure=os.environ.get("PLANNER_COOKIE_SECURE", "0") == "1",
                path="/",
                max_age=14 * 24 * 60 * 60,
            )
        return response
