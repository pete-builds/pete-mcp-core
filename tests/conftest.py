"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


@pytest.fixture(autouse=True)
def _isolate_session_reaper_patch():
    """Keep the session-reaper monkeypatch from leaking between tests.

    ``enable_session_reaper`` patches a class on the installed SDK, so any test
    that calls ``run_server`` would otherwise leave every later test running
    against a patched manager. Restore the pristine ``__init__`` around each
    test, unwrapping first in case a previous test already installed the patch.
    """
    current = StreamableHTTPSessionManager.__init__
    pristine = getattr(current, "__wrapped__", current)
    StreamableHTTPSessionManager.__init__ = pristine
    try:
        yield
    finally:
        StreamableHTTPSessionManager.__init__ = pristine
