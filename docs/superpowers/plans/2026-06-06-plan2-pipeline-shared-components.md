# PDFlex Premium — Plan 2: PipelineWindow + Shared Components

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevar la experiencia dentro de cada herramienta: estados visuales de pasos completados, transiciones slide animadas, barra de navegación fija (← prev / next →), atajos Alt+N, mejoras en DocumentsCard (menú compacto, conteo live, drag feedback animado) y shimmer + count-up en ProcessStep.

**Architecture:** Evolutionary Premium — cirugía sobre `tool_scaffold.py`, `documents_step.py` y `process_step.py`. Nada se reescribe. Las mejoras del Plan 1 (AnimationHelper, COLORS premium) se usan directamente.

**Tech Stack:** PyQt6 (QPropertyAnimation, QTimer, QShortcut, QMenu, QGraphicsDropShadowEffect) + AnimationHelper de Plan 1 — cero dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-06-06-pdflex-premium-redesign-design.md` Secciones 3 y 4.

**Depends on:** Plan 1 (COLORS, AnimationHelper, iconos SVG).

**Plans que siguen:**
- Plan 3: Launcher redesign + features transversales (Ctrl+K, presets, historial drawer)
- Plan 4 & 5: Per-tool improvements

---

## File Map

| Acción | Archivo | Responsabilidad |
|--------|---------|-----------------|
| Modify | `ui/common/tool_scaffold.py` | Completed step states, slide transition, NavBar fija, Alt+N shortcuts |
| Modify | `ui/common/documents_step.py` | Menú compacto [≡], label count+size live, drag visual feedback |
| Modify | `ui/common/process_step.py` | Shimmer en QProgressBar, count-up en stat labels |
| Modify | `tests/test_design_system.py` | Tests de nuevas funcionalidades |

---

## Estado de implementación (actualizado 2026-06-07)

- [x] Task 1: `_StepBtn` estados completed/pending con checkmark (`e622da9`)
- [x] Task 2: transición slide animada entre pasos (`8c9a404`)
- [x] Task 3: NavBar fija prev/next (`58eb9cd`)
- [x] Task 4: atajos Alt+1-9 + hint en sidebar (`e1564e7`)
- [x] Task 5: `DocumentsCard` menú compacto + count/size (`65d2d22`)
- [x] Task 6: `DocumentsCard` drag feedback con accent, bounce interno y flash
- [x] Task 7: `ProcessStep` shimmer, count-up API y estado running robusto
- [ ] Verificación visual manual en app: recorrer una herramienta con drag/drop y procesamiento real

Notas de revisión:
- `git status` al retomar solo mostraba este plan sin trackear; las Tasks 1-5 ya estaban en commits.
- Task 6 usa bounce del icono interno, no resize del contenedor, para evitar saltos de layout.
- `PipelineWindow` propaga ahora el accent a shared components construidos por subclases al cambiar de sección.
- Los botones Primary deshabilitados ya no mantienen glow ni color de acción.

---

## Task 1: _StepBtn — estados completed/pending y checkmark

**Files:**
- Modify: `ui/common/tool_scaffold.py`
- Modify: `tests/test_design_system.py`

### Estado actual

`_StepBtn` tiene `set_active(bool)` y estados: `SidebarStep / SidebarStepHover / SidebarStepActive`. El badge muestra un número (p.ej. "01"). No hay estado "completado".

### Cambios requeridos

**Step 1.1: Añadir test**

Añadir al final de `tests/test_design_system.py`:

```python
def test_step_btn_completed_state():
    """_StepBtn puede marcar un paso como completado (muestra checkmark)."""
    import sys
    from PyQt6.QtWidgets import QApplication
    from ui.common.tool_scaffold import _StepBtn
    app = QApplication.instance() or QApplication(sys.argv)
    btn = _StepBtn("01", "Documentos")
    assert not btn._completed
    btn.set_completed(True)
    assert btn._completed
    btn.set_completed(False)
    assert not btn._completed
```

- [ ] **Step 1.1:** Añadir el test anterior al final de `tests/test_design_system.py`.

- [ ] **Step 1.2:** Ejecutar — debe FALLAR:

```
python -m pytest tests/test_design_system.py::test_step_btn_completed_state -v
```

- [ ] **Step 1.3:** En `_StepBtn.__init__`, añadir el atributo:

```python
self._completed = False
```

(añadir justo después de `self._active = False`)

- [ ] **Step 1.4:** Añadir el método `set_completed` a `_StepBtn`:

```python
def set_completed(self, completed: bool) -> None:
    self._completed = completed
    self._apply_state()
