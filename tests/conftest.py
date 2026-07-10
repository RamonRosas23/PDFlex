"""Shared pytest lifecycle helpers for the Qt test suite."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def release_qt_clipboard_before_shutdown():
    """Release test-owned clipboard data before Qt tears down on Windows.

    PySide6 keeps the ``QMimeData`` object alive while the application owns the
    clipboard.  Explicit cleanup prevents Qt's platform clipboard from being
    destroyed after Python has already finalized related wrappers.
    """
    yield

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    app.clipboard().clear()
    app.processEvents()
