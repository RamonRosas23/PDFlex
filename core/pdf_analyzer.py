"""
Análisis de páginas PDF: detección de texto, márgenes y zonas ocupadas.

Genera un mapa de "obstáculos" por página que el buscador de zona segura
consulta para decidir si una posición candidata de firma es válida.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple
import io
import fitz  # PyMuPDF


@dataclass
class TextBlock:
    """Bloque de texto detectado en una página, en coordenadas de PDF."""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str = ""
    is_signature_line: bool = False

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class PageAnalysis:
    """Análisis completo de una página."""
    page_index: int
    width: float
    height: float
    text_blocks: List[TextBlock] = field(default_factory=list)
    signature_lines: List[Tuple[float, float, float, float]] = field(default_factory=list)
    margin_left: float = 0.0
    margin_right: float = 0.0
    margin_top: float = 0.0
    margin_bottom: float = 0.0

    def intersects_text(self, rect: fitz.Rect, padding: float = 4.0) -> bool:
        """¿La caja `rect` (con padding) intersecta algún bloque de texto?"""
        expanded = fitz.Rect(
            rect.x0 - padding, rect.y0 - padding,
            rect.x1 + padding, rect.y1 + padding,
        )
        for block in self.text_blocks:
            if block.is_signature_line:
                continue
            if expanded.intersects(block.rect):
                return True
        return False

    def inside_page(self, rect: fitz.Rect, margin: float = 0.0) -> bool:
        """¿El rect está dentro de los límites de la página y del margen solicitado?"""
        return (
            rect.x0 >= margin
            and rect.y0 >= margin
            and rect.x1 <= self.width - margin
            and rect.y1 <= self.height - margin
        )


class PdfAnalyzer:
    """Analiza documentos PDF y produce un PageAnalysis por página."""

    def __init__(self, min_text_length: int = 1):
        self.min_text_length = min_text_length

    def analyze_document(self, pdf_path: str) -> List[PageAnalysis]:
        doc = fitz.open(pdf_path)
        try:
            return [self.analyze_page(doc, i) for i in range(doc.page_count)]
        finally:
            doc.close()

    def analyze_page(self, doc: fitz.Document, page_index: int) -> PageAnalysis:
        page = doc[page_index]
        rect = page.rect

        analysis = PageAnalysis(
            page_index=page_index,
            width=rect.width,
            height=rect.height,
        )

        # Extracción de bloques de texto con sus bounding boxes
        blocks = page.get_text("blocks") or []
        for b in blocks:
            if len(b) < 5:
                continue
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            if not isinstance(text, str):
                continue
            text = text.strip()
            if len(text) < self.min_text_length:
                continue
            is_signature_line = self._is_text_signature_line(text, x1 - x0)
            analysis.text_blocks.append(
                TextBlock(
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    text=text,
                    is_signature_line=is_signature_line,
                )
            )

        # Detectar líneas de firma (líneas horizontales típicas "__________")
        analysis.signature_lines = self._detect_signature_lines(page, analysis)

        # Calcular márgenes efectivos del contenido
        if analysis.text_blocks:
            analysis.margin_left = min(b.x0 for b in analysis.text_blocks)
            analysis.margin_right = rect.width - max(b.x1 for b in analysis.text_blocks)
            analysis.margin_top = min(b.y0 for b in analysis.text_blocks)
            analysis.margin_bottom = rect.height - max(b.y1 for b in analysis.text_blocks)

        return analysis

    def _detect_signature_lines(
        self, page: fitz.Page, analysis: PageAnalysis
    ) -> List[Tuple[float, float, float, float]]:
        """Detecta líneas horizontales largas y delgadas (típicas líneas de firma)."""
        lines: List[Tuple[float, float, float, float]] = []
        try:
            drawings = page.get_drawings()
        except Exception:
            return lines

        for d in drawings:
            for item in d.get("items", []):
                if not item or item[0] != "l":
                    continue
                try:
                    p1, p2 = item[1], item[2]
                    x0, x1 = min(p1.x, p2.x), max(p1.x, p2.x)
                    y0, y1 = min(p1.y, p2.y), max(p1.y, p2.y)
                except Exception:
                    continue
                # Línea horizontal larga (>= 60 pt) y fina
                if (x1 - x0) >= 60 and (y1 - y0) <= 2:
                    lines.append((x0, y0, x1, y1))

        # Buscar también texto que se vea como línea de firma (subrayados largos)
        for block in analysis.text_blocks:
            if block.is_signature_line:
                lines.append((block.x0, block.y0, block.x1, block.y1))

        return lines

    @staticmethod
    def _is_text_signature_line(text: str, width: float) -> bool:
        compact = text.replace(" ", "")
        return (
            len(compact) >= 8
            and set(compact).issubset({"_", "-", "."})
            and width >= 60
        )

    @staticmethod
    def suggest_signature_anchor(analysis: PageAnalysis) -> Tuple[float, float]:
        """
        Sugiere un punto de anclaje razonable para la firma:
        priorizando la línea de firma más baja; si no hay, la zona inferior derecha.
        """
        if analysis.signature_lines:
            # Tomar la línea de firma más cercana al pie de página
            line = max(analysis.signature_lines, key=lambda l: l[1])
            cx = (line[0] + line[2]) / 2
            cy = line[1] - 8  # un poco arriba de la línea
            return cx, cy

        # Fallback: zona inferior derecha
        return analysis.width * 0.72, analysis.height * 0.88
