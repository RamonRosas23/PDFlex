# Contextual Footer Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move action buttons (Ejecutar/Cancelar in Procesar step, Nueva sesión/SendToTool in Resultados step) out of step content and into PipelineWindow's `ToolNavBar` footer, making the scaffold the single owner of all action UX.

**Architecture:** `PipelineWindow` gains an `_action_zone` widget in the navbar; the base `_get_step_actions(idx)` reads conventionally named attributes (`_run_btn`, `_cancel_btn`, `_restart_btn`, `_send_btn`) from SECTIONS name matching — no override needed per tool. `ProcessStep` loses its button row and gains `run_enabled_changed` / `running_changed` signals. Each tool window adds `_build_action_buttons()` that creates the four buttons, moves `_send_btn` creation here from the results section, and wires the ProcessStep signals.

**Tech Stack:** PyQt6, QWidget, QHBoxLayout, pyqtSignal

---

## File Structure

**Modified:**
- `ui/common/tool_scaffold.py` — `_build_navbar`, `_switch_section`, `_update_navbar`; new `_get_step_actions`, `_refresh_action_zone`
- `ui/common/process_step.py` — remove button row; add `run_enabled_changed` + `running_changed` signals; remove `run_requested` + `cancel_requested`
- `ui/compresor/window.py` — reference implementation
- `ui/unir/window.py`
- `ui/protector/window.py`
- `ui/marca_agua/window.py`
- `ui/extraer_imagenes/window.py`
- `ui/quitar_fondo/window.py`
- `ui/reparador/window.py`
- `ui/clasificador/window.py`
- `ui/comparador/window.py`
- `ui/formularios/window.py`
- `ui/imgs_a_pdf/window.py`
- `ui/redactor/window.py`
- `ui/separador/window.py`
- `ui/pdf_to_imgs/window.py`
- `ui/pdf_to_word/window.py`
- `ui/ocr/window.py` — no `_send_btn`
- `ui/organizador/window.py` — Procesar=1, Resultados=2
- `ui/word_a_pdf/window.py` — Procesar=1, Resultados=2
- `ui/membretado/window.py` — Procesar=3, Resultados=4
- `ui/firmador/window.py` — Procesar=4, Resultados=5
- `ui/foleador/window.py` — Procesar=4, Resultados=5

**Created:**
- `tests/test_scaffold_action_zone.py`

---

### Task 1: Write failing tests for scaffold action zone

**Files:**
- Create: `tests/test_scaffold_action_zone.py`

- [ ] **Step 1: Create the test file**

```python
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


class _FakePipeline:
    """Minimal subclass used in tests — assembled after scaffold exists."""


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
```

- [ ] **Step 2: Run tests to confirm they fail (CompresorWindow not yet updated)**

```
pytest tests/test_scaffold_action_zone.py -v
```

Expected: FAIL — `AttributeError: 'CompresorWindow' has no attribute '_action_zone'` or similar.

- [ ] **Step 3: Commit the test file**

```
git add tests/test_scaffold_action_zone.py
git commit -m "test(scaffold): failing tests for contextual action zone in navbar"
```

---

### Task 2: Implement scaffold action zone in PipelineWindow

**Files:**
- Modify: `ui/common/tool_scaffold.py`

- [ ] **Step 1: Add `_action_zone` to `_build_navbar`**

In `_build_navbar`, after `row.addStretch()` and before adding `_nav_next_btn`, insert:

```python
self._action_zone = QWidget()
_az_layout = QHBoxLayout(self._action_zone)
_az_layout.setContentsMargins(0, 0, 0, 0)
_az_layout.setSpacing(8)
self._action_zone.setVisible(False)
row.addWidget(self._action_zone)
```

Full updated `_build_navbar` body (replace existing):

```python
def _build_navbar(self) -> "QFrame":
    """Barra de navegación fija al pie del content area."""
    from ui.common.icons import set_button_icon

    navbar = QFrame()
    navbar.setObjectName("ToolNavBar")
    navbar.setFixedHeight(56)
    navbar.setStyleSheet(
        "QFrame#ToolNavBar {"
        f"background: {COLORS['bg']};"
        f"border-top: 1px solid {COLORS['border']};"
        "}"
    )

    row = QHBoxLayout(navbar)
    row.setContentsMargins(20, 0, 20, 0)
    row.setSpacing(12)

    self._nav_prev_btn = QPushButton("Anterior")
    self._nav_prev_btn.setProperty("class", "Ghost")
    self._nav_prev_btn.setFixedHeight(36)
    set_button_icon(self._nav_prev_btn, "arrow-left", color=COLORS["text_muted"])
    self._nav_prev_btn.clicked.connect(self._on_nav_prev)
    self._nav_prev_btn.setVisible(False)
    row.addWidget(self._nav_prev_btn)

    row.addStretch()

    # Zona de acciones contextuales por paso
    self._action_zone = QWidget()
    _az_layout = QHBoxLayout(self._action_zone)
    _az_layout.setContentsMargins(0, 0, 0, 0)
    _az_layout.setSpacing(8)
    self._action_zone.setVisible(False)
    row.addWidget(self._action_zone)

    self._nav_next_btn = QPushButton("Siguiente")
    self._nav_next_btn.setProperty("class", "Primary")
    self._nav_next_btn.setFixedHeight(36)
    set_button_icon(self._nav_next_btn, "arrow-right", color="#FFFFFF")
    self._nav_next_btn.clicked.connect(self._on_nav_next)
    self._nav_next_btn.setVisible(False)
    row.addWidget(self._nav_next_btn)

    return navbar
```

