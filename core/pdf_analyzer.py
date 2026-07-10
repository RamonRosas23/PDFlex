"""
Análisis de páginas PDF: detección de texto, márgenes y zonas ocupadas.

Genera un mapa de "obstáculos" por página que el buscador de zona segura
consulta para decidir si una posición candidata de firma es válida.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple

from core.pdf_backend import PdfRenderDocument, Rect


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
    def rect(self) -> Rect:
        return Rect(self.x0, self.y0, self.x1, self.y1)

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

    def intersects_text(self, rect: Rect, padding: float = 4.0) -> bool:
        """¿La caja `rect` (con padding) intersecta algún bloque de texto?"""
        expanded = Rect(
            rect.x0 - padding, rect.y0 - padding,
            rect.x1 + padding, rect.y1 + padding,
        )
        for block in self.text_blocks:
            if block.is_signature_line:
                continue
            if expanded.intersects(block.rect):
                return True
        return False

    def inside_page(self, rect: Rect, margin: float = 0.0) -> bool:
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
        with PdfRenderDocument(pdf_path) as document:
            return [self.analyze_page(document, i) for i in range(document.page_count)]

    def analyze_page(
        self,
        document: PdfRenderDocument,
        page_index: int,
    ) -> PageAnalysis:
        page = document.page_info(page_index)

        analysis = PageAnalysis(
            page_index=page_index,
            width=page.width_pt,
            height=page.height_pt,
        )

        for block in document.text_blocks(page_index):
            text = block.text.strip()
            if len(text) < self.min_text_length:
                continue
            is_signature_line = self._is_text_signature_line(text, block.right - block.left)
            analysis.text_blocks.append(
                TextBlock(
                    x0=block.left,
                    y0=block.top,
                    x1=block.right,
                    y1=block.bottom,
                    text=text,
                    is_signature_line=is_signature_line,
                )
            )

        analysis.signature_lines = self._detect_signature_lines(
            document, page_index, analysis
        )

        # Calcular márgenes efectivos del contenido
        if analysis.text_blocks:
            analysis.margin_left = min(b.x0 for b in analysis.text_blocks)
            analysis.margin_right = page.width_pt - max(b.x1 for b in analysis.text_blocks)
            analysis.margin_top = min(b.y0 for b in analysis.text_blocks)
            analysis.margin_bottom = page.height_pt - max(b.y1 for b in analysis.text_blocks)

        return analysis

    def _detect_signature_lines(
        self,
        document: PdfRenderDocument,
        page_index: int,
        analysis: PageAnalysis,
    ) -> List[Tuple[float, float, float, float]]:
        """Detecta líneas horizontales largas y delgadas (típicas líneas de firma)."""
        lines: List[Tuple[float, float, float, float]] = []
        for path in document.object_bounds(page_index, kinds=("path",)):
            if path.width >= 60 and path.height <= 2:
                lines.append((path.left, path.top, path.right, path.bottom))

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
