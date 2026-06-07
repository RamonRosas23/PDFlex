# PDF-to-Images Grouping + Firmador Page Exclusion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) PDF-to-Images shows results grouped by document with per-doc subfolders on save; (2) Firmador adds right-click context menu on signatures in the preview to exclude them from specific pages or intervals.

**Architecture:** Feature 1 adds `set_grouped_results()` to `ImageResultsViewer` and `save_grouped_files_as_batch()` to `save_utils`, wiring them in `pdf_to_imgs/window.py`. Feature 2 adds `excluded_pages: frozenset` to `SigPlacement`, a `contextMenuEvent` + `set_exclusion_state()` to `pdf_preview.py`, and full exclusion management + `_PageExclusionDialog` to `firmador/window.py`.

**Tech Stack:** PyQt6, fitz (PyMuPDF), PIL, Python 3.10+

---

## File Map

| File | What changes |
|------|-------------|
| `ui/common/save_utils.py` | +`save_grouped_files_as_batch()` |
| `ui/common/image_results_viewer.py` | +`_ResultGroup` dataclass, +`set_grouped_results()`, grouped list rendering, grouped save-all |
| `ui/pdf_to_imgs/window.py` | `_on_finished()` → `set_grouped_results()` |
| `core/signature_engine.py` | `SigPlacement.excluded_pages` field + skip logic in `run_job()` |
| `ui/pdf_preview.py` | `sig_context_requested` signal, `contextMenuEvent`, `SignatureItem.set_exclusion_state()`, `PdfPreviewView.refresh_page_exclusions()` |
| `ui/firmador/window.py` | `_sig_page_exclusions` dict, context-menu handler, exclusion helpers, `_PageExclusionDialog`, `_build_jobs()` update, `_update_status_bar()` update |

---

## Task 1 — `save_utils.py`: grouped batch save

**Files:**
- Modify: `ui/common/save_utils.py`

- [ ] **Step 1: Add `save_grouped_files_as_batch` after the existing `save_files_as_batch` function**

Open `ui/common/save_utils.py` and add after line 88 (after `save_files_as_batch`):

```python
def save_grouped_files_as_batch(
    parent: QWidget,
    groups: list[tuple[str, list[str | Path]]],
    *,
    title: str = "Guardar todo",
    start_dir: str | Path | None = None,
) -> None:
    """Save images grouped into per-doc subfolders inside a chosen destination."""
    prepared: list[tuple[str, list[Path]]] = []
    total_files = 0
    for doc_stem, paths in groups:
        srcs = [Path(p) for p in paths if p and Path(p).exists()]
        if srcs:
            prepared.append((doc_stem, srcs))
            total_files += len(srcs)

    if total_files == 0:
        show_info(parent, title, "No hay archivos disponibles para guardar.")
        return

    folder = get_existing_directory(parent, title, str(start_dir or Path.home()))
    if not folder:
        return

    dest_root = Path(folder)

    conflicts: list[Path] = []
    for doc_stem, srcs in prepared:
        group_dir = dest_root / doc_stem
        for src in srcs:
            if (group_dir / src.name).exists():
                conflicts.append(group_dir / src.name)

    replace_existing = False
    skip_existing = False
    if conflicts:
        decision = _ask_conflict_strategy(parent, len(conflicts))
        if decision == "cancel":
            return
        replace_existing = decision == "replace"
        skip_existing = decision == "skip"

    copied = 0
    skipped = 0
    n_folders = 0
    errors: list[str] = []

    for doc_stem, srcs in prepared:
        group_dir = dest_root / doc_stem
        try:
            group_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            errors.append(f"{doc_stem}/: {exc}")
            continue
        n_folders += 1
        for src in srcs:
            dest = group_dir / src.name
            if dest.exists() and skip_existing:
                skipped += 1
                continue
            if dest.exists() and not replace_existing:
                skipped += 1
                continue
            try:
                shutil.copy2(str(src), str(dest))
                copied += 1
            except Exception as exc:
                errors.append(f"{src.name}: {exc}")

    folder_word = "subcarpeta" if n_folders == 1 else "subcarpetas"
    msg = f"Se guardaron {copied} imagen(es) en {n_folders} {folder_word}."
    if skipped:
        msg += f"\nSe omitieron {skipped} existente(s)."

    if errors:
        preview = "\n".join(errors[:5])
        if len(errors) > 5:
            preview += f"\n... y {len(errors) - 5} más"
        show_warning(parent, title, msg + f"\n\nErrores:\n{preview}")
    else:
        show_success(parent, title, msg)
```