- [ ] **Step 2: Add `_get_step_actions` and `_refresh_action_zone` methods**

Add these two methods to `PipelineWindow`, just before `_on_nav_prev`:

```python
def _get_step_actions(self, idx: int) -> list:
    """Returns contextual navbar widgets for the given step index.

    Default reads SECTIONS step names and attribute convention:
      'Procesar'   → [_cancel_btn, _run_btn]  (if attrs exist)
      'Resultados' → [_send_btn, _restart_btn] (if attrs exist)
    Subclasses may override for custom behavior.
    """
    if not self.SECTIONS or idx >= len(self.SECTIONS):
        return []
    step_name = self.SECTIONS[idx][1]
    if step_name == "Procesar":
        actions = []
        if hasattr(self, "_cancel_btn"):
            actions.append(self._cancel_btn)
        if hasattr(self, "_run_btn"):
            actions.append(self._run_btn)
        return actions
    if step_name == "Resultados":
        actions = []
        if hasattr(self, "_send_btn"):
            actions.append(self._send_btn)
        if hasattr(self, "_restart_btn"):
            actions.append(self._restart_btn)
        return actions
    return []

def _refresh_action_zone(self, idx: int) -> None:
    """Swaps contextual action widgets into the navbar for the current step."""
    az_layout = self._action_zone.layout()
    while az_layout.count():
        item = az_layout.takeAt(0)
        if item.widget():
            item.widget().setParent(None)

    actions = self._get_step_actions(idx)
    for widget in actions:
        az_layout.addWidget(widget)

    has_actions = bool(actions)
    self._action_zone.setVisible(has_actions)
    if has_actions and hasattr(self, "_nav_next_btn"):
        self._nav_next_btn.setVisible(False)
```

- [ ] **Step 3: Update `_switch_section` call order**

Replace the last 4 lines of `_switch_section` (the block that calls `_sync_child_accents`, `_apply_primary_glows`, `_on_section_activated`, and `_update_navbar`) with:

```python
        self._sync_child_accents()
        self._on_section_activated(idx)
        if hasattr(self, "_nav_prev_btn"):
            self._update_navbar(idx)
        if hasattr(self, "_action_zone"):
            self._refresh_action_zone(idx)
        self._apply_primary_glows()
```

- [ ] **Step 4: Update `_update_navbar` — descriptive "Siguiente" text**

In `_update_navbar`, change:

```python
# OLD:
self._nav_next_btn.setText(next_name)

# NEW:
self._nav_next_btn.setText(f"Siguiente: {next_name}")
```

- [ ] **Step 5: Run existing tests to confirm scaffold changes don't break anything**

```
pytest tests/test_smoke_tools.py -v
```

Expected: all 21 smoke tests PASS (CompresorWindow etc. haven't changed yet so action_zone is empty on all steps — that's fine).

- [ ] **Step 6: Commit scaffold changes**

```
git add ui/common/tool_scaffold.py
git commit -m "feat(scaffold): action zone in navbar + _get_step_actions hook + descriptive Siguiente text"
```

---

### Task 3: Write failing tests for ProcessStep refactor

**Files:**
- Modify: `tests/test_scaffold_action_zone.py`

- [ ] **Step 1: Add ProcessStep signal tests to the test file**

Append to `tests/test_scaffold_action_zone.py`:

```python
def test_process_step_emits_run_enabled_changed(app):
    """ProcessStep.set_run_enabled emits run_enabled_changed signal."""
    from ui.common.process_step import ProcessStep
    step = ProcessStep()
    received = []
    step.run_enabled_changed.connect(lambda v: received.append(v))
    try:
        step.set_run_enabled(True)
        assert received == [True]
        step.set_run_enabled(False)
        assert received == [True, False]
    finally:
        step.deleteLater(); app.processEvents()


def test_process_step_emits_running_changed(app):
    """ProcessStep emits running_changed(True) on start, (False) on stop."""
    from ui.common.process_step import ProcessStep
    step = ProcessStep()
    step.set_run_enabled(True)
    received = []
    step.running_changed.connect(lambda v: received.append(v))
    try:
        step.start_processing_ui()
        assert True in received
        step.stop_processing_ui()
        assert False in received
    finally:
        step.deleteLater(); app.processEvents()


def test_process_step_has_no_run_or_cancel_button(app):
    """ProcessStep no longer contains _run_btn or _cancel_btn children."""
    from ui.common.process_step import ProcessStep
    step = ProcessStep()
    try:
        assert not hasattr(step, "_run_btn"), "ProcessStep should not have _run_btn"
        assert not hasattr(step, "_cancel_btn"), "ProcessStep should not have _cancel_btn"
    finally:
        step.deleteLater(); app.processEvents()
```

- [ ] **Step 2: Run new tests to confirm they fail**

```
pytest tests/test_scaffold_action_zone.py::test_process_step_emits_run_enabled_changed tests/test_scaffold_action_zone.py::test_process_step_emits_running_changed tests/test_scaffold_action_zone.py::test_process_step_has_no_run_or_cancel_button -v
```

Expected: FAIL — signals don't exist yet / buttons still exist.

- [ ] **Step 3: Commit failing tests**

```
git add tests/test_scaffold_action_zone.py
git commit -m "test(process-step): failing tests for new signals and button removal"
```

---

### Task 4: Implement ProcessStep refactor

**Files:**
- Modify: `ui/common/process_step.py`

- [ ] **Step 1: Add new signals to `ProcessStep`**

In `ProcessStep` class body, add two signals right after the existing `run_requested` / `cancel_requested`. **Do NOT delete the old signals yet** — tool windows still connect to them and smoke tests will fail if removed now. They will be deleted in Task 18 once all tool windows are updated.

