"""Parser y renderizador de máscaras de folio.

Sintaxis soportada:
    {n}         número de folio sin formato
    {n:05}      folio relleno con ceros a la izquierda, ancho mínimo 5
    {total}     total de páginas del lote o del documento
    {total:05}  idem con formato
    {doc}       nombre del archivo sin extensión

Ejemplos:
    {n:05}              → 00001, 00002 … 00100 … 10000
    FOLIO-{n:04}        → FOLIO-0001
    {doc}-{n:03}        → contrato-001 (reinicia por doc)
    {n:05}/{total:05}   → 00001/00123
    Pág. {n}            → Pág. 1, Pág. 2

Nota sobre el relleno:
    {n:05} significa "ancho mínimo 5, relleno izquierdo con ceros".
    El número NUNCA se trunca: el folio 100 es "00100" (5 chars),
    el folio 100000 es "100000" (6 chars).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Literal, List


# ====================================================================== #
#  Configuración
# ====================================================================== #

@dataclass
class FolioConfig:
    pattern: str = "{n:05}"
    start: int = 1
    step: int = 1
    scope: Literal["continuous", "per_doc"] = "continuous"
    skip_first_page: bool = False
    only_pages: List[int] | None = None   # 1-based; None = todas


# ====================================================================== #
#  Renderizador
# ====================================================================== #

_TOKEN = re.compile(r'\{(n|total|doc)(?::(\d+))?\}')


def render(
    pattern: str,
    n: int,
    doc_name: str = "",
    total_pages: int = 0,
) -> str:
    """Renderiza la máscara con los valores dados.

    El relleno de ceros es un ancho MÍNIMO: el número crece hacia la
    derecha sin truncarse.  {n:05} con n=100 → "00100", con n=10000 → "10000".
    """
    def _replace(m: re.Match) -> str:
        var = m.group(1)
        width = int(m.group(2)) if m.group(2) else 0
        if var == "n":
            return str(n).zfill(width) if width else str(n)
        if var == "total":
            return str(total_pages).zfill(width) if width else str(total_pages)
        if var == "doc":
            return doc_name
        return m.group(0)

    return _TOKEN.sub(_replace, pattern)


# ====================================================================== #
#  Validación
# ====================================================================== #

_KNOWN_VAR = re.compile(r'^(n|total|doc)(:\d+)?$')
_BRACE_CONTENT = re.compile(r'\{([^}]*)\}')


def validate_pattern(pattern: str) -> List[str]:
    """Retorna lista de mensajes de error; lista vacía si el patrón es válido."""
    errors: List[str] = []

    # Llaves desbalanceadas
    depth = 0
    for i, c in enumerate(pattern):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        if depth < 0:
            errors.append("Llave de cierre '}' sin apertura.")
            break
    if depth > 0:
        errors.append("Llave de apertura '{' sin cierre.")

    if not errors:
        for m in _BRACE_CONTENT.finditer(pattern):
            content = m.group(1)
            if not _KNOWN_VAR.match(content):
                errors.append(
                    f"Variable desconocida: {{{content}}}. "
                    "Variables válidas: n, total, doc (con formato opcional :NN)."
                )

    return errors


# ====================================================================== #
#  Preview de ejemplo
# ====================================================================== #

def preview_examples(cfg: FolioConfig, doc_name: str = "documento", n_show: int = 5) -> str:
    """Genera texto con N ejemplos de folios para mostrar en la UI."""
    lines = []
    n = cfg.start
    for i in range(n_show):
        folio = render(cfg.pattern, n, doc_name, total_pages=100)
        lines.append(f"  Página {i + 1}  →  {folio}")
        n += cfg.step
    if cfg.step != 0:
        lines.append("  …")
    return "\n".join(lines)