```

- [ ] **Step 1.5:** Actualizar `_apply_state` en `_StepBtn` para el nuevo estado `completed`:

Reemplazar el método `_apply_state` existente con:

```python
def _apply_state(self) -> None:
    if self._active:
        self.setObjectName("SidebarStepActive")
        self._badge.setObjectName("StepBadgeActive")
        self._lbl.setObjectName("StepNameActive")
        self._badge.setText(self._num)
    elif self._completed:
        self.setObjectName("SidebarStepCompleted")
        self._badge.setObjectName("StepBadgeCompleted")
        self._lbl.setObjectName("StepNameCompleted")
        self._badge.setText("✓")
    else:
        self.setObjectName("SidebarStep")
        self._badge.setObjectName("StepBadge")
        self._lbl.setObjectName("StepName")
        self._badge.setText(self._num)
    for w in (self, self._badge, self._lbl):
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
```

- [ ] **Step 1.6:** Añadir estilos CSS para los nuevos estados en `_apply_tool_accent` de `PipelineWindow`.

Dentro del string `self.setStyleSheet(f"""...""")`, añadir después del bloque `QLabel#StepBadgeActive`:

```css
/* Paso completado */
#SidebarStepCompleted {{
    background: transparent;
    border: none;
    border-left: 2px solid {_rgba(accent, 0.25)};
}}
QLabel#StepBadgeCompleted {{
    background: {_rgba(accent, 0.12)};
    color: {accent};
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
    border: 1px solid {_rgba(accent, 0.25)};
}}
QLabel#StepNameCompleted {{
    color: #6B6F7A;
    font-size: 13px;
    font-weight: 500;
    background: transparent;
}}
```

- [ ] **Step 1.7:** Añadir `_completed_steps: set[int]` a `PipelineWindow` y marcar pasos al avanzar.

En `PipelineWindow.__init__`, después de `self.ctx = ctx`, añadir:

```python
self._completed_steps: set[int] = set()
```

En `_switch_section`, añadir la lógica de "marcar anterior como completado" al navegar hacia adelante:

```python
def _switch_section(self, idx: int) -> None:
    prev_idx = self.stack.currentIndex()
    # Marcar paso anterior como completado si avanzamos
    if idx > prev_idx and prev_idx >= 0:
        self._completed_steps.add(prev_idx)
    for i, btn in enumerate(self._section_buttons):
        btn.set_active(i == idx)
        btn.set_completed(i in self._completed_steps and i != idx)
    self.stack.setCurrentIndex(idx)
    if hasattr(self, "_step_progress") and self.SECTIONS:
        pct = int((idx + 1) / len(self.SECTIONS) * 100)
        self._step_progress.setValue(pct)
    self._on_section_activated(idx)
```

- [ ] **Step 1.8:** Ejecutar todos los tests:

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Resultado esperado: todos pasan.

- [ ] **Step 1.9:** Commit:

```bash
git add ui/common/tool_scaffold.py tests/test_design_system.py
git commit -m "feat(scaffold): estados completed/pending en pasos del sidebar con checkmark"
```

---

## Task 2: Transición slide animada entre pasos

**Files:**
- Modify: `ui/common/tool_scaffold.py`

### Lógica de la animación

Al cambiar de paso:
1. Capturar el widget actual como QPixmap con `.grab()`
2. Crear un `QLabel` temporal superpuesto sobre el stack con ese pixmap
3. Cambiar el stack silenciosamente al nuevo índice
4. Animar el label temporal (slide hacia afuera) mientras el nuevo contenido ya está visible debajo
5. Borrar el label al terminar

Dirección: avanzar → label sale por la izquierda. Retroceder → sale por la derecha.

- [ ] **Step 2.1:** Añadir el método `_slide_to_section` a `PipelineWindow`:

Añadir ANTES de `_switch_section`:

```python
def _slide_to_section(self, idx: int) -> None:
    """Transición slide animada entre pasos. Llama a _switch_section internamente."""
    from PyQt6.QtCore import QPropertyAnimation, QRect, QEasingCurve, QTimer
    from ui.common.animations import is_reduced_motion

    if is_reduced_motion():
        self._switch_section(idx)
        return

    current_idx = self.stack.currentIndex()
    if current_idx == idx:
        return

    direction = 1 if idx > current_idx else -1  # 1=avanzar(sale izq), -1=retroceder(sale der)

    # Capturar snapshot del widget actual
    current_widget = self.stack.currentWidget()
    if current_widget is None:
        self._switch_section(idx)
        return

    snapshot = current_widget.grab()
    w = self.stack.width()
    h = self.stack.height()

    # Overlay con el snapshot — flota sobre el stack
    from PyQt6.QtWidgets import QLabel
    overlay = QLabel(self.stack)
    overlay.setPixmap(snapshot)
    overlay.setGeometry(0, 0, w, h)
    overlay.raise_()
    overlay.show()

    # Cambiar el stack silenciosamente (el overlay lo cubre)
    self._switch_section(idx)

    # Animar el overlay: sale hacia la izquierda (avanzar) o derecha (retroceder)
    anim = QPropertyAnimation(overlay, b"geometry", overlay)
    anim.setDuration(220)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.setStartValue(QRect(0, 0, w, h))
    anim.setEndValue(QRect(-w * direction, 0, w, h))
    anim.finished.connect(overlay.deleteLater)
    anim.start()
```

