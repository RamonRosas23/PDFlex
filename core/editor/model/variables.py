"""Variables dinámicas de PDFlex Studio (spec §16).

Extiende la sintaxis probada de core/folio_format ({n}, {n:05}, {total}, {doc})
con {pagina}, {fecha[:formato strftime]} y {hora}. Tokens desconocidos se dejan
intactos (el usuario los ve y corrige; no se lanza error en render).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime

from core.folio_format import render as folio_render

_TOKEN = re.compile(r"\{(pagina|fecha|hora)(?::([^{}]+))?\}")


@dataclass(frozen=True)
class RenderContext:
    page: int                 # 1-based, página donde se renderiza la instancia
    total: int
    doc_name: str
    now: datetime
    folio_n: int = 1          # contador de folio (la regla folio lo incrementa)


def render_text(template: str, ctx: RenderContext) -> str:
    if "{" not in template:
        return template

    def _replace(m: re.Match) -> str:
        name, fmt = m.group(1), m.group(2)
        if name == "pagina":
            return str(ctx.page)
        if name == "fecha":
            return ctx.now.strftime(fmt or "%d/%m/%Y")
        if name == "hora":
            return ctx.now.strftime(fmt or "%H:%M")
        return m.group(0)

    out = _TOKEN.sub(_replace, template)
    # {n}, {n:05}, {total}, {doc} — sintaxis y semántica exactas del foleador
    out = folio_render(out, n=ctx.folio_n, doc_name=ctx.doc_name, total_pages=ctx.total)
    return out
