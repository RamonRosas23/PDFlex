"""Tests for PipelineWindow contextual action zone in navbar."""
from __future__ import annotations
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _make_ctx():
    from shell.context import ShellContext
    from shell.tray import PdfTray
    from shell.word_to_pdf import WordToPdfConverter
    return ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None)


def test_action_zone_hidden_by_default(app):
    """_action_zone starts hidden when no step actions registered."""
    from ui.compresor.window import CompresorWindow
    w = CompresorWindow(_make_ctx())
    try:
        w._switch_section(0)
        assert not w._action_zone.isVisible()
    finally:
        w.deleteLater(); app.processEvents()


def test_action_zone_visible_on_procesar_step(app):
    """_action_zone is visible and nav_next hidden on the Procesar step."""
    from ui.compresor.window import CompresorWindow
    w = CompresorWindow(_make_ctx())
    try:
        procesar_idx = next(i for i, s in enumerate(w.SECTIONS) if s[1] == "Procesar")
        w._switch_section(procesar_idx)
        assert w._action_zone.isVisible()
        assert not w._nav_next_btn.isVisible()
    finally:
        w.deleteLater(); app.processEvents()


def test_action_zone_visible_on_resultados_step(app):
    """_action_zone is visible on Resultados step."""
    from ui.compresor.window import CompresorWindow
    w = CompresorWindow(_make_ctx())
    try:
        resultados_idx = next(i for i, s in enumerate(w.SECTIONS) if s[1] == "Resultados")
        w._switch_section(resultados_idx)
        assert w._action_zone.isVisible()
    finally:
        w.deleteLater(); app.processEvents()


def test_nav_next_shows_on_non_action_step(app):
    """On a step without actions, nav_next button is visible and shows step name."""
    from ui.compresor.window import CompresorWindow
    w = CompresorWindow(_make_ctx())
    try:
        w._switch_section(0)  # Documentos — no actions
        assert not w._action_zone.isVisible()
        assert w._nav_next_btn.isVisible()
        assert "Siguiente:" in w._nav_next_btn.text()
    finally:
        w.deleteLater(); app.processEvents()


def test_get_step_actions_returns_run_cancel_on_procesar(app):
    """_get_step_actions returns [_cancel_btn, _run_btn] for Procesar step."""
    from ui.compresor.window import CompresorWindow
    w = CompresorWindow(_make_ctx())
    try:
        procesar_idx = next(i for i, s in enumerate(w.SECTIONS) if s[1] == "Procesar")
        actions = w._get_step_actions(procesar_idx)
        assert w._cancel_btn in actions
        assert w._run_btn in actions
    finally:
        w.deleteLater(); app.processEvents()


def test_get_step_actions_returns_send_restart_on_resultados(app):
    """_get_step_actions returns [_send_btn, _restart_btn] for Resultados step."""
    from ui.compresor.window import CompresorWindow
    w = CompresorWindow(_make_ctx())
    try:
        resultados_idx = next(i for i, s in enumerate(w.SECTIONS) if s[1] == "Resultados")
        actions = w._get_step_actions(resultados_idx)
        assert w._restart_btn in actions
    finally:
        w.deleteLater(); app.processEvents()