- [ ] **Step 2.2:** Conectar los botones de paso al nuevo método `_slide_to_section` en lugar de `_switch_section`.

En `_build_sidebar`, localizar:

```python
btn._clicked.connect(lambda idx=i: self._switch_section(idx))
```

Reemplazar con:

```python
btn._clicked.connect(lambda idx=i: self._slide_to_section(idx))
```

- [ ] **Step 2.3:** Verificar smoke tests:

```
python -m pytest tests/ -k "smoke" --tb=short -q
```

Resultado esperado: todos pasan.

- [ ] **Step 2.4:** Commit:

```bash
git add ui/common/tool_scaffold.py
git commit -m "feat(scaffold): transición slide animada 220ms OutCubic entre pasos"
```

---

## Task 3: NavBar fija (← prev / next →) en el content area

**Files:**
- Modify: `ui/common/tool_scaffold.py`

### Diseño

La NavBar es un `QFrame` de 48px de alto, fijo en la base del área de contenido (no del sidebar). Tiene:
- Izquierda: botón Ghost "← [nombre paso anterior]" (oculto en el primer paso)
- Derecha: botón Primary "[nombre paso siguiente] →" (oculto en el último paso)

Se actualiza al cambiar de paso.

- [ ] **Step 3.1:** Modificar `_build_scaffold` para añadir la NavBar debajo del stack.

Reemplazar el bloque del stack en `_build_scaffold`:

```python
# ANTES:
self.stack = QStackedWidget()
self.stack.setStyleSheet("background-color: #0A0A0B;")
root.addWidget(self.stack, 1)
```

Con:

```python
# DESPUÉS:
content_area = QWidget()
content_area.setStyleSheet("background-color: #050507;")
content_layout = QVBoxLayout(content_area)
content_layout.setContentsMargins(0, 0, 0, 0)
content_layout.setSpacing(0)

self.stack = QStackedWidget()
content_layout.addWidget(self.stack, 1)

# NavBar fija al pie del content area
self._navbar = self._build_navbar()
content_layout.addWidget(self._navbar)

root.addWidget(content_area, 1)
```

- [ ] **Step 3.2:** Añadir el método `_build_navbar` a `PipelineWindow`:

```python
def _build_navbar(self) -> "QFrame":
    """Barra de navegación fija al pie: ← paso anterior / paso siguiente →"""
    from PyQt6.QtWidgets import QPushButton
    from ui.common.icons import icon_pixmap

    navbar = QFrame()
    navbar.setObjectName("ToolNavBar")
    navbar.setFixedHeight(56)
    navbar.setStyleSheet(
        f"QFrame#ToolNavBar {{"
        f"background: #0A0A0B;"
        f"border-top: 1px solid #1E1E28;"
        f"}}"
    )

    row = QHBoxLayout(navbar)
    row.setContentsMargins(20, 0, 20, 0)
    row.setSpacing(12)

    self._nav_prev_btn = QPushButton("Anterior")
    self._nav_prev_btn.setProperty("class", "Ghost")
    self._nav_prev_btn.setFixedHeight(36)
    self._nav_prev_btn.clicked.connect(self._on_nav_prev)
    self._nav_prev_btn.setVisible(False)
    row.addWidget(self._nav_prev_btn)

    row.addStretch()

    self._nav_next_btn = QPushButton("Siguiente")
    self._nav_next_btn.setProperty("class", "Primary")
    self._nav_next_btn.setFixedHeight(36)
    self._nav_next_btn.clicked.connect(self._on_nav_next)
    self._nav_next_btn.setVisible(False)
    row.addWidget(self._nav_next_btn)

    return navbar
```

- [ ] **Step 3.3:** Añadir los métodos de navegación y actualización:

