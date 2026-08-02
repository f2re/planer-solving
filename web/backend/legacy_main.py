"""Deprecated import path retained for one compatibility cycle.

The former monolithic application lived here. Runtime construction now belongs
in :mod:`web.backend.app_factory`; no routes or mutable globals are defined in
this module.
"""
from web.backend.app_factory import create_app
from web.backend.main import app

__all__ = ["app", "create_app"]