```python
run_enabled_changed = pyqtSignal(bool)
running_changed     = pyqtSignal(bool)
# run_requested and cancel_requested remain for now — removed in Task 18
```

- [ ] **Step 2: Remove the button row from `_build()`**

In `_build()`, delete the entire button block at the bottom. It starts with `layout.addStretch(1)` and ends with `nav.addWidget(self._run_btn)`. Replace that entire final section with just:

```python
        layout.addStretch(1)
```

The deleted block was:
```python
        layout.addStretch(1)

        # ── Botones ───────────────────────────────────────────────────
        nav = QHBoxLayout()
        nav.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        nav.addWidget(self._cancel_btn)

        self._run_btn = QPushButton(self._run_label)
        self._run_btn.setProperty("class", "Primary")
        set_button_icon(self._run_btn, "play")
        self._run_btn.setMinimumWidth(200)
        self._run_btn.setMinimumHeight(38)
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self.run_requested)
        nav.addWidget(self._run_btn)

        layout.addLayout(nav)
```

- [ ] **Step 3: Update `set_run_enabled` to emit signal**

Replace the body of `set_run_enabled`:

```python
    def set_run_enabled(self, enabled: bool) -> None:
        """Emite run_enabled_changed para que la ventana controle el botón."""
        self._run_enabled_requested = enabled
        if not self._is_running:
            self.run_enabled_changed.emit(enabled)
```

- [ ] **Step 4: Update `start_processing_ui` to emit signal**

Replace the body of `start_processing_ui`:

```python
    def start_processing_ui(self) -> None:
        """Inicia shimmer y emite running_changed(True)."""
        if self._is_running:
            return
        self._is_running = True
        from ui.common.animations import AnimationHelper
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
        self._shimmer_timer = AnimationHelper.start_shimmer(self._prog_bar, self._accent)
        self.running_changed.emit(True)
```

- [ ] **Step 5: Update `stop_processing_ui` to emit signals**

Replace the body of `stop_processing_ui`:

```python
    def stop_processing_ui(self) -> None:
        """Detiene shimmer y emite running_changed(False) + run_enabled_changed."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._is_running = False
        self._apply_progress_accent()
        self.running_changed.emit(False)
        self.run_enabled_changed.emit(self._run_enabled_requested)
```

- [ ] **Step 6: Remove `_refresh_run_glow`**

Delete the entire `_refresh_run_glow` method and remove its two call sites inside `set_run_enabled`, `start_processing_ui`, and `stop_processing_ui` (those were already removed in steps 3-5). Also remove the call in `set_accent`:

In `set_accent`, change:

```python
    def set_accent(self, accent: str) -> None:
        self._accent = accent or COLORS["accent"]
        if not self._is_running:
            self._apply_progress_accent()
        # Remove: self._refresh_run_glow()
```

- [ ] **Step 7: Remove constructor initialization of `_run_label` if unused**

The `self._run_label = run_label` stored in `__init__` is now unused (no button displays it). Remove that line from `__init__` and the `run_label` parameter default from `__init__` signature — BUT keep the parameter for backward compat in case external code passes it; just don't store it:

```python
    def __init__(
        self,
        *,
        run_label: str = "Procesar",   # kept for API compat, no longer used internally
        settings_key: str = "",
        default_output: str = "",
        show_output_dir: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings_key = settings_key
        self._show_output_dir = show_output_dir
        self._initial_output = _load_output_dir(settings_key, default_output) if show_output_dir else ""
        self._accent = COLORS["accent"]
        self._is_running = False
        self._run_enabled_requested = False
        self._shimmer_timer = None
        self._build()
```

- [ ] **Step 8: Run ProcessStep tests**

```
pytest tests/test_scaffold_action_zone.py::test_process_step_emits_run_enabled_changed tests/test_scaffold_action_zone.py::test_process_step_emits_running_changed tests/test_scaffold_action_zone.py::test_process_step_has_no_run_or_cancel_button -v
```

Expected: all 3 PASS.

- [ ] **Step 9: Run smoke tests to confirm no breakage**

```
pytest tests/test_smoke_tools.py -v
```

Expected: all 21 PASS. The old `run_requested` / `cancel_requested` signals are still present (per Step 1), so tool window `__init__` calls that connect to them still work. The new signals are additional — no breakage.

- [ ] **Step 10: Commit ProcessStep refactor**

```
git add ui/common/process_step.py
git commit -m "feat(process-step): replace button row with run_enabled_changed/running_changed signals"
```

---

### Task 5: CompresorWindow — reference implementation

**Files:**
- Modify: `ui/compresor/window.py`
- Modify: `tests/test_compresor_window.py`

- [ ] **Step 1: Add test for button placement**

Append to `tests/test_compresor_window.py`:

```python
    def test_action_buttons_exist_and_go_to_navbar(self) -> None:
        window = CompresorWindow(
            ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None)
        )
        try:
            self.assertTrue(hasattr(window, "_run_btn"))
            self.assertTrue(hasattr(window, "_cancel_btn"))
            self.assertTrue(hasattr(window, "_restart_btn"))
            self.assertTrue(hasattr(window, "_send_btn"))
            procesar_idx = next(i for i, s in enumerate(window.SECTIONS) if s[1] == "Procesar")
            window._switch_section(procesar_idx)
            self.assertTrue(window._action_zone.isVisible())
            self.assertFalse(window._nav_next_btn.isVisible())
        finally:
            window.deleteLater()
            self.app.processEvents()
```

- [ ] **Step 2: Run the new test to confirm it fails**

