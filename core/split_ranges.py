"""Modelo de rangos y validaciones para el Separador de PDF.

Un rango define un tramo de páginas que se extraerá a un archivo separado.
La notación de entrada acepta: "1-11", "15", "20-30".

Ejemplos de uso:
    parse_range_text("1-11")   → (1, 11)
    parse_range_text("5")      → (5, 5)
    parse_range_text("abc")    → "Formato inválido..."

    validate_ranges(ranges, total_pages=100)
    generate_equal_ranges(100, n=4)   → [(1,25), (26,50), (51,75), (76,100)]
    generate_one_per_page(5)           → [(1,1), (2,2), (3,3), (4,4), (5,5)]
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Literal, Tuple


# ====================================================================== #
#  Modelo
# ====================================================================== #

@dataclass
class SplitRange:
    """Un tramo de páginas que se extrae a un archivo PDF propio."""
    start: int          # 1-based, inclusive
    end: int            # 1-based, inclusive
    name: str = ""      # nombre del archivo de salida (sin extensión .pdf)

    @property
    def page_count(self) -> int:
        return self.end - self.start + 1


@dataclass
class ValidationIssue:
    kind: Literal["error", "warning"]
    message: str


# ====================================================================== #
#  Parser
# ====================================================================== #

def parse_range_text(text: str) -> Tuple[int, int] | str:
    """Parsea "X-Y" o "X". Retorna (start, end) o un mensaje de error."""
    text = text.strip()
    if not text:
        return "Ingresa un rango: 1-11 o una sola página: 5"

    if "-" in text:
        parts = text.split("-", 1)
        s, e = parts[0].strip(), parts[1].strip()
        if not s or not e:
            return "Formato inválido — escribe: 1-11"
        try:
            start, end = int(s), int(e)
        except ValueError:
            return "Formato inválido — solo se permiten números: 1-11"
        if start < 1 or end < 1:
            return "Las páginas deben ser números positivos (≥ 1)"
        if end < start:
            return f"El fin ({end}) debe ser mayor o igual al inicio ({start})"
        return (start, end)
    else:
        try:
            n = int(text)
        except ValueError:
            return "Formato inválido — escribe: 1-11 o una página: 5"
        if n < 1:
            return "La página debe ser un número positivo (≥ 1)"
        return (n, n)


# ====================================================================== #
#  Validación
# ====================================================================== #

def validate_ranges(
    ranges: List[SplitRange],
    total_pages: int,
) -> List[ValidationIssue]:
    """Verifica rangos, solapamientos y cobertura.

    Retorna lista vacía si todo está bien.  Los errores bloquean el
    proceso; las advertencias son informativas.
    """
    issues: List[ValidationIssue] = []

    for i, r in enumerate(ranges):
        if r.start < 1:
            issues.append(ValidationIssue(
                "error", f"Tramo {i+1}: la página inicial ({r.start}) debe ser ≥ 1"
            ))
        if total_pages > 0 and r.end > total_pages:
            issues.append(ValidationIssue(
                "error",
                f"Tramo {i+1}: la página final ({r.end}) excede "
                f"el total del documento ({total_pages})"
            ))
        if r.start > r.end:
            issues.append(ValidationIssue(
                "error",
                f"Tramo {i+1}: inicio ({r.start}) > fin ({r.end})"
            ))

    # Solapamientos
    for i in range(len(ranges)):
        for j in range(i + 1, len(ranges)):
            a, b = ranges[i], ranges[j]
            ov_s = max(a.start, b.start)
            ov_e = min(a.end, b.end)
            if ov_s <= ov_e:
                span = f"{ov_s}" if ov_s == ov_e else f"{ov_s}–{ov_e}"
                issues.append(ValidationIssue(
                    "error",
                    f"Tramos {i+1} y {j+1} se solapan en la{'s' if ov_s != ov_e else ''} "
                    f"página{'s' if ov_s != ov_e else ''} {span}"
                ))

    # Cobertura (advertencia si hay páginas sin tramo asignado)
    if ranges and total_pages > 0:
        covered: set[int] = set()
        for r in ranges:
            covered.update(range(r.start, r.end + 1))
        all_pages = set(range(1, total_pages + 1))
        missing = sorted(all_pages - covered)
        if missing:
            if len(missing) <= 6:
                desc = ", ".join(str(p) for p in missing)
            else:
                desc = f"{missing[0]}–{missing[-1]} ({len(missing)} páginas)"
            issues.append(ValidationIssue(
                "warning",
                f"Páginas sin tramo asignado: {desc} — no se incluirán en ningún archivo"
            ))

    return issues


# ====================================================================== #
#  Generadores rápidos
# ====================================================================== #

def generate_equal_ranges(total_pages: int, n: int) -> List[SplitRange]:
    """Divide total_pages en N partes lo más iguales posible."""
    if n <= 0 or total_pages <= 0:
        return []
    n = min(n, total_pages)  # no puede haber más partes que páginas
    base = total_pages // n
    extra = total_pages % n   # las primeras 'extra' partes tienen 1 pág más
    ranges: List[SplitRange] = []
    start = 1
    for i in range(n):
        size = base + (1 if i < extra else 0)
        end = start + size - 1
        ranges.append(SplitRange(start=start, end=end, name=f"parte-{i+1:02d}"))
        start = end + 1
    return ranges


def generate_one_per_page(total_pages: int) -> List[SplitRange]:
    """Crea un tramo por cada página del documento."""
    return [
        SplitRange(start=i + 1, end=i + 1, name=f"pag-{i+1:03d}")
        for i in range(total_pages)
    ]
