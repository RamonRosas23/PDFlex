"""Exportador: EditorDocument → PDF nuevo. NUNCA toca el original (spec §15).

Flujo: abrir copia del fuente → por página: resolved_elements() → primitivas
rotación-seguras → guardar a temporal → verificar → respaldo del destino si
existe → os.replace atómico. Contrato de progreso idéntico a los engines de
la suite: progress(current, total, msg) + should_cancel().
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import fitz

from core.editor.geometry import PageGeometry
from core.editor.image_engine import prepare_image_bytes
from core.editor.model.document_state import EditorDocument
from core.editor.model.model_types import ResolvedElement
from core.editor.text_engine import alignment_flag, resolve_font
from .backup import backup_existing
from .primitives import stamp_image, stamp_image_rotated, stamp_rect, stamp_text
from .verifier import verify_pdf


@dataclass(frozen=True)
class ExportOptions:
    garbage: int = 3
    deflate: bool = True


@dataclass
class ExportResult:
    output_path: str = ""
    success: bool = False
    error: str = ""
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)


class Exporter:
    def export(self, doc: EditorDocument, output_path: Path,
               options: ExportOptions,
               progress: Callable[[int, int, str], None] | None = None,
               should_cancel: Callable[[], bool] | None = None) -> ExportResult:
        output_path = Path(output_path)
        result = ExportResult(output_path=str(output_path))
        tmp = output_path.with_suffix(".tmp.pdf")
        total = doc.page_count
        try:
            with fitz.open(doc.source_path) as pdf:
                for page_no in range(1, total + 1):
                    if should_cancel and should_cancel():
                        result.error = "Exportación cancelada por el usuario"
                        return result
                    if progress:
                        progress(page_no - 1, total, f"Exportando página {page_no}")
                    page = pdf[page_no - 1]
                    geo = doc.page_geometries[page_no - 1]
                    for res in doc.resolved_elements(page_no):
                        self._stamp(page, geo, res, doc, result)
                pdf.save(str(tmp), garbage=options.garbage, deflate=options.deflate)

            ok, msg = verify_pdf(tmp, expected_pages=total)
            if not ok:
                result.error = f"Verificación fallida: {msg}"
                return result
            backup_existing(output_path)
            os.replace(tmp, output_path)
            result.success = True
            result.page_count = total
            if progress:
                progress(total, total, "Exportación completada")
            return result
        except Exception as exc:                  # noqa: BLE001 — se reporta
            result.error = f"Error al exportar: {exc}"
            return result
        finally:
            if tmp.exists() and not result.success:
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------
    def _stamp(self, page: fitz.Page, geo: PageGeometry, res: ResolvedElement,
               doc: EditorDocument, result: ExportResult) -> None:
        el = res.element
        rect = fitz.Rect(res.frame.x, res.frame.y,
                         res.frame.x + res.frame.w, res.frame.y + res.frame.h)
        if el.kind == "text":
            if el.box_fill is not None:
                stamp_rect(page, geo, rect, fill=el.box_fill,
                           opacity=el.box_fill_opacity * res.effective_opacity)
            leftover = stamp_text(
                page, geo, rect, res.text if res.text is not None else el.text,
                fontsize=el.font_size,
                fontname=resolve_font(el.font_family, bold=el.bold, italic=el.italic),
                color=el.color, opacity=res.effective_opacity,
                align=alignment_flag(el.align), angle_deg=el.rotation_deg)
            if leftover < 0:
                result.warnings.append(
                    f"Página {geo.index + 1}: el texto {el.id[:8]} no cupo completo "
                    f"en su caja (faltaron {-leftover:.0f} pt)")
        elif el.kind == "image":
            data = doc.assets[el.asset_id]
            data = prepare_image_bytes(data, opacity=res.effective_opacity,
                                       crop=el.crop, flip_h=el.flip_h,
                                       flip_v=el.flip_v)
            if el.rotation_deg:
                stamp_image_rotated(page, geo, rect, data, angle_deg=el.rotation_deg)
            else:
                stamp_image(page, geo, rect, data)