```
pytest tests/test_compresor_window.py::CompresorWindowTests::test_action_buttons_exist_and_go_to_navbar -v
```

Expected: FAIL — `AttributeError: 'CompresorWindow' has no attribute '_run_btn'`.

- [ ] **Step 3: Update `__init__` — add `_build_action_buttons` call**

In `CompresorWindow.__init__`, change:

```python
        self._build_pages()
        self._switch_section(0)
        self.setAcceptDrops(True)
```

to:

```python
        self._build_pages()
        self._build_action_buttons()
        self._switch_section(0)
        self.setAcceptDrops(True)
```

- [ ] **Step 4: Add `_build_action_buttons` method**

Add this method to `CompresorWindow` (before `_build_documents_section`):

```python
    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Comprimir PDFs")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "compresor")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)
```

- [ ] **Step 5: Add `_on_proc_running` method**

```python
    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()
```

- [ ] **Step 6: Update `_build_process_section` — remove old signal connections**

In `_build_process_section`, remove these two lines:

```python
        self._proc_step.run_requested.connect(self._on_run)    # DELETE
        self._proc_step.cancel_requested.connect(self._on_cancel)  # DELETE
```

Keep `self._proc_step.watch_documents(self._docs_card)`.

- [ ] **Step 7: Update `_build_results_section` — remove action_row, remove old _send_btn creation**

In `_build_results_section`, remove this entire block (keep `self._result_viewer = GenericPdfViewer(...)` and everything above it):

```python
        action_row = QHBoxLayout()
        action_row.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "compresor")
        action_row.addWidget(self._send_btn)

        restart = QPushButton("Nueva sesion")
        restart.setProperty("class", "Primary")
        restart.setMinimumWidth(180)
        set_button_icon(restart, "refresh-cw")
        restart.clicked.connect(self._reset_session)
        action_row.addWidget(restart)
        outer.addLayout(action_row)
```

Also remove the `SendToToolButton` import from the top of the file **only if** it's no longer imported anywhere else — it is now imported inside `_build_action_buttons`, so the top-level import can be removed.

The `_build_results_section` should end with:

```python
        self._result_viewer = GenericPdfViewer("PDFs comprimidos")
        self._result_viewer.openInExplorer.connect(self._open_in_explorer)
        outer.addWidget(self._result_viewer, 1)

        return page
```

- [ ] **Step 8: Run all CompresorWindow tests**

```
pytest tests/test_compresor_window.py tests/test_scaffold_action_zone.py -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```
git add ui/compresor/window.py tests/test_compresor_window.py
git commit -m "feat(compresor): move action buttons to navbar footer"
```

---

### Task 6: UnirWindow

**Files:**
- Modify: `ui/unir/window.py`
- Modify: `tests/test_unir_window.py`

- [ ] **Step 1: Add test**

Append to the test class in `tests/test_unir_window.py`:

```python
    def test_action_buttons_in_navbar(self) -> None:
        from ui.unir.window import UnirWindow
        w = UnirWindow(ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None))
        try:
            self.assertTrue(hasattr(w, "_run_btn"))
            self.assertTrue(hasattr(w, "_cancel_btn"))
            self.assertTrue(hasattr(w, "_restart_btn"))
            procesar_idx = next(i for i, s in enumerate(w.SECTIONS) if s[1] == "Procesar")
            w._switch_section(procesar_idx)
            self.assertTrue(w._action_zone.isVisible())
            self.assertFalse(w._nav_next_btn.isVisible())
        finally:
            w.deleteLater(); self.app.processEvents()
```

- [ ] **Step 2: Run to confirm failure, then implement**

```
pytest tests/test_unir_window.py -k test_action_buttons_in_navbar -v
```

Expected: FAIL.

- [ ] **Step 3: Update `UnirWindow.__init__`**

Add `self._build_action_buttons()` after `self._build_pages()`, before `self._switch_section(0)`.

- [ ] **Step 4: Add `_build_action_buttons` to `UnirWindow`**

```python
    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Unir PDFs")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "unir")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)
```

- [ ] **Step 5: Add `_on_proc_running`**

```python
    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()
```

- [ ] **Step 6: In `_build_process_section`, remove old connections**

Delete:
```python
        self._proc_step.run_requested.connect(self._on_run)
        self._proc_step.cancel_requested.connect(self._on_cancel)
```

Also remove: `self._proc_step.set_run_enabled(False)` (now handled by `_run_btn.setEnabled(False)` at creation and via `run_enabled_changed`).

- [ ] **Step 7: In `_build_results_section`, remove `action_row` block**

Delete:
```python
        action_row = QHBoxLayout()
        action_row.addStretch()

        self._send_btn = SendToToolButton(self.ctx, "unir")
        action_row.addWidget(self._send_btn)

        restart_btn = QPushButton("Nueva sesión")
        restart_btn.setProperty("class", "Primary")
        restart_btn.setMinimumWidth(180)
        set_button_icon(restart_btn, "refresh-cw")
        restart_btn.clicked.connect(self._reset_session)
        action_row.addWidget(restart_btn)
        outer.addLayout(action_row)
