"""TDD — failing tests for ProcessStep refactor (Task 3).

These tests describe the POST-refactor contract where ProcessStep:
  - Removes _run_btn and _cancel_btn as internal widgets
  - Adds run_enabled_changed(bool) signal  (emitted by set_run_enabled)
  - Adds running_changed(bool) signal       (emitted by start/stop_processing_ui)

All 6 tests MUST fail against the current (pre-refactor) implementation.
Do NOT implement the feature until these tests are green.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def step(app):
    from ui.common.process_step import ProcessStep
    return ProcessStep(run_label="Procesar", show_output_dir=False)


# ── Test 1 ──────────────────────────────────────────────────────────────────

def test_process_step_has_no_run_button(step):
    """After refactor, ProcessStep must not have a _run_btn attribute."""
    assert not hasattr(step, "_run_btn"), (
        "_run_btn still exists on ProcessStep — button must be removed in the refactor"
    )


# ── Test 2 ──────────────────────────────────────────────────────────────────

def test_process_step_has_no_cancel_button(step):
    """After refactor, ProcessStep must not have a _cancel_btn attribute."""
    assert not hasattr(step, "_cancel_btn"), (
        "_cancel_btn still exists on ProcessStep — button must be removed in the refactor"
    )


# ── Test 3 ──────────────────────────────────────────────────────────────────

def test_run_enabled_changed_signal_exists(app):
    """ProcessStep must expose a run_enabled_changed(bool) signal."""
    from ui.common.process_step import ProcessStep
    assert hasattr(ProcessStep, "run_enabled_changed"), (
        "ProcessStep is missing the run_enabled_changed signal"
    )


# ── Test 4 ──────────────────────────────────────────────────────────────────

def test_running_changed_signal_exists(app):
    """ProcessStep must expose a running_changed(bool) signal."""
    from ui.common.process_step import ProcessStep
    assert hasattr(ProcessStep, "running_changed"), (
        "ProcessStep is missing the running_changed signal"
    )


# ── Test 5 ──────────────────────────────────────────────────────────────────

def test_set_run_enabled_emits_run_enabled_changed(step):
    """set_run_enabled() must emit run_enabled_changed with the given bool.

    Calls are made while NOT running so the signal fires immediately.
    """
    received: list[bool] = []
    step.run_enabled_changed.connect(received.append)

    step.set_run_enabled(True)
    assert received == [True], (
        f"Expected run_enabled_changed to emit True; got {received}"
    )

    step.set_run_enabled(False)
    assert received == [True, False], (
        f"Expected run_enabled_changed to emit False next; got {received}"
    )


# ── Test 6 ──────────────────────────────────────────────────────────────────

def test_start_stop_processing_ui_emit_running_changed(step):
    """start_processing_ui() emits running_changed(True).
    stop_processing_ui() emits running_changed(False) then run_enabled_changed(False).

    _run_enabled_requested defaults to False before any set_run_enabled call,
    so stop_processing_ui() should also emit run_enabled_changed(False).
    """
    running_values: list[bool] = []
    enabled_values: list[bool] = []

    step.running_changed.connect(running_values.append)
    step.run_enabled_changed.connect(enabled_values.append)

    step.start_processing_ui()
    assert running_values == [True], (
        f"Expected running_changed(True) after start_processing_ui; got {running_values}"
    )

    # Clear any initial emissions before checking stop behavior
    enabled_values.clear()

    step.stop_processing_ui()
    assert running_values == [True, False], (
        f"Expected running_changed(False) after stop_processing_ui; got {running_values}"
    )
    assert enabled_values == [False], (
        f"Expected run_enabled_changed(False) after stop_processing_ui; got {enabled_values}"
    )


# ── Test 7 ──────────────────────────────────────────────────────────────────

def test_set_run_enabled_while_running_defers_signal(app):
    """set_run_enabled while running defers emission until stop_processing_ui."""
    from ui.common.process_step import ProcessStep
    step = ProcessStep(run_label="Test", show_output_dir=False)
    enabled_values = []
    step.run_enabled_changed.connect(lambda v: enabled_values.append(v))
    try:
        step.start_processing_ui()           # running = True
        enabled_values.clear()               # clear any emissions from start
        step.set_run_enabled(True)           # should NOT emit yet (running)
        assert enabled_values == [], "run_enabled_changed must NOT emit while running"
        step.stop_processing_ui()            # NOW it should emit run_enabled_changed(True)
        assert True in enabled_values, "run_enabled_changed must emit on stop with requested value"
    finally:
        step.deleteLater()
        app.processEvents()


# ── Test 8 ──────────────────────────────────────────────────────────────────

def test_refresh_run_glow_method_removed(app):
    """_refresh_run_glow is fully removed from ProcessStep."""
    from ui.common.process_step import ProcessStep
    step = ProcessStep(run_label="Test", show_output_dir=False)
    try:
        assert not hasattr(step, "_refresh_run_glow"), (
            "_refresh_run_glow should be removed in the refactor"
        )
    finally:
        step.deleteLater()
        app.processEvents()