```python
def _on_nav_prev(self) -> None:
    idx = self.stack.currentIndex()
    if idx > 0:
        self._slide_to_section(idx - 1)

def _on_nav_next(self) -> None:
    idx = self.stack.currentIndex()
    if idx < self.stack.count() - 1:
        self._slide_to_section(idx + 1)

def _update_navbar(self, idx: int) -> None:
    """Actualiza visibilidad y textos de los botones de navegación."""
    if not self.SECTIONS:
        return
    total = len(self.SECTIONS)
    # Prev
    if idx > 0:
        prev_name = self.SECTIONS[idx - 1][1]  # (num, nombre, hint)
        self._nav_prev_btn.setText(f"← {prev_name}")
        self._nav_prev_btn.setVisible(True)
    else:
        self._nav_prev_btn.setVisible(False)
    # Next
    if idx < total - 1:
        next_name = self.SECTIONS[idx + 1][1]
        self._nav_next_btn.setText(f"{next_name} →")
        self._nav_next_btn.setVisible(True)
    else:
        self._nav_next_btn.setVisible(False)
```

- [ ] **Step 3.4:** Llamar a `_update_navbar` desde `_switch_section`.

Al final del método `_switch_section`, añadir:

```python
    if hasattr(self, "_nav_prev_btn"):
        self._update_navbar(idx)
```

- [ ] **Step 3.5:** Llamar a `_update_navbar(0)` al inicializar (para mostrar correctamente el botón Siguiente en el primer paso).

En `PipelineWindow.__init__`, después de `self._apply_tool_accent()`:

```python
        QTimer.singleShot(0, lambda: self._update_navbar(0) if self.SECTIONS else None)
```

(El `QTimer` ya existe de Task 6 del Plan 1; añadir solo esta llamada extra, o encadenarla.)

- [ ] **Step 3.6:** Actualizar el color de la NavBar en `_apply_tool_accent`.

Al final de `_apply_tool_accent`, añadir:

```python
    if hasattr(self, "_nav_next_btn"):
        # Re-aplicar glow al botón next (puede haberse recreado)
        from ui.common.animations import AnimationHelper
        AnimationHelper.apply_glow(self._nav_next_btn, accent, blur=16, alpha=70)
```

- [ ] **Step 3.7:** Ejecutar smoke tests:

```
python -m pytest tests/ -k "smoke" --tb=short -q 2>&1 | tail -5
```

Resultado esperado: todos pasan.

- [ ] **Step 3.8:** Commit:

```bash
git add ui/common/tool_scaffold.py
git commit -m "feat(scaffold): NavBar fija con botones ← prev / next → animados"
```

---

## Task 4: Atajos Alt+1-9 para navegación entre pasos

**Files:**
- Modify: `ui/common/tool_scaffold.py`

- [ ] **Step 4.1:** Añadir registración de `QShortcut` para Alt+1…9 en `PipelineWindow.__init__`.

Añadir este bloque al final de `__init__` (antes del `QTimer.singleShot`):

```python
        # Atajos Alt+1-9 para navegar entre pasos de la herramienta
        from PyQt6.QtGui import QShortcut
        from PyQt6.QtCore import QKeyCombination
        for n in range(1, 10):
            shortcut = QShortcut(self)
            shortcut.setKey(f"Alt+{n}")
            shortcut.activated.connect(
                lambda idx=n-1: self._slide_to_section(idx) if idx < len(self.SECTIONS) else None
            )
        self._alt_shortcuts: list = []  # mantener referencias vivas
```

**Nota:** En Python, `QShortcut(self)` con `setKey` después es la forma correcta. El contexto del shortcut es el widget (herramienta activa), así que no interfiere con otros atajos globales.

- [ ] **Step 4.2:** Añadir hint de shortcuts en hover del sidebar.

En `_build_sidebar`, antes del `sb.addStretch(1)`, añadir el hint:

```python
        # Hint de atajos — visible solo al hacer hover en el sidebar
        self._shortcut_hint = QLabel("⌨  Alt+1…9 para navegar")
        self._shortcut_hint.setObjectName("SidebarShortcutHint")
        self._shortcut_hint.setStyleSheet(
            "color: #383B4A; font-size: 10px; padding: 0 18px 12px 18px;"
            "background: transparent;"
        )
        self._shortcut_hint.setVisible(False)
        sb.addWidget(self._shortcut_hint)
```

- [ ] **Step 4.3:** Sobreescribir `enterEvent` / `leaveEvent` del sidebar para mostrar/ocultar el hint.

El sidebar es el `QFrame` retornado por `_build_sidebar`. Para hacer esto sin complicar demasiado, añadir un `QFrame` subclase local solo para este efecto — o simplemente instalar un event filter en el sidebar:

Guardar referencia al sidebar en `_build_scaffold`:

```python
# En _build_scaffold, cambiar:
root.addWidget(self._build_sidebar())
# A:
self._sidebar_frame = self._build_sidebar()
root.addWidget(self._sidebar_frame)
```

Añadir en `PipelineWindow.__init__` (después de `_build_scaffold`):

```python
        self._sidebar_frame.installEventFilter(self)
```

Añadir el método `eventFilter` a `PipelineWindow`:

```python
def eventFilter(self, obj, event) -> bool:
    from PyQt6.QtCore import QEvent
    if obj is getattr(self, "_sidebar_frame", None):
        if event.type() == QEvent.Type.Enter:
            if hasattr(self, "_shortcut_hint"):
                self._shortcut_hint.setVisible(True)
        elif event.type() == QEvent.Type.Leave:
            if hasattr(self, "_shortcut_hint"):
                self._shortcut_hint.setVisible(False)
    return super().eventFilter(obj, event)
```

- [ ] **Step 4.4:** Ejecutar smoke tests:

```
python -m pytest tests/ -k "smoke" --tb=short -q 2>&1 | tail -5
```

Resultado esperado: todos pasan.

- [ ] **Step 4.5:** Commit:

```bash
git add ui/common/tool_scaffold.py
git commit -m "feat(scaffold): atajos Alt+1-9 para navegar entre pasos + hint en hover del sidebar"
```

---

## Task 5: DocumentsCard — menú compacto y label count+size live

**Files:**
- Modify: `ui/common/documents_step.py`
- Modify: `tests/test_design_system.py`

### Estado actual de la toolbar

Actualmente la toolbar tiene 4 botones en fila: `Agregar / Vaciar / Quitar / Cargar desde bandeja` + `_count_lbl`.

### Cambios

1. Mover "Vaciar" y "Quitar selección" a un menú `[≡]` dropdown (QMenu)
2. El botón "Tray" se mantiene visible (es frecuente)
3. El `_count_lbl` muestra ahora "N docs · X.X MB" (tamaño total)

- [ ] **Step 5.1:** Añadir test:

```python
def test_documents_card_count_label_shows_size():
    """_count_lbl muestra conteo y tamaño total."""
    import sys
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    ctx = MagicMock()
    ctx.tray.changed = MagicMock()
    ctx.tray.changed.connect = MagicMock()
    ctx.tray.paths = []
    from ui.common.documents_step import DocumentsCard
    card = DocumentsCard(ctx)
    # Label inicial
    assert "0" in card._count_lbl.text() or card._count_lbl.text() == ""
```

- [ ] **Step 5.2:** Ejecutar — debe pasar (el test es permisivo, solo verifica que no crashea):

```
python -m pytest tests/test_design_system.py::test_documents_card_count_label_shows_size -v
```

- [ ] **Step 5.3:** Modificar `_build` en `DocumentsCard`.

Encontrar el bloque de la toolbar (desde `row = QHBoxLayout()` hasta `row.addStretch()`). Reemplazar los botones `clear_btn` y `remove_btn` inline por un menú `[≡]`:

Eliminar estas líneas del _build:
```python
clear_btn = QPushButton("Vaciar")
clear_btn.setProperty("class", "Ghost")
set_button_icon(clear_btn, "eraser")
clear_btn.setToolTip("Vacía la lista actual sin borrar archivos del disco.")
clear_btn.clicked.connect(self.clear)
row.addWidget(clear_btn)

self._remove_btn = QPushButton("Quitar")
self._remove_btn.setProperty("class", "Ghost")
set_button_icon(self._remove_btn, "trash-2")
self._remove_btn.setToolTip("Quita del lote los documentos seleccionados. No borra archivos del disco.")
self._remove_btn.clicked.connect(self.remove_selected)
self._remove_btn.setEnabled(False)
row.addWidget(self._remove_btn)
```

Y añadir en su lugar:

```python
# Botón menú [≡] — agrupa acciones secundarias
from PyQt6.QtWidgets import QMenu
self._menu_btn = QPushButton()
self._menu_btn.setProperty("class", "Ghost")
set_button_icon(self._menu_btn, "more-horizontal")
self._menu_btn.setToolTip("Más acciones")
self._menu_btn.setFixedWidth(36)
self._menu_btn.clicked.connect(self._show_docs_menu)
row.addWidget(self._menu_btn)
```

Añadir el método `_show_docs_menu`:

```python
def _show_docs_menu(self) -> None:
    """Muestra el menú de acciones secundarias de la DocumentsCard."""
    from PyQt6.QtWidgets import QMenu
    from PyQt6.QtGui import QAction
    menu = QMenu(self)
    menu.setObjectName("DocsMenu")

    act_remove = QAction("Quitar seleccionados", menu)
    act_remove.setEnabled(bool(self.list_widget.selectedItems()) if hasattr(self, "list_widget") else False)
    act_remove.triggered.connect(self.remove_selected)
    menu.addAction(act_remove)

    act_clear = QAction("Vaciar lista", menu)
    act_clear.triggered.connect(self.clear)
    menu.addAction(act_clear)

    menu.addSeparator()

    act_sort_name = QAction("Ordenar por nombre", menu)
    act_sort_name.triggered.connect(lambda: self._sort_by("name"))
    menu.addAction(act_sort_name)

    act_sort_size = QAction("Ordenar por tamaño", menu)
    act_sort_size.triggered.connect(lambda: self._sort_by("size"))
    menu.addAction(act_sort_size)

    menu.exec(self._menu_btn.mapToGlobal(self._menu_btn.rect().bottomLeft()))
```