```

- [ ] **Step 8: Update `_on_finished` — remove `self._send_btn.set_output_paths([])` if was in action_row init**

In `_on_finished`, the line `self._send_btn.set_output_paths(output_paths)` and in `_reset_session` `self._send_btn.set_output_paths([])` — these still work since `_send_btn` is now on `self`. No change needed.

- [ ] **Step 9: Run tests and commit**

```
pytest tests/test_unir_window.py -v
git add ui/unir/window.py tests/test_unir_window.py
git commit -m "feat(unir): move action buttons to navbar footer"
```

---

### Task 7: ProtectorWindow + MarcaAguaWindow

**Files:**
- Modify: `ui/protector/window.py`, `ui/marca_agua/window.py`
- Modify: `tests/test_protector_window.py`, `tests/test_marca_agua_window.py`

For each window, apply the **exact same pattern** as Tasks 5–6. Only the specific values differ.

#### ProtectorWindow

- [ ] **Step 1: Add test to `tests/test_protector_window.py`** (same structure as Task 6 Step 1, with `ProtectorWindow`)

- [ ] **Step 2: Run to fail**

```
pytest tests/test_protector_window.py -k test_action_buttons_in_navbar -v
```

- [ ] **Step 3: Update `__init__`** — add `self._build_action_buttons()` after `self._build_pages()`

- [ ] **Step 4: Add `_build_action_buttons`**

```python
    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Proteger PDFs")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "protector")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)
```

- [ ] **Step 5: Add `_on_proc_running`** (identical to Tasks 5–6)

```python
    def _on_proc_running(self, running: bool) -> None:
        if running:
            self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(running)
        self._apply_primary_glows()
```

- [ ] **Step 6: Remove old connections from `_build_process_section`** — delete `run_requested.connect` and `cancel_requested.connect`

- [ ] **Step 7: Remove `action_row` block from `_build_results_section`** — search for `action_row = QHBoxLayout()` and delete through `outer.addLayout(action_row)`

- [ ] **Step 8: Run, then commit**

```
pytest tests/test_protector_window.py -v
```

#### MarcaAguaWindow

- [ ] **Step 9: Add test to `tests/test_marca_agua_window.py`**

```python
    def test_action_buttons_in_navbar(self) -> None:
        from ui.marca_agua.window import MarcaAguaWindow
        w = MarcaAguaWindow(ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None))
        try:
            self.assertTrue(hasattr(w, "_run_btn"))
            self.assertTrue(hasattr(w, "_cancel_btn"))
            procesar_idx = next(i for i, s in enumerate(w.SECTIONS) if s[1] == "Procesar")
            w._switch_section(procesar_idx)
            self.assertTrue(w._action_zone.isVisible())
        finally:
            w.deleteLater(); self.app.processEvents()