Also add `show_info` to the import at the top of `save_utils.py` (it's already there in the existing imports — verify).

- [ ] **Step 2: Verify the import block at the top of `save_utils.py` includes `show_info`**

The existing import block already has `show_info`:
```python
from ui.common.dialogs import (
    DialogAction,
    choose_dialog_action,
    show_info,
    show_success,
    show_warning,
)
```
No change needed if it's already there.

- [ ] **Step 3: Commit**

```bash
git add ui/common/save_utils.py
git commit -m "feat(save_utils): add save_grouped_files_as_batch for per-doc subfolders"
```

---

## Task 2 — `image_results_viewer.py`: grouped results display

**Files:**
- Modify: `ui/common/image_results_viewer.py`

- [ ] **Step 1: Add imports at the top of `image_results_viewer.py`**

Add to the existing imports (after `from __future__ import annotations`):

```python
from dataclasses import dataclass
```

Add `QSize` to `PyQt6.QtCore` import line:
```python
from PyQt6.QtCore import Qt, QSize, pyqtSignal
```

Add `save_grouped_files_as_batch` to save_utils import:
```python
from ui.common.save_utils import save_files_as_batch, save_grouped_files_as_batch
```

- [ ] **Step 2: Add `_ResultGroup` dataclass just before `class ImageResultsViewer`**

```python
@dataclass
class _ResultGroup:
    doc_name: str      # e.g. "contrato.pdf"
    output_dir: str    # per-doc temp subfolder path
    results: list      # List[ImageResult]
```

- [ ] **Step 3: Add grouped state fields to `__init__`**

Inside `ImageResultsViewer.__init__`, after `self._source_dirs: list = []`, add:

```python
self._grouped: bool = False
self._flat_results: list = []   # flattened ImageResults when grouped
self._row_map: list = []        # list row → index into _flat_results, or None (header)
self._groups: list = []         # List[_ResultGroup]
```

- [ ] **Step 4: Add helper `_result_at_row`**

Add method after `set_source_dirs`:

```python
def _result_at_row(self, row: int):
    """Returns the ImageResult at the given list row, or None (header or out-of-range)."""
    if not self._grouped:
        if 0 <= row < len(self._results):
            return self._results[row]
        return None
    if 0 <= row < len(self._row_map):
        idx = self._row_map[row]
        if idx is not None and 0 <= idx < len(self._flat_results):
            return self._flat_results[idx]
    return None
```

- [ ] **Step 5: Add `set_grouped_results` method**

Add after `set_source_dirs`:

```python
def set_grouped_results(self, job_results: list) -> None:
    """Display results grouped by source PDF document.

    Accepts List[PdfToImagesJobResult].  Renders non-selectable group
    header items followed by indented image entries per document.
    """
    self._grouped = True
    self._groups = []
    self._flat_results = []
    self._row_map = []
    self._results = []
    self._source_dirs = []

    self.file_list.clear()

    for job_result in job_results:
        doc_name = Path(job_result.job.pdf_path).name
        out_dir = str(job_result.job.output_dir)
        group_results = list(job_result.image_results)
        self._groups.append(_ResultGroup(doc_name, out_dir, group_results))

        success_count = sum(1 for r in group_results if getattr(r, "success", False))
        img_word = "imagen" if success_count == 1 else "imágenes"

        # ── Group header (non-selectable) ────────────────────────────
        header = QListWidgetItem()
        header.setText(f"  {doc_name}  ·  {success_count} {img_word}")
        header.setIcon(icon("file-text", "#9094A0", 13))
        header.setFlags(Qt.ItemFlag.NoItemFlags)
        header.setSizeHint(QSize(200, 26))
        header.setForeground(QBrush(QColor("#9094A0")))
        header.setBackground(QBrush(QColor("#1A1A20")))
        font = header.font()
        font.setPointSize(9)
        header.setFont(font)
        self.file_list.addItem(header)
        self._row_map.append(None)

        # ── Result items ─────────────────────────────────────────────
        for r in group_results:
            out = getattr(r, "output_path", "") or ""
            name = "   " + Path(out).name if out else "   (error)"
            item = QListWidgetItem(name)
            item.setToolTip(out or name.strip())
            if not getattr(r, "success", False):
                item.setForeground(QBrush(QColor("#E5484D")))
                item.setIcon(icon("warning", "#E5484D", 16))
            self.file_list.addItem(item)
            self._row_map.append(len(self._flat_results))
            self._flat_results.append(r)

    if self._flat_results:
        # Select first real result (skip header at row 0)
        for i, v in enumerate(self._row_map):
            if v is not None:
                self.file_list.setCurrentRow(i)
                break
    else:
        self.clear_results()
```

- [ ] **Step 6: Update `clear_results` to reset grouped state**

Replace the existing `clear_results` body with:

```python
def clear_results(self) -> None:
    self._results = []
    self._source_dirs = []
    self._grouped = False
    self._flat_results = []
    self._row_map = []
    self._groups = []
    self.file_list.clear()
    self.preview_lbl.clear()
    self.meta_lbl.setText("")
    self.title_lbl.setText("Selecciona un archivo")
    self.open_file_btn.setEnabled(False)
    self.open_btn.setEnabled(False)
    self.save_as_btn.setEnabled(False)
    self.save_all_btn.setEnabled(False)
```

- [ ] **Step 7: Update `_on_file_selected` to use `_result_at_row`**

Replace the first five lines of `_on_file_selected`:

```python
def _on_file_selected(self) -> None:
    row = self.file_list.currentRow()
    if row < 0:
        return
    r = self._result_at_row(row)
    if r is None:
        # Header row or out-of-range — clear preview
        self.title_lbl.setText("Selecciona un archivo")
        self.meta_lbl.setText("")
        self.preview_lbl.clear()
        self.open_file_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self.save_all_btn.setEnabled(self._has_saveable_results())
        return
    # rest of method unchanged — just replace `r = self._results[row]` with the r we already have
    out = getattr(r, "output_path", "") or ""
    if not getattr(r, "success", False) or not out:
        self.title_lbl.setText("Error en este archivo")
        self.meta_lbl.setText(getattr(r, "error", "") or "")
        self.preview_lbl.clear()
        self.open_file_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.save_as_btn.setEnabled(False)
        self.save_all_btn.setEnabled(self._has_saveable_results())
        return

    path = Path(out)
    self.title_lbl.setText(path.name)
    self.open_file_btn.setEnabled(True)
    self.open_btn.setEnabled(True)
    self.save_as_btn.setEnabled(True)
    self.save_all_btn.setEnabled(self._has_saveable_results())

    pix = QPixmap(str(path))
    if pix.isNull():
        self.preview_lbl.clear()
        self.meta_lbl.setText("No se pudo previsualizar")
        return

    target_w = max(240, self.preview_lbl.width())
    target_h = max(220, self.preview_lbl.height())
    scaled = pix.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    self.preview_lbl.setPixmap(scaled)
    try:
        size_kb = path.stat().st_size / 1024
        size_str = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
        self.meta_lbl.setText(
            f"{pix.width()} x {pix.height()} px  ·  {size_str}"
        )
    except OSError:
        self.meta_lbl.setText(f"{pix.width()} x {pix.height()} px")
```

- [ ] **Step 8: Update `_saveable_paths` to handle grouped mode**

Replace `_saveable_paths`:

```python
def _saveable_paths(self) -> list[str]:
    source = self._flat_results if self._grouped else self._results
    return [
        getattr(r, "output_path", "")
        for r in source
        if (
            getattr(r, "success", False)
            and getattr(r, "output_path", "")
            and Path(getattr(r, "output_path", "")).exists()
        )
    ]
```

- [ ] **Step 9: Update `_on_save_as` to use `_result_at_row`**

Replace `_on_save_as`:

```python
def _on_save_as(self) -> None:
    row = self.file_list.currentRow()
    if row < 0:
        return
    r = self._result_at_row(row)
    if r is None:
        return
    out = getattr(r, "output_path", "") or ""
    if not getattr(r, "success", False) or not out or not Path(out).exists():
        return
    src_dir = str(Path(out).parent)
    suffix = Path(out).suffix.lower()
    filter_map = {
        ".png": "PNG (*.png)",
        ".jpg": "JPEG (*.jpg)",
        ".jpeg": "JPEG (*.jpg)",
        ".webp": "WebP (*.webp)",
    }
    file_filter = filter_map.get(suffix, f"Imagen (*{suffix})")
    new_path, _ = get_save_file_name(
        self,
        "Guardar como",
        str(Path(src_dir) / Path(out).name),
        file_filter,
    )
    if new_path:
        import shutil
        shutil.copy2(out, new_path)
```

- [ ] **Step 10: Update `_on_save_all` for grouped mode**

Replace `_on_save_all`:

```python
def _on_save_all(self) -> None:
    if self._grouped:
        groups: list[tuple[str, list[str]]] = []
        for g in self._groups:
            paths = [
                getattr(r, "output_path", "")
                for r in g.results
                if (
                    getattr(r, "success", False)
                    and getattr(r, "output_path", "")
                    and Path(getattr(r, "output_path", "")).exists()
                )
            ]
            if paths:
                stem = Path(g.output_dir).name
                groups.append((stem, paths))
        save_grouped_files_as_batch(
            self,
            groups,
            title="Guardar todo",
            start_dir=str(Path.home()),
        )
        return

    row = self.file_list.currentRow()
    start_dir = (
        self._source_dirs[row]
        if 0 <= row < len(self._source_dirs)
        else str(Path.home())
    )
    save_files_as_batch(
        self,
        self._saveable_paths(),
        title="Guardar todo",
        start_dir=start_dir,
    )
```

- [ ] **Step 11: Update `_on_open_file` and `_on_open` to use `_result_at_row`**

Replace both methods:

```python
def _on_open_file(self) -> None:
    row = self.file_list.currentRow()
    r = self._result_at_row(row)
    if r is not None:
        out = getattr(r, "output_path", "") or ""
        if out and Path(out).exists():
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

def _on_open(self) -> None:
    row = self.file_list.currentRow()
    r = self._result_at_row(row)
    if r is not None:
        out = getattr(r, "output_path", "") or ""
        if out:
            self.openInExplorer.emit(out)
```

- [ ] **Step 12: Commit**

```bash
git add ui/common/image_results_viewer.py
git commit -m "feat(image_results_viewer): grouped display by document with per-doc save-all"
```

---

## Task 3 — `pdf_to_imgs/window.py`: wire grouped results

**Files:**
- Modify: `ui/pdf_to_imgs/window.py`

- [ ] **Step 1: Update `_on_finished` to use `set_grouped_results`**

In `_on_finished`, replace:

```python
all_img_results: List[ImageResult] = []
ok_files = 0
for job_result in results:
    all_img_results.extend(job_result.image_results)
    ok_files += sum(1 for r in job_result.image_results if r.success)

output_paths = [r.output_path for r in all_img_results if r.success and r.output_path]
self._send_btn.set_output_paths(output_paths)
self.outputs_ready.emit(output_paths)

show_success(
    self, "Conversión completa",
    f"Se generaron {ok_files} imagen{'es' if ok_files != 1 else ''}.",
)
self._img_viewer.set_results(all_img_results)
src_dirs = [
    str(Path(jr.job.pdf_path).parent)
    for jr in results
    for _ in jr.image_results
]
self._img_viewer.set_source_dirs(src_dirs)
self._switch_section(3)
```

With:

```python
ok_files = sum(
    1 for jr in results for r in jr.image_results if r.success
)
output_paths = [
    r.output_path
    for jr in results
    for r in jr.image_results
    if r.success and r.output_path
]
self._send_btn.set_output_paths(output_paths)
self.outputs_ready.emit(output_paths)

show_success(
    self, "Conversión completa",
    f"Se generaron {ok_files} imagen{'es' if ok_files != 1 else ''}.",
)
self._img_viewer.set_grouped_results(results)
self._switch_section(3)
```

- [ ] **Step 2: Commit**

```bash
git add ui/pdf_to_imgs/window.py
git commit -m "feat(pdf_to_imgs): show results grouped by document, save to per-doc subfolders"
```

---

## Task 4 — `core/signature_engine.py`: per-sig page exclusions

**Files:**
- Modify: `core/signature_engine.py`

- [ ] **Step 1: Add `excluded_pages` field to `SigPlacement`**

Find the `SigPlacement` dataclass (around line 42) and add `excluded_pages` field:

```python
@dataclass
class SigPlacement:
    """Posición y tamaño de una firma individual dentro de un job."""
    signature_path: str
    base_x_norm: float
    base_y_norm: float
    base_width_pt: float
    base_height_pt: float
    base_angle: float = 0.0
    excluded_pages: frozenset = field(default_factory=frozenset)
```

Make sure `field` is imported from `dataclasses`. The existing import is:
```python
from dataclasses import dataclass, field
```
If `field` is not there, add it.

- [ ] **Step 2: Add skip-if-excluded check in `run_job`**

Inside `run_job`, in the inner loop `for sig_conf in job.signatures:` (around line 185), add the exclusion check as the very first line of the loop body:

```python
for sig_conf in job.signatures:
    if page_idx in sig_conf.excluded_pages:
        continue
    base_img = self._get_image(sig_conf.signature_path)
    # ... rest of loop unchanged ...
```

- [ ] **Step 3: Apply same skip in `preflight_bounds`**

Inside `preflight_bounds`, in the `for sig_conf in job.signatures:` loop (around line 136), add:

```python
for sig_conf in job.signatures:
    if page_idx in sig_conf.excluded_pages:
        continue
    desired = self._desired_placement(...)
```

- [ ] **Step 4: Commit**

```bash
git add core/signature_engine.py
git commit -m "feat(signature_engine): SigPlacement.excluded_pages for per-sig page skipping"
```

---

## Task 5 — `ui/pdf_preview.py`: context menu signal + exclusion visuals

**Files:**
- Modify: `ui/pdf_preview.py`

- [ ] **Step 1: Add `_excluded` field to `SignatureItem.__init__`**

In `SignatureItem.__init__`, after `self._active: bool = False`, add:

```python
self._excluded: bool = False
```

- [ ] **Step 2: Add `set_exclusion_state` method to `SignatureItem`**

Add after `set_pixmap`:

```python
def set_exclusion_state(self, excluded: bool) -> None:
    """Toggle the excluded visual: dim opacity + red X overlay."""
    if self._excluded == excluded:
        return
    self._excluded = excluded
    self.setOpacity(0.28 if excluded else 1.0)
    self.setToolTip(
        "Esta firma está excluida en esta página.\n"
        "Clic derecho → Restaurar para incluirla."
        if excluded else ""
    )
    self.update()
```

- [ ] **Step 3: Add red X overlay to `SignatureItem.paint`**

At the end of the `paint` method, after drawing border and handles, add:

```python
if self._excluded:
    x_pen = QPen(QColor("#E5484D"), 2.5)
    x_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(x_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = 6.0
    painter.drawLine(
        QPointF(inset, inset),
        QPointF(self._w - inset, self._h - inset),
    )
    painter.drawLine(
        QPointF(self._w - inset, inset),
        QPointF(inset, self._h - inset),
    )
```

- [ ] **Step 4: Add `sig_context_requested` signal to `PdfPreviewView`**

In the signals block of `PdfPreviewView` (after `pageChanged`), add:

```python
# Emitida cuando el usuario hace clic derecho sobre una firma
sig_context_requested = pyqtSignal(str, int, object)  # uid, page_0based, QPoint
```

- [ ] **Step 5: Add `contextMenuEvent` to `PdfPreviewView`**

Add method after `set_active_uid`:

```python
def contextMenuEvent(self, event) -> None:
    """Forward right-clicks on signature items as sig_context_requested signals."""
    scene_pos = self.mapToScene(event.pos())
    for item in self._scene.items(scene_pos):
        if isinstance(item, SignatureItem):
            self.sig_context_requested.emit(
                item.uid(), self._page_index, event.globalPos()
            )
            event.accept()
            return
    super().contextMenuEvent(event)
```

- [ ] **Step 6: Add `refresh_page_exclusions` to `PdfPreviewView`**

Add method after `contextMenuEvent`:

```python
def refresh_page_exclusions(self, excluded_uids: set) -> None:
    """Set visual exclusion state on all signature items for the current page."""
    for uid, item in self._sig_items.items():
        item.set_exclusion_state(uid in excluded_uids)
```

- [ ] **Step 7: Commit**

```bash
git add ui/pdf_preview.py
git commit -m "feat(pdf_preview): right-click context signal + signature exclusion visuals"
```

---

## Task 6 — `ui/firmador/window.py`: exclusion logic, dialog, status bar

**Files:**
- Modify: `ui/firmador/window.py`

### Step group A — imports and new fields

- [ ] **Step A1: Add `QMenu, QDialog` to PyQt6 imports**

Find the `from PyQt6.QtWidgets import (` block and add `QMenu, QDialog`:

```python
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFrame,
    QSpinBox, QCheckBox, QProgressBar,
    QGridLayout, QComboBox, QScrollArea, QLineEdit,
    QRadioButton, QButtonGroup, QAbstractItemView,
    QMenu, QDialog,
)
```

- [ ] **Step A2: Add `_sig_page_exclusions` field in `FirmadorWindow.__init__`**

In `__init__`, after `self._sig_disabled: Dict[str, Set[str]] = {}`, add:

```python
self._sig_page_exclusions: Dict[str, Dict[str, Set[int]]] = {}
# shape: uid → {doc_path → {0-based page indices to exclude}}
```

- [ ] **Step A3: Connect `sig_context_requested` in `_build_preview_section`**

In `_build_preview_section`, after the line:
```python
self.preview.pageChanged.connect(self._on_page_changed)
```
Add:
```python
self.preview.sig_context_requested.connect(self._on_sig_context_menu)
```

### Step group B — exclusion helpers

- [ ] **Step B1: Add `_get_excluded_uids_for_page` helper**

Add after `_sig_is_active`:

```python
def _get_excluded_uids_for_page(self, doc_path: str, page_idx: int) -> set:
    """Returns the set of sig UIDs excluded on the given page of the given doc."""
    return {
        uid
        for uid, doc_map in self._sig_page_exclusions.items()
        if page_idx in doc_map.get(doc_path, set())
    }
```

- [ ] **Step B2: Add `_refresh_page_exclusion_view` helper**

Add after `_get_excluded_uids_for_page`:

```python
def _refresh_page_exclusion_view(self) -> None:
    """Pushes current exclusion state to the preview canvas and status bar."""
    if self._active_doc_idx < 0:
        return
    doc_path = self.pdf_paths[self._active_doc_idx]
    page_idx = self.preview.current_page()
    excluded = self._get_excluded_uids_for_page(doc_path, page_idx)
    self.preview.refresh_page_exclusions(excluded)
    self._update_status_bar()
```

- [ ] **Step B3: Add `_on_exclude_current_page` handler**

```python
def _on_exclude_current_page(self, uid: str, page_idx: int) -> None:
    """Toggle exclusion of a single page for one signature."""
    if self._active_doc_idx < 0:
        return
    doc_path = self.pdf_paths[self._active_doc_idx]
    exclusions = (
        self._sig_page_exclusions
        .setdefault(uid, {})
        .setdefault(doc_path, set())
    )
    if page_idx in exclusions:
        exclusions.discard(page_idx)
    else:
        exclusions.add(page_idx)
    if not exclusions:
        self._sig_page_exclusions[uid].pop(doc_path, None)
    self._refresh_page_exclusion_view()
```

- [ ] **Step B4: Add `_on_exclude_interval_dialog` handler**

```python
def _on_exclude_interval_dialog(self, uid: str) -> None:
    """Open the interval exclusion dialog for one signature on the active doc."""
    entry = self._entry_for_uid(uid)
    if not entry or self._active_doc_idx < 0:
        return
    doc_path = self.pdf_paths[self._active_doc_idx]
    total = self._page_count_for_doc(doc_path)
    current = sorted(
        self._sig_page_exclusions.get(uid, {}).get(doc_path, set())
    )
    prefill = compact_page_intervals(current) if current else ""

    dlg = _PageExclusionDialog(
        self,
        sig_label=entry.label,
        doc_name=Path(doc_path).name,
        total_pages=total,
        prefill=prefill,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    new_pages = dlg.result_pages()
    if new_pages:
        self._sig_page_exclusions.setdefault(uid, {})[doc_path] = set(new_pages)
    else:
        self._sig_page_exclusions.get(uid, {}).pop(doc_path, None)
    self._refresh_page_exclusion_view()
```

- [ ] **Step B5: Add `_on_restore_sig_exclusions` handler**

```python
def _on_restore_sig_exclusions(self, uid: str) -> None:
    """Clear all page exclusions for one signature on the active document."""
    if self._active_doc_idx < 0:
        return
    doc_path = self.pdf_paths[self._active_doc_idx]
    self._sig_page_exclusions.get(uid, {}).pop(doc_path, None)
    self._refresh_page_exclusion_view()
```

### Step group C — context menu

- [ ] **Step C1: Add `_on_sig_context_menu` handler**

```python
def _on_sig_context_menu(self, uid: str, page_idx: int, pos) -> None:
    """Show the right-click context menu for a signature on a specific page."""
    entry = self._entry_for_uid(uid)
    if not entry or self._active_doc_idx < 0:
        return
    doc_path = self.pdf_paths[self._active_doc_idx]

    is_excluded = page_idx in (
        self._sig_page_exclusions.get(uid, {}).get(doc_path, set())
    )
    has_any_exclusions = bool(
        self._sig_page_exclusions.get(uid, {}).get(doc_path)
    )

    menu = QMenu(self)
    menu.setStyleSheet("""
        QMenu {
            background-color: #1E1E26;
            border: 1px solid #32323C;
            border-radius: 6px;
            padding: 4px 0px;
            font-size: 13px;
        }
        QMenu::item {
            color: #ECEDEE;
            padding: 7px 20px 7px 14px;
            border-radius: 4px;
            margin: 1px 4px;
        }
        QMenu::item:selected {
            background-color: #2A2A38;
        }
        QMenu::item:disabled {
            color: #6B6E7A;
            background: transparent;
        }
        QMenu::separator {
            height: 1px;
            background: #32323C;
            margin: 4px 10px;
        }
    """)

    title_act = menu.addAction(f"{entry.label}  ·  página {page_idx + 1}")
    title_act.setEnabled(False)
    menu.addSeparator()

    if is_excluded:
        toggle_act = menu.addAction("✓  Incluir esta página")
    else:
        toggle_act = menu.addAction("✕  No firmar esta página")

    interval_act = menu.addAction("≡  Excluir intervalo de páginas…")

    restore_act = None
    if has_any_exclusions:
        menu.addSeparator()
        restore_act = menu.addAction("↺  Restaurar todas las exclusiones")

    chosen = menu.exec(pos)

    if chosen == toggle_act:
        self._on_exclude_current_page(uid, page_idx)
    elif chosen == interval_act:
        self._on_exclude_interval_dialog(uid)
    elif restore_act is not None and chosen == restore_act:
        self._on_restore_sig_exclusions(uid)
```

### Step group D — page change + status bar + job builder

- [ ] **Step D1: Update `_on_page_changed` to refresh exclusion view**

Replace the existing `_on_page_changed`:

```python
def _on_page_changed(self, cur: int, total: int) -> None:
    self._update_status_bar()
    if self._active_doc_idx >= 0:
        doc_path = self.pdf_paths[self._active_doc_idx]
        excluded = self._get_excluded_uids_for_page(doc_path, cur)
        self.preview.refresh_page_exclusions(excluded)
```

- [ ] **Step D2: Update `_update_status_bar` to append exclusion badge**

At the end of `_update_status_bar`, replace the final `self._sb_sig_info.setText(...)` call:

```python
cx_n, cy_n, w_pt, h_pt, angle = p
r = entry.color.red()
g = entry.color.green()
b = entry.color.blue()
info_html = (
    f"<b style='color:rgb({r},{g},{b});'>{entry.label}</b>"
    f"&nbsp;&nbsp;·&nbsp;&nbsp;"
    f"x&nbsp;{cx_n*100:.0f}%&nbsp;&nbsp;y&nbsp;{cy_n*100:.0f}%"
    f"&nbsp;&nbsp;·&nbsp;&nbsp;"
    f"{w_pt:.0f}&thinsp;×&thinsp;{h_pt:.0f}&nbsp;pt"
    f"&nbsp;&nbsp;·&nbsp;&nbsp;{angle:+.1f}°"
)

# Exclusion badge for current page
if self._active_doc_idx >= 0:
    doc_path = self.pdf_paths[self._active_doc_idx]
    page_idx = self.preview.current_page()
    active_uids = {
        e.uid for e in self._sigs if self._sig_is_active(e.uid, doc_path)
    }
    n_excl = len(
        self._get_excluded_uids_for_page(doc_path, page_idx) & active_uids
    )
    if n_excl:
        label = "excluida" if n_excl == 1 else "excluidas"
        info_html += (
            f"&nbsp;&nbsp;&nbsp;"
            f"<span style='color:#E5484D;'>● {n_excl} {label} "
            f"en pág.&nbsp;{page_idx + 1}</span>"
        )

self._sb_sig_info.setText(info_html)
```

- [ ] **Step D3: Update `_build_jobs` to pass `excluded_pages` to `SigPlacement`**

In `_build_jobs`, replace the `sig_placements.append(SigPlacement(...))` call:

```python
sig_placements.append(SigPlacement(
    signature_path=self._get_sig_path_for_job(e),
    base_x_norm=cx_n,
    base_y_norm=cy_n,
    base_width_pt=w_frac * page_w_pt,
    base_height_pt=h_frac * page_h_pt,
    base_angle=angle,
    excluded_pages=frozenset(
        self._sig_page_exclusions.get(e.uid, {}).get(pdf_path, set())
    ),
))
```

### Step group E — cleanup hooks

- [ ] **Step E1: Update `_reset_session` to clear exclusions**

In `_reset_session`, after `self._sig_disabled.clear()`, add:

```python
self._sig_page_exclusions.clear()
```

- [ ] **Step E2: Update `_on_delete_doc` to clean exclusions for deleted doc**

In `_on_delete_doc`, after the line `self._sig_disabled[uid].discard(doc_path)`, add:

```python
for uid in list(self._sig_page_exclusions):
    self._sig_page_exclusions[uid].pop(doc_path, None)
```

### Step group F — `_PageExclusionDialog`

- [ ] **Step F1: Add `_PageExclusionDialog` class at the bottom of `firmador/window.py`** (before or after `FirmadorWindow`, as a module-level class)

Add this class at the end of the file (after the `FirmadorWindow` class closing):

```python
class _PageExclusionDialog(QDialog):
    """Compact dialog to configure page exclusions for one signature."""

    def __init__(
        self,
        parent,
        *,
        sig_label: str,
        doc_name: str,
        total_pages: int,
        prefill: str = "",
    ) -> None:
        super().__init__(parent)
        self._total_pages = total_pages
        self._result: list[int] = []

        self.setWindowTitle("Excluir páginas")
        self.setFixedSize(460, 230)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        title_lbl = QLabel(f"Excluir <b>{sig_label}</b> de páginas seleccionadas")
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("font-size: 14px; color: #ECEDEE;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(
            f"Documento: {doc_name}  ·  {total_pages} "
            f"página{'s' if total_pages != 1 else ''} en total"
        )
        sub_lbl.setProperty("class", "CardHint")
        layout.addWidget(sub_lbl)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Ej: 2-5, 8, 10-final")
        self._edit.setText(prefill)
        self._edit.textChanged.connect(self._validate)
        layout.addWidget(self._edit)

        self._status_lbl = QLabel("")
        self._status_lbl.setProperty("class", "CardHint")
        self._status_lbl.setWordWrap(True)
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setProperty("class", "Ghost")
        cancel_btn.clicked.connect(self.reject)
        self._accept_btn = QPushButton("Aplicar exclusiones")
        self._accept_btn.setProperty("class", "Primary")
        self._accept_btn.setMinimumWidth(160)
        self._accept_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._accept_btn)
        layout.addLayout(btn_row)

        self._validate(prefill)

    def _validate(self, text: str) -> None:
        if not text.strip():
            self._status_lbl.setText(
                "Sin páginas seleccionadas — acepta para limpiar las exclusiones actuales."
            )
            self._status_lbl.setStyleSheet("color: #9094A0;")
            self._result = []
            self._accept_btn.setEnabled(True)
            return
        try:
            pages = parse_page_intervals(text, self._total_pages)
            count = len(pages)
            self._result = pages
            label = "página" if count == 1 else "páginas"
            compact = compact_page_intervals(pages)
            self._status_lbl.setText(f"{count} {label} excluidas: {compact}")
            self._status_lbl.setStyleSheet("color: #3BD37C;")
            self._accept_btn.setEnabled(True)
        except ValueError as exc:
            self._status_lbl.setText(str(exc))
            self._status_lbl.setStyleSheet("color: #E5484D;")
            self._result = []
            self._accept_btn.setEnabled(False)

    def result_pages(self) -> list[int]:
        """Returns validated 0-based page indices to exclude."""
        return list(self._result)
```

- [ ] **Step F2: Commit everything in firmador**

```bash
git add ui/firmador/window.py
git commit -m "feat(firmador): right-click page exclusion — context menu, dialog, status badge"
```

---

## Self-Review

### Spec coverage check
- [x] PDF-to-Images grouped list with document headers → Task 2
- [x] Guardar todo creates per-doc subfolders → Tasks 1 + 2
- [x] `SigPlacement.excluded_pages` + engine skip → Task 4
- [x] `contextMenuEvent` on canvas → Task 5
- [x] `sig_context_requested` signal → Task 5
- [x] `set_exclusion_state` (opacity + red X) → Task 5
- [x] `refresh_page_exclusions` → Task 5
- [x] Context menu with toggle / interval / restore → Task 6 C1
- [x] `_on_page_changed` → refreshes exclusion visuals → Task 6 D1
- [x] Status bar exclusion badge → Task 6 D2
- [x] `_build_jobs` passes `excluded_pages` → Task 6 D3
- [x] `_reset_session` clears exclusions → Task 6 E1
- [x] `_on_delete_doc` cleans exclusions for removed doc → Task 6 E2
- [x] `_PageExclusionDialog` → Task 6 F1

### Type consistency
- `sig_context_requested = pyqtSignal(str, int, object)` → emitted in Task 5 as `(item.uid(), self._page_index, event.globalPos())` → consumed in Task 6 as `(uid: str, page_idx: int, pos)` ✓
- `SigPlacement.excluded_pages: frozenset` → built in Task 6 D3 as `frozenset(set)` ✓ → consumed in Task 4 as `if page_idx in sig_conf.excluded_pages` ✓
- `_sig_page_exclusions: Dict[str, Dict[str, Set[int]]]` → written in Task 6 B3/B4/B5 → read in B1/B2/D2/D3/E1/E2 ✓
- `set_grouped_results` accepts `List[PdfToImagesJobResult]` → called in Task 3 with `results` from `PdfToImgsWorker.finished` ✓
- `_result_at_row` returns `ImageResult | None` → callers all guard for None ✓