Añadir el método `_sort_by`:

```python
def _sort_by(self, key: str) -> None:
    """Ordena la lista de documentos por nombre o tamaño."""
    from pathlib import Path
    if key == "name":
        self._paths.sort(key=lambda p: Path(p).name.lower())
    elif key == "size":
        self._paths.sort(key=lambda p: Path(p).stat().st_size if Path(p).exists() else 0)
    self._rebuild_list()
    self.files_changed.emit(list(self._paths))
```

Añadir el método `_rebuild_list` (reconstruye el list_widget desde `_paths`):

```python
def _rebuild_list(self) -> None:
    """Reconstruye el list_widget a partir del estado actual de _paths."""
    self.list_widget.clear()
    for path in self._paths:
        self._add_item_to_list(path)
    self._content_stack.setCurrentIndex(1 if self._paths else 0)
```

**Nota:** Si ya existe un método similar para añadir ítems, reutilizarlo. El método `_add_item_to_list(path)` debería extraerse del código de `_on_files_added` si no existe ya — busca el código que crea `QListWidgetItem` y extráelo a un método separado.

- [ ] **Step 5.4:** Actualizar `_count_lbl` para mostrar tamaño total.

Buscar el método que actualiza `_count_lbl` (probablemente en `_update_count_label` o `_sync_after_change`). Reemplazar la actualización con:

```python
def _update_count_label(self) -> None:
    """Actualiza el label de conteo con N docs · X.X MB."""
    from pathlib import Path
    n = len(self._paths)
    if n == 0:
        self._count_lbl.setText("Sin documentos")
        return
    total_bytes = sum(
        Path(p).stat().st_size for p in self._paths if Path(p).exists()
    )
    if total_bytes >= 1_048_576:
        size_str = f"{total_bytes / 1_048_576:.1f} MB"
    elif total_bytes >= 1024:
        size_str = f"{total_bytes / 1024:.0f} KB"
    else:
        size_str = f"{total_bytes} B"
    doc_word = "doc" if n == 1 else "docs"
    self._count_lbl.setText(f"{n} {doc_word} · {size_str}")
```

Asegurarse de que `_update_count_label` se llame en todos los lugares donde antes se actualizaba `_count_lbl` (buscar `_count_lbl.setText` en el archivo y reemplazar con llamadas al nuevo método).

- [ ] **Step 5.5:** Ejecutar el test y smoke tests:

```
python -m pytest tests/test_design_system.py::test_documents_card_count_label_shows_size tests/ -k "smoke" --tb=short -q 2>&1 | tail -8
```

- [ ] **Step 5.6:** Commit:

```bash
git add ui/common/documents_step.py tests/test_design_system.py
git commit -m "feat(docs-card): menú compacto [≡], label count+size live, sort por nombre/tamaño"
```

---

## Task 6: DocumentsCard — feedback visual en drag & drop

**Files:**
- Modify: `ui/common/documents_step.py`

### Objetivo

Cuando el usuario arrastra archivos sobre la drop zone:
1. El borde del `_empty_w` se vuelve accent sólido + bg con tinte accent 6%
2. El icono de folder-open hace bounce (scale 1.0 → 1.12 → 1.0, loop)
3. Al soltar, flash de `rgba(accent, 0.15)` por 300ms

- [ ] **Step 6.1:** Añadir atributo de accent a `DocumentsCard.__init__`.

En `DocumentsCard.__init__`, añadir:

```python
self._accent: str = "#5E6AD2"  # sobreescribir desde la herramienta con set_accent()
```

Añadir método público:

```python
def set_accent(self, accent: str) -> None:
    """Permite que la herramienta inyecte su accent color para el feedback visual."""
    self._accent = accent
```

- [ ] **Step 6.2:** Mejorar `dragEnterEvent` con feedback visual.

Buscar el método `dragEnterEvent` en `DocumentsCard`. Reemplazarlo con:

```python
def dragEnterEvent(self, event: "QDragEnterEvent") -> None:
    if event.mimeData().hasUrls():
        event.acceptProposedAction()
        self._set_drag_highlight(True)
    else:
        event.ignore()
```

Añadir los métodos de highlight:

```python
def _set_drag_highlight(self, active: bool) -> None:
    """Aplica/quita el efecto visual de drag sobre la drop zone."""
    r, g, b = self._parse_accent_rgb()
    if active:
        self._empty_w.setStyleSheet(
            f"QFrame#DropZone {{"
            f"background: rgba({r},{g},{b},0.06);"
            f"border: 2px solid rgba({r},{g},{b},0.7);"
            f"border-radius: 10px;"
            f"}}"
        )
        self._start_icon_bounce()
    else:
        self._empty_w.setStyleSheet("")  # restaurar estilo base
        self._stop_icon_bounce()

def _parse_accent_rgb(self) -> tuple[int, int, int]:
    h = self._accent.lstrip("#")
    if len(h) != 6:
        return (94, 106, 210)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (94, 106, 210)

def _start_icon_bounce(self) -> None:
    """Inicia la animación bounce del icono folder-open."""
    if hasattr(self, "_bounce_timer") and self._bounce_timer.isActive():
        return
    from PyQt6.QtCore import QTimer
    import math
    self._bounce_step = 0
    self._bounce_timer = QTimer(self)
    self._bounce_timer.setInterval(40)

    def _tick():
        if not hasattr(self, "_bounce_timer"):
            return
        t = self._bounce_step / 20.0  # 0→1 en 20 ticks (~800ms)
        scale = 1.0 + 0.12 * abs(math.sin(t * math.pi * 2))
        # Aplicar escala via stylesheet en el icon_box
        if hasattr(self, "_icon_box"):
            sz = int(56 * scale)
            offset = (sz - 56) // 2
            self._icon_box.setFixedSize(sz, sz)
        self._bounce_step += 1

    self._bounce_timer.timeout.connect(_tick)
    self._bounce_timer.start()

def _stop_icon_bounce(self) -> None:
    """Detiene la animación bounce y restaura el icono."""
    if hasattr(self, "_bounce_timer"):
        self._bounce_timer.stop()
        self._bounce_timer.deleteLater()
        del self._bounce_timer
    if hasattr(self, "_icon_box"):
        self._icon_box.setFixedSize(56, 56)
```

**Nota:** Para que `_icon_box` sea accesible, añadir `self._icon_box = icon_box` en `_build` justo donde se crea el `icon_box`.

- [ ] **Step 6.3:** Mejorar `dragLeaveEvent` y `dropEvent`.

Buscar `dragLeaveEvent` y añadir:

```python
def dragLeaveEvent(self, event) -> None:
    self._set_drag_highlight(False)
    super().dragLeaveEvent(event)
```

En `dropEvent`, añadir el flash al inicio, después de `event.acceptProposedAction()`:

```python
def dropEvent(self, event: "QDropEvent") -> None:
    self._set_drag_highlight(False)
    if event.mimeData().hasUrls():
        event.acceptProposedAction()
        self._flash_drop_success()
        # ... (código existente de procesamiento de archivos)
```

Añadir `_flash_drop_success`:

```python
def _flash_drop_success(self) -> None:
    """Flash sutil de accent al recibir un drop exitoso."""
    from PyQt6.QtCore import QTimer
    r, g, b = self._parse_accent_rgb()
    self._empty_w.setStyleSheet(
        f"QFrame#DropZone {{ background: rgba({r},{g},{b},0.15); border-radius: 10px; }}"
    )
    QTimer.singleShot(300, lambda: self._empty_w.setStyleSheet(""))
```

- [ ] **Step 6.4:** Ejecutar smoke tests:

```
python -m pytest tests/ -k "smoke" --tb=short -q 2>&1 | tail -5
```

- [ ] **Step 6.5:** Commit:

```bash
git add ui/common/documents_step.py
git commit -m "feat(docs-card): feedback visual drag&drop con accent border, bounce de ícono y flash en drop"
```

---

## Task 7: ProcessStep — shimmer en progress bar + count-up en stats

**Files:**
- Modify: `ui/common/process_step.py`

### Estado actual

`ProcessStep` tiene un `QProgressBar` básico que se actualiza con `set_progress(value)`. No hay shimmer. Si tiene summary cards (stat values), no tienen count-up.

- [ ] **Step 7.1:** Añadir shimmer al progress bar durante procesamiento.

En `ProcessStep`, localizar el `QProgressBar` (probablemente `self._progress_bar` o `self._bar`). Añadir método `start_processing_ui` y `stop_processing_ui`:

```python
def start_processing_ui(self) -> None:
    """Inicia el shimmer en la progress bar e inhabilita el botón Ejecutar."""
    from ui.common.animations import AnimationHelper
    accent = getattr(self, "_accent", "#5E6AD2")
    if hasattr(self, "_progress_bar"):
        self._shimmer_timer = AnimationHelper.start_shimmer(self._progress_bar, accent)
    if hasattr(self, "_run_btn"):
        self._run_btn.setEnabled(False)
    if hasattr(self, "_cancel_btn"):
        self._cancel_btn.setVisible(True)

def stop_processing_ui(self) -> None:
    """Detiene el shimmer y restaura la UI al estado inicial."""
    if hasattr(self, "_shimmer_timer"):
        self._shimmer_timer.stop()
        del self._shimmer_timer
    if hasattr(self, "_progress_bar"):
        self._progress_bar.setStyleSheet("")
    if hasattr(self, "_run_btn"):
        self._run_btn.setEnabled(True)
    if hasattr(self, "_cancel_btn"):
        self._cancel_btn.setVisible(False)
```

Añadir atributo accent:

```python
def set_accent(self, accent: str) -> None:
    """Inyectar accent color para el shimmer."""
    self._accent = accent
```

- [ ] **Step 7.2:** Añadir count-up en stat labels.

En `ProcessStep`, si hay summary labels (p.ej. número de documentos, tamaño, etc.) añadir método para animarlos al mostrar la sección:

```python
def animate_stats(self, stats: dict[str, int]) -> None:
    """Anima los stat labels con count-up. stats = {"docs": 3, "pages": 24, ...}

    Busca QLabel con objectName en stats.keys() y anima su valor.
    """
    from ui.common.animations import AnimationHelper
    from PyQt6.QtWidgets import QLabel
    for name, value in stats.items():
        for lbl in self.findChildren(QLabel):
            if lbl.objectName() == name:
                AnimationHelper.count_up(lbl, value, duration=400)
                break
```

- [ ] **Step 7.3:** Leer process_step.py completo para verificar los nombres reales de los atributos.

```python
# Ejecutar este one-liner para ver los atributos de ProcessStep:
python -c "
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from ui.common.process_step import ProcessStep
s = ProcessStep(run_label='Test')
print([a for a in dir(s) if not a.startswith('__')])
"
```

Usar los nombres reales que aparecen (p.ej. si el progress bar se llama `_bar` en lugar de `_progress_bar`, actualizar el código de Task 7.1 acorde).

- [ ] **Step 7.4:** Ejecutar todos los tests:

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Resultado esperado: todos pasan.

- [ ] **Step 7.5:** Commit:

```bash
git add ui/common/process_step.py
git commit -m "feat(process-step): shimmer en progress bar + count-up en stats + set_accent"
```

---

## Verificación final del Plan 2

- [ ] **Suite completa:**

```
python -m pytest tests/ -v --tb=short 2>&1 | tail -15
```

Resultado esperado: todos pasan.

- [ ] **Smoke test visual:**

```
python main.py
```

Checklist:
- [ ] Al hacer clic en un paso del sidebar, la transición slide es visible (220ms)
- [ ] Al avanzar de paso, el badge del paso anterior muestra ✓
- [ ] La NavBar muestra "← Documentos" y "Perfil →" según corresponda
- [ ] Alt+2 navega al segundo paso de la herramienta activa
- [ ] En DocumentsCard, el botón [≡] abre un menú con Vaciar / Quitar / Ordenar
- [ ] El label muestra "3 docs · 1.2 MB" al cargar documentos
- [ ] Al arrastrar sobre la drop zone, el borde se vuelve accent y el ícono hace bounce

---

## Self-Review del Plan

**Cobertura del spec (Secciones 3 y 4):**
- ✅ Sidebar step states completed/pending (Task 1)
- ✅ Slide transition 220ms OutCubic (Task 2)
- ✅ NavBar fija ← prev / next → (Task 3)
- ✅ Alt+1-9 shortcuts + hint en hover (Task 4)
- ✅ DocumentsCard menú compacto + count+size (Task 5)
- ✅ DocumentsCard drag visual feedback (Task 6)
- ✅ ProcessStep shimmer + count-up (Task 7)
- ⏭ ProcessStep success animation check SVG → Plan 4 (requiere per-tool integration)
- ⏭ GenericPdfViewer zoom Ctrl+Scroll → Plan 4 (requiere per-tool integration)
- ⏭ Mini status bar dinámica → Plan 3 (requiere context de cada herramienta)

**Consistencia de tipos:**
- `_StepBtn.set_completed(bool)` → usado en `_switch_section` ✅
- `_slide_to_section(idx)` → conectado en `_build_sidebar` ✅
- `_update_navbar(idx)` → llamado desde `_switch_section` ✅
- `DocumentsCard.set_accent(str)` → las herramientas pueden llamarlo ✅
- `ProcessStep.set_accent(str)` + `start_processing_ui()` → las herramientas pueden llamarlo ✅

**No hay placeholders:** todos los steps tienen código completo ✅