```

- [ ] **Step 10: Run to fail, then apply full pattern**

`run_label="Aplicar sello"`, `tool_id="marca_agua"`, `restart_label="Nueva sesion"`

- [ ] **Step 11: Commit both**

```
git add ui/protector/window.py tests/test_protector_window.py ui/marca_agua/window.py tests/test_marca_agua_window.py
git commit -m "feat(protector,marca-agua): move action buttons to navbar footer"
```

---

### Task 8: ExtraerImagenesWindow + QuitarFondoWindow

**Files:**
- Modify: `ui/extraer_imagenes/window.py`, `ui/quitar_fondo/window.py`

For each, apply the standard pattern. Values:

| Window | run_label | tool_id | restart_label |
|---|---|---|---|
| ExtraerImagenesWindow | "Extraer imagenes" | "extraer_imagenes" | "Nueva sesion" |
| QuitarFondoWindow | "Quitar fondo" | "quitar_fondo" | "Nueva sesión" |

- [ ] **Step 1: Add test for ExtraerImagenesWindow** (same structure: instantiate, navigate to Procesar, assert action_zone visible)
- [ ] **Step 2: Run to fail**
- [ ] **Step 3: Apply full pattern to ExtraerImagenesWindow** — `__init__` update, `_build_action_buttons`, `_on_proc_running`, remove old connections, remove action_row
- [ ] **Step 4: Add test for QuitarFondoWindow**
- [ ] **Step 5: Run to fail**
- [ ] **Step 6: Apply full pattern to QuitarFondoWindow**
- [ ] **Step 7: Run all tests and commit**

```
pytest tests/test_smoke_tools.py -k "extraer_imagenes or quitar_fondo" -v
git add ui/extraer_imagenes/window.py ui/quitar_fondo/window.py
git commit -m "feat(extraer-imagenes,quitar-fondo): move action buttons to navbar footer"
```

---

### Task 9: ReparadorWindow + ClasificadorWindow

Values:

| Window | run_label | tool_id | restart_label |
|---|---|---|---|
| ReparadorWindow | "Reparar / normalizar" | "reparador" | "Nueva reparacion" |
| ClasificadorWindow | "Clasificar y renombrar" | "clasificador" | "Nueva sesion" |

- [ ] **Step 1–3: ReparadorWindow** — add test, run fail, apply full pattern
- [ ] **Step 4–6: ClasificadorWindow** — add test, run fail, apply full pattern
- [ ] **Step 7: Run and commit**

```
pytest tests/test_smoke_tools.py -k "reparador or clasificador" -v
git add ui/reparador/window.py ui/clasificador/window.py
git commit -m "feat(reparador,clasificador): move action buttons to navbar footer"
```

---

### Task 10: ComparadorWindow + FormulariosWindow

Values:

| Window | run_label | tool_id | restart_label |
|---|---|---|---|
| ComparadorWindow | "Comparar PDFs" | "comparador" | "Nueva comparacion" |
| FormulariosWindow | "Rellenar formulario" | "formularios" | "Nueva sesion" |

- [ ] **Step 1–3: ComparadorWindow** — add test, run fail, apply full pattern
- [ ] **Step 4–6: FormulariosWindow** — add test, run fail, apply full pattern
- [ ] **Step 7: Run and commit**

```
pytest tests/test_smoke_tools.py -k "comparador or formularios" -v
git add ui/comparador/window.py ui/formularios/window.py
git commit -m "feat(comparador,formularios): move action buttons to navbar footer"
```

---

### Task 11: ImgsAPdfWindow + RedactorWindow

Values:

| Window | run_label | tool_id | restart_label |
|---|---|---|---|
| ImgsAPdfWindow | "Generar PDF" | "imgs_a_pdf" | "Nueva sesión" |
| RedactorWindow | "Redactar PDF" | "redactor" | "Nueva sesion" |

- [ ] **Step 1–3: ImgsAPdfWindow** — apply pattern (note: file is large ~970 lines; `_build_results_section` starts around line 950)
- [ ] **Step 4–6: RedactorWindow** — apply pattern
- [ ] **Step 7: Run and commit**

```
pytest tests/test_smoke_tools.py -k "imgs_a_pdf or redactor" -v
git add ui/imgs_a_pdf/window.py ui/redactor/window.py
git commit -m "feat(imgs-a-pdf,redactor): move action buttons to navbar footer"
```

---

### Task 12: SeparadorWindow + PdfToImgsWindow

Values:

| Window | run_label | tool_id | restart_label |
|---|---|---|---|
| SeparadorWindow | "Separar documento" | "separador" | "Nueva sesión" |
| PdfToImgsWindow | "Convertir a imágenes" | "pdf_to_imgs" | "Nueva sesión" |

- [ ] **Step 1–3: SeparadorWindow** — apply pattern
- [ ] **Step 4–6: PdfToImgsWindow** — apply pattern
- [ ] **Step 7: Run and commit**

```
pytest tests/test_smoke_tools.py -k "separador or pdf_to_imgs" -v
pytest tests/test_pdf_to_imgs_window.py -v
git add ui/separador/window.py ui/pdf_to_imgs/window.py
git commit -m "feat(separador,pdf-to-imgs): move action buttons to navbar footer"
```

---

### Task 13: PdfToWordWindow + OcrWindow (no `_send_btn`)

**Files:**
- Modify: `ui/pdf_to_word/window.py`, `ui/ocr/window.py`

#### PdfToWordWindow

Values: `run_label="Convertir a Word"`, `tool_id="pdf_to_word"`, `restart_label="Nueva sesion"`

- [ ] **Step 1–3: Apply standard pattern** (has `_send_btn`)

#### OcrWindow — no `_send_btn`

OcrWindow has no `SendToToolButton` in its results section. The `_build_action_buttons` omits `_send_btn`:

- [ ] **Step 4: Apply pattern to OcrWindow without `_send_btn`**

```python
    def _build_action_buttons(self) -> None:
        self._run_btn = QPushButton("Extraer texto con OCR")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        # No _send_btn — OcrWindow does not have SendToToolButton

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)
```

The base `_get_step_actions` skips `_send_btn` automatically via `hasattr`. Resultados step shows only `[_restart_btn]`.

- [ ] **Step 5: Remove action_row from OcrWindow `_build_results_section`** (search for `action_row = QHBoxLayout()`)

- [ ] **Step 6: Run tests and commit**

```
pytest tests/test_pdf_to_word_window.py tests/test_smoke_tools.py -k "pdf_to_word or ocr" -v
git add ui/pdf_to_word/window.py ui/ocr/window.py
git commit -m "feat(pdf-to-word,ocr): move action buttons to navbar footer"
```

---

### Task 14: OrganizadorWindow + WordAPdfWindow (Procesar=1, Resultados=2)

These two tools have 3 steps: the Procesar step is index 1 and Resultados is index 2. The base `_get_step_actions` uses step NAME matching, so no override is needed — the same pattern applies.

#### OrganizadorWindow

`SECTIONS = [(0,'Paginas'),(1,'Procesar'),(2,'Resultados')]`

- [ ] **Step 1: Apply pattern**

```python
    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Generar PDFs")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesion")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "organizador")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)
```

> **OrganizadorWindow note:** `ProcessStep` in organizador is created inline (not inside a separate `_build_process_section`) — search for `self._proc_step = ProcessStep(` and remove the `run_requested`/`cancel_requested` connections wherever they appear. The `action_row` block is also inline — find and remove it.

- [ ] **Step 2: Remove old connections from wherever `run_requested`/`cancel_requested` are connected in the file**

- [ ] **Step 3: Remove the `action_row` block from the results section of the file**

#### WordAPdfWindow

`SECTIONS = [(0,'Documentos'),(1,'Procesar'),(2,'Resultados')]`

Values: `run_label="Convertir a PDF"`, `tool_id="word_a_pdf"`, `restart_label="Nueva sesión"`

- [ ] **Step 4: Apply full pattern** (has `_send_btn`)

- [ ] **Step 5: Run tests and commit**

```
pytest tests/test_smoke_tools.py -k "organizador or word_a_pdf" -v
pytest tests/test_organizador_window.py -v
git add ui/organizador/window.py ui/word_a_pdf/window.py
git commit -m "feat(organizador,word-a-pdf): move action buttons to navbar footer"
```

---

### Task 15: MembretadoWindow (Procesar=3, Resultados=4)

`SECTIONS = [(0,'Membrete'),(1,'Documentos'),(2,'Margenes'),(3,'Procesar'),(4,'Resultados')]`

**Files:**
- Modify: `ui/membretado/window.py`
- Modify: `tests/test_membretado_window.py`

- [ ] **Step 1: Add test**

```python
    def test_action_buttons_in_navbar(self) -> None:
        from ui.membretado.window import MembretadoWindow
        w = MembretadoWindow(ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None))
        try:
            self.assertTrue(hasattr(w, "_run_btn"))
            w._switch_section(3)  # Procesar
            self.assertTrue(w._action_zone.isVisible())
            self.assertFalse(w._nav_next_btn.isVisible())
        finally:
            w.deleteLater(); self.app.processEvents()
