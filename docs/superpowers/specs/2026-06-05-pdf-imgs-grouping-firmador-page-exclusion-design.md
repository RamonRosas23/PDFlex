# Design: PDF-to-Images Grouping + Firmador Page Exclusion
**Date:** 2026-06-05

---

## Feature 1 — PDF a Imágenes: Agrupación por documento

### Problem
When processing N PDFs, the engine already creates one temp subfolder per document, but
`_on_finished()` flattens all `ImageResult` objects into a single list. The viewer shows
all images mixed together, and "Guardar todo" copies them to a single flat folder.

### Architecture

**`core/pdf_to_images_engine.py`** — no changes needed. Already creates per-doc dirs.

**`ui/common/image_results_viewer.py`**
- New method `set_grouped_results(job_results: list)` accepts `List[PdfToImagesJobResult]`.
- Builds `_groups: List[_ResultGroup]` internally where each group has `(doc_name, doc_path, [ImageResult])`.
- Renders QListWidget with non-selectable header items (doc name + image count) followed by
  indented result items. Row-to-result mapping stored in `_row_map: List[Optional[int]]` where
  None = header row.
- Existing `set_results()` kept for backward compat (foleador, other tools).
- `_on_save_all()` detects grouped mode → calls new `save_grouped_files_as_batch()`.

**`ui/common/save_utils.py`**
- New `save_grouped_files_as_batch(parent, groups: list[tuple[str, list[str]]], ...)`.
- User picks one destination folder. Function creates `dest/doc_stem/` per group,
  copies images respecting conflict strategy (skip/replace).

**`ui/pdf_to_imgs/window.py`**
- `_on_finished()`: call `self._img_viewer.set_grouped_results(results)` instead of
  flattening to `all_img_results`.
- `_open_in_explorer()`: open `Path(output_path).parent` (already the per-doc subdir in temp).

### List visual design
```
┌──────────────────────────┐
│ 📄 contrato.pdf  3 imgs  │  ← group header (CardHint style, no hover, bg subtle)
│   contrato_p001.png      │
│   contrato_p002.png      │
│   contrato_p003.png      │
│ 📄 factura.pdf   2 imgs  │  ← group header
│   factura_p001.png       │
│   factura_p002.png       │
└──────────────────────────┘
```
Group headers use `background: #1A1A20; color: #9094A0; font-size: 11px; padding: 2px 6px`.

### Guardar todo flow
1. User clicks "Guardar todo".
2. Folder picker opens (starting in `Path.home()`).
3. For each group: `mkdir dest/doc_stem`, copy images resolving name conflicts.
4. Success dialog: "Se guardaron X imágenes en Y subcarpetas."

---

## Feature 2 — Firmador: Exclusión de páginas por firma (clic derecho)

### Problem
No mechanism exists to exclude a specific signature from individual pages. Existing
`_sig_disabled` only disables a sig for an entire document. `SignJob.pages` is global for
all sigs in the job (from the Intervals step).

### Architecture

**`core/signature_engine.py`**
- `SigPlacement`: add `excluded_pages: frozenset = field(default_factory=frozenset)`.
- `SignatureEngine._process_page()` (or equivalent per-sig loop): skip sig if
  `page_idx in sig_placement.excluded_pages`.

**`ui/pdf_preview.py`** — `PdfPreviewView`
- New signal: `sig_context_requested = pyqtSignal(str, int, object)` (uid, page_0based, QPoint).
- Override `contextMenuEvent`: hit-test via `scene.itemAt(pos, transform)`, walk up to find
  `SignatureItem`, emit `sig_context_requested` instead of showing menu (window handles menu).
- `SignatureItem`: new method `set_exclusion_state(excluded: bool)` → `setOpacity(0.28)` when
  excluded, 1.0 when normal. Paints a red diagonal strikethrough line over the sig bounding rect
  when excluded (drawn in `paint()`).
- `PdfPreviewView.refresh_page_exclusions(page_idx, excluded_uids: set[str])`: called on page
  navigation to apply opacity/strikethrough to each sig item.

