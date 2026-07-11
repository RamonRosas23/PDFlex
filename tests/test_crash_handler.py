from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import crash_handler as ch


def _reset_crash_handler_state() -> None:
    ch._CRASH_IN_PROGRESS = False
    ch._SESSION_STARTED = False
    ch._SESSION_FILE = None


def test_save_log_uses_persistent_crash_log_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PDFLEX_CRASH_LOG_DIR", str(tmp_path / "logs"))

    path = ch._save_log("diagnostic report")

    assert path is not None
    assert path.parent == tmp_path / "logs"
    assert path.read_text(encoding="utf-8") == "diagnostic report"


def test_session_sentinel_marks_running_crashed_and_clean(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PDFLEX_CRASH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PDFLEX_CRASH_LOG_DIR", str(tmp_path / "logs"))
    _reset_crash_handler_state()

    native_log = tmp_path / "logs" / "native.log"
    crash_log = tmp_path / "logs" / "crash.txt"
    ch._mark_session_running(native_fault_log=native_log)

    session_file = tmp_path / "state" / "session_state.json"
    running = json.loads(session_file.read_text(encoding="utf-8"))
    assert running["status"] == "running"
    assert running["native_fault_log"] == str(native_log)

    ch._mark_session_crashed(crash_log)
    crashed = json.loads(session_file.read_text(encoding="utf-8"))
    assert crashed["status"] == "crashed"
    assert crashed["last_log"] == str(crash_log)

    ch._CRASH_IN_PROGRESS = False
    ch._mark_session_clean()
    assert not session_file.exists()


def test_nonfatal_handle_crash_writes_log_and_resets_guard(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PDFLEX_CRASH_LOG_DIR", str(tmp_path / "logs"))
    _reset_crash_handler_state()

    try:
        raise RuntimeError("background boom")
    except RuntimeError:
        ch.handle_crash(*sys.exc_info(), context="unit-test", fatal=False)

    logs = list((tmp_path / "logs").glob("crash_*.txt"))
    assert len(logs) == 1
    text = logs[0].read_text(encoding="utf-8")
    assert "background boom" in text
    assert "Contexto: unit-test" in text
    assert ch._CRASH_IN_PROGRESS is False