```

- [ ] **Step 2: Run to fail**

- [ ] **Step 3: Add `_build_action_buttons` to `MembretadoWindow`**

```python
    def _build_action_buttons(self) -> None:
        from ui.common.send_to_tool import SendToToolButton

        self._run_btn = QPushButton("Membretar documentos")
        self._run_btn.setProperty("class", "Primary")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setMinimumWidth(160)
        set_button_icon(self._run_btn, "play")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setProperty("class", "Danger")
        self._cancel_btn.setFixedHeight(36)
        set_button_icon(self._cancel_btn, "square", color="#E5484D")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._restart_btn = QPushButton("Nueva sesión")
        self._restart_btn.setProperty("class", "Primary")
        self._restart_btn.setFixedHeight(36)
        self._restart_btn.setMinimumWidth(160)
        set_button_icon(self._restart_btn, "refresh-cw")
        self._restart_btn.clicked.connect(self._reset_session)

        self._send_btn = SendToToolButton(self.ctx, "membretado")

        self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)
        self._proc_step.running_changed.connect(self._on_proc_running)
```

- [ ] **Step 4: Update `__init__`** — add `self._build_action_buttons()` after `self._build_pages()`

- [ ] **Step 5: Add `_on_proc_running`** (same as all others)

- [ ] **Step 6: In `_build_process_section` (~line 640), remove old connections**

Search for `run_requested.connect` and `cancel_requested.connect` and delete both lines.

- [ ] **Step 7: In `_build_results_section` (~line 685), remove action_row block**

Remove from `nav = QHBoxLayout()` (or `action_row = QHBoxLayout()`) through `outer.addLayout(nav)` — the block containing `_send_btn` creation and `restart_btn`. The results section should end with the viewer widget only.

- [ ] **Step 8: Run tests and commit**

```
pytest tests/test_membretado_window.py -v
git add ui/membretado/window.py tests/test_membretado_window.py
git commit -m "feat(membretado): move action buttons to navbar footer"
```

---

### Task 16: FirmadorWindow (Procesar=4, Resultados=5)

`SECTIONS = [(0,'Documentos'),(1,'Firma y posición'),(2,'Variación'),(3,'Intervalos'),(4,'Procesar'),(5,'Resultados')]`

**Files:**
- Modify: `ui/firmador/window.py`

FirmadorWindow is the largest file (~1200 lines). The ProcessStep is at `_build_process_section` around line 1156. The results section is around line 1185.

- [ ] **Step 1: Add test to a test file for firmador** (create `tests/test_firmador_navbar.py` if no existing test file)

```python
"""Test that FirmadorWindow action buttons are in the navbar."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtWidgets import QApplication
from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)

def test_firmador_action_buttons_in_navbar(app):
    from ui.firmador.window import FirmadorWindow
    w = FirmadorWindow(ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None))
    try:
        assert hasattr(w, "_run_btn")
        assert hasattr(w, "_cancel_btn")
        assert hasattr(w, "_restart_btn")
        w._switch_section(4)  # Procesar
        assert w._action_zone.isVisible()
        assert not w._nav_next_btn.isVisible()
    finally:
        w.deleteLater(); app.processEvents()
```

- [ ] **Step 2: Run to fail**

```
pytest tests/test_firmador_navbar.py -v
```

- [ ] **Step 3: Apply full pattern to FirmadorWindow**

`run_label="Firmar documentos"`, `tool_id="firmador"`, `restart_label="Nueva sesión"`

Add `_build_action_buttons()` method (same structure), add `_on_proc_running()`, update `__init__`, remove old connections from `_build_process_section`, remove action_row from `_build_results_section`.

> **Note on FirmadorWindow `_build_results_section`:** The results section's action block uses `actions = QHBoxLayout()` (not `action_row`) — search for this pattern around line 1185. Delete from `actions = QHBoxLayout()` through `outer.addLayout(actions)`, including the `_send_btn` and `restart_btn` creation within that block.

- [ ] **Step 4: Run tests and commit**

```
pytest tests/test_firmador_navbar.py tests/test_smoke_tools.py -k firmador -v
git add ui/firmador/window.py tests/test_firmador_navbar.py
git commit -m "feat(firmador): move action buttons to navbar footer"
```

---

### Task 17: FoleadorWindow (Procesar=4, Resultados=5)

`SECTIONS = [(0,'Documentos'),(1,'Formato'),(2,'Estilo'),(3,'Posición'),(4,'Procesar'),(5,'Resultados')]`

**Files:**
- Modify: `ui/foleador/window.py`

- [ ] **Step 1: Add test** (create `tests/test_foleador_navbar.py`)

```python
"""Test that FoleadorWindow action buttons are in the navbar."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtWidgets import QApplication
from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)

def test_foleador_action_buttons_in_navbar(app):
    from ui.foleador.window import FoleadorWindow
    w = FoleadorWindow(ShellContext(tray=PdfTray(), word_converter=WordToPdfConverter(), open_tool=lambda *_: None))
    try:
        assert hasattr(w, "_run_btn")
        w._switch_section(4)  # Procesar
        assert w._action_zone.isVisible()
        assert not w._nav_next_btn.isVisible()
    finally:
        w.deleteLater(); app.processEvents()