**`ui/firmador/window.py`**
- New field: `_sig_page_exclusions: Dict[str, Dict[str, Set[int]]] = {}`.
  Shape: `uid → doc_path → {0-based page indices}`.
- Connect: `self.preview.sig_context_requested.connect(self._on_sig_context_menu)`.
- `_on_sig_context_menu(uid, page_idx, pos)`:
  - Build `QMenu` (styled to match app palette):
    - Header action (title, disabled): "Firma N · página P"
    - Separator
    - "✕  No firmar esta página" → `_on_exclude_current_page(uid, page_idx)`
    - "≡  Excluir intervalo..." → `_on_exclude_interval_dialog(uid)`
    - Separator (only if exclusions exist for this sig on this doc)
    - "↺  Restaurar exclusiones de esta firma" → `_on_restore_sig_exclusions(uid)`
- `_on_exclude_current_page(uid, page_idx)`: toggle logic — if already excluded, remove (restore).
- `_on_exclude_interval_dialog(uid)`: show `_PageExclusionDialog`, apply result to exclusions.
- `_on_restore_sig_exclusions(uid)`: clear `_sig_page_exclusions[uid][doc_path]`.
- `_on_page_changed(page_idx)`: already connected; extend to call
  `preview.refresh_page_exclusions(page_idx, excluded_uids_for_this_page)` and
  `_update_status_bar()`.
- `_update_status_bar()`: if current page has excluded sigs, append
  `● N excluida(s) en pág. P` (color `#E5484D`) to `_sb_sig_info`.
- `_build_jobs()`: include `excluded_pages=frozenset(...)` in each `SigPlacement`.

**New inner class `_PageExclusionDialog(QDialog)`** (defined in `window.py`):
- Compact dialog (400×200 px), same dark palette as app.
- Title: "Excluir firma '{label}' de páginas"
- Subtitle hint: "Documento: {doc_name} · {N} páginas totales"
- QLineEdit with placeholder "Ej: 2-5, 8, 10-final" — pre-filled with existing exclusions.
- Real-time validation: green "N páginas seleccionadas" or red error.
- Buttons: "Excluir" (primary) + "Cancelar".
- Uses existing `parse_page_intervals()` for validation.

### Context menu visual
```
┌────────────────────────────────────┐
│  Firma 1 · página 3                │  ← disabled title action
├────────────────────────────────────┤
│  ✕  No firmar esta página          │
│  ≡  Excluir intervalo de páginas…  │
├────────────────────────────────────┤
│  ↺  Restaurar exclusiones          │  ← only visible if exclusions exist
└────────────────────────────────────┘
```

### Excluded page visual (preview canvas)
- `SignatureItem` opacity drops to 28% (barely visible, still locatable).
- Red diagonal line drawn across the sig rect (`Qt.PenStyle.SolidLine`, width 2, color `#E5484D`).
- Tooltip on hover: "Esta firma está excluida en esta página. Clic derecho → Restaurar."

### Status bar badge
Normal state: `Firma 1 · 120×40 pt · (x=0.42, y=0.87)`
With exclusion: `Firma 1 · 120×40 pt · (x=0.42, y=0.87)  ●  1 excluida en pág. 3`

---

## Files changed

| File | Change |
|------|--------|
| `core/signature_engine.py` | `SigPlacement.excluded_pages` field + skip logic |
| `ui/pdf_preview.py` | `sig_context_requested` signal, `contextMenuEvent`, `SignatureItem.set_exclusion_state` |
| `ui/common/image_results_viewer.py` | `set_grouped_results()`, grouped list rendering, grouped save-all |
| `ui/common/save_utils.py` | `save_grouped_files_as_batch()` |
| `ui/pdf_to_imgs/window.py` | Use `set_grouped_results()` in `_on_finished()` |
| `ui/firmador/window.py` | Context menu handler, `_sig_page_exclusions`, `_PageExclusionDialog`, job builder update |

---

## Out of scope
- Persisting page exclusions across sessions (exclusions live only during the current run).
- Per-page placement offsets (signature position is the same for all pages it appears on).
- Undo/redo for exclusion actions.