```

- [ ] **Step 2: Run to fail**

- [ ] **Step 3: Apply full pattern**

`run_label="Foliar documentos"`, `tool_id="foleador"`, `restart_label="Nueva sesión"`

> **Note on FoleadorWindow results section:** The action block uses `actions = QHBoxLayout()` around line 520. Remove from `actions = QHBoxLayout()` through `outer.addLayout(actions)`.

- [ ] **Step 4: Run tests and commit**

```
pytest tests/test_foleador_navbar.py tests/test_smoke_tools.py -k foleador -v
git add ui/foleador/window.py tests/test_foleador_navbar.py
git commit -m "feat(foleador): move action buttons to navbar footer"
```

---

### Task 18: Final verification — run all tests

- [ ] **Step 1: Run full test suite**

```
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 2: Verify smoke test passes for all 21 tools**

```
pytest tests/test_smoke_tools.py -v
```

Expected: 21/21 PASS.

- [ ] **Step 3: Remove dead `run_requested`/`cancel_requested` signals from `ProcessStep` if they were kept temporarily**

If in Task 4 Step 9 you added them back temporarily, now remove them:

```python
# Delete these two lines from ProcessStep:
run_requested = pyqtSignal()
cancel_requested = pyqtSignal()
```

Run tests again to confirm nothing references them.

- [ ] **Step 4: Run full suite one more time**

```
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 5: Final commit**

```
git add -u
git commit -m "feat: contextual footer buttons — action zone complete across all 21 tools"
```

---

## Quick Reference: Pattern per tool window

When applying the pattern to any tool, these are the 5 changes:

1. **`__init__`**: add `self._build_action_buttons()` after `self._build_pages()`, before `self._switch_section(0)`

2. **New method `_build_action_buttons()`**:
   - `self._run_btn` = QPushButton(`<run_label>`), Primary, h=36, w≥160, clicked→`_on_run`, enabled=False
   - `self._cancel_btn` = QPushButton("Cancelar"), Danger, h=36, clicked→`_on_cancel`, enabled=False
   - `self._restart_btn` = QPushButton(`<restart_label>`), Primary, h=36, w≥160, clicked→`_reset_session`
   - `self._send_btn` = SendToToolButton(self.ctx, `<tool_id>`) ← omit if tool has no send button
   - `self._proc_step.run_enabled_changed.connect(self._run_btn.setEnabled)`
   - `self._proc_step.running_changed.connect(self._on_proc_running)`

3. **New method `_on_proc_running`**:
   ```python
   def _on_proc_running(self, running: bool) -> None:
       if running:
           self._run_btn.setEnabled(False)
       self._cancel_btn.setEnabled(running)
       self._apply_primary_glows()
   ```

4. **In `_build_process_section`**: delete `run_requested.connect(...)` and `cancel_requested.connect(...)`

5. **In `_build_results_section`**: delete the entire `action_row` / `actions` / `nav` block that creates `_send_btn` and `restart_btn` inline

## Tool values table

| Window | run_label | tool_id | restart_label | has_send | Procesar idx | Resultados idx |
|---|---|---|---|---|---|---|
| CompresorWindow | "Comprimir PDFs" | "compresor" | "Nueva sesion" | ✓ | 2 | 3 |
| UnirWindow | "Unir PDFs" | "unir" | "Nueva sesión" | ✓ | 2 | 3 |
| ProtectorWindow | "Proteger PDFs" | "protector" | "Nueva sesion" | ✓ | 2 | 3 |
| MarcaAguaWindow | "Aplicar sello" | "marca_agua" | "Nueva sesion" | ✓ | 2 | 3 |
| ExtraerImagenesWindow | "Extraer imagenes" | "extraer_imagenes" | "Nueva sesion" | ✓ | 2 | 3 |
| QuitarFondoWindow | "Quitar fondo" | "quitar_fondo" | "Nueva sesión" | ✓ | 2 | 3 |
| ReparadorWindow | "Reparar / normalizar" | "reparador" | "Nueva reparacion" | ✓ | 2 | 3 |
| ClasificadorWindow | "Clasificar y renombrar" | "clasificador" | "Nueva sesion" | ✓ | 2 | 3 |
| ComparadorWindow | "Comparar PDFs" | "comparador" | "Nueva comparacion" | ✓ | 2 | 3 |
| FormulariosWindow | "Rellenar formulario" | "formularios" | "Nueva sesion" | ✓ | 2 | 3 |
| ImgsAPdfWindow | "Generar PDF" | "imgs_a_pdf" | "Nueva sesión" | ✓ | 2 | 3 |
| RedactorWindow | "Redactar PDF" | "redactor" | "Nueva sesion" | ✓ | 2 | 3 |
| SeparadorWindow | "Separar documento" | "separador" | "Nueva sesión" | ✓ | 2 | 3 |
| PdfToImgsWindow | "Convertir a imágenes" | "pdf_to_imgs" | "Nueva sesión" | ✓ | 2 | 3 |
| PdfToWordWindow | "Convertir a Word" | "pdf_to_word" | "Nueva sesion" | ✓ | 2 | 3 |
| OcrWindow | "Extraer texto con OCR" | — | "Nueva sesión" | ✗ | 2 | 3 |
| OrganizadorWindow | "Generar PDFs" | "organizador" | "Nueva sesion" | ✓ | 1 | 2 |
| WordAPdfWindow | "Convertir a PDF" | "word_a_pdf" | "Nueva sesión" | ✓ | 1 | 2 |
| MembretadoWindow | "Membretar documentos" | "membretado" | "Nueva sesión" | ✓ | 3 | 4 |
| FirmadorWindow | "Firmar documentos" | "firmador" | "Nueva sesión" | ✓ | 4 | 5 |
| FoleadorWindow | "Foliar documentos" | "foleador" | "Nueva sesión" | ✓ | 4 | 5 |
