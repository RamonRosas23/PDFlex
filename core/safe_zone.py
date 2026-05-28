"""
Algoritmo de búsqueda de zona segura.

Dado un punto deseado para colocar la firma y un tamaño de firma,
busca la posición más cercana posible que:
  - No tape bloques de texto
  - Esté dentro de los márgenes de la página
  - Idealmente esté cerca de una línea de firma si la hay

Estrategia: búsqueda en espiral cuadrada alrededor del punto inicial,
con paso configurable. Si tras N intentos no encuentra zona libre,
devuelve la posición original (mejor algo que nada) y marca `clean=False`.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import math
import fitz

from .pdf_analyzer import PageAnalysis


@dataclass
class Placement:
    """Resultado de una colocación de firma."""
    x: float  # centro x (PDF coords)
    y: float  # centro y (PDF coords)
    width: float
    height: float
    angle: float  # grados, positivo = antihorario
    opacity: float = 1.0
    clean: bool = True  # True si no tapa texto ni se sale
    snapped_to_line: bool = False

    @property
    def rect(self) -> fitz.Rect:
        """Bounding box axis-aligned (sin rotación)."""
        return fitz.Rect(
            self.x - self.width / 2,
            self.y - self.height / 2,
            self.x + self.width / 2,
            self.y + self.height / 2,
        )

    @property
    def rotated_bbox(self) -> fitz.Rect:
        """Bounding box que envuelve la firma rotada."""
        if abs(self.angle) < 0.01:
            return self.rect
        rad = math.radians(self.angle)
        cos_a, sin_a = abs(math.cos(rad)), abs(math.sin(rad))
        new_w = self.width * cos_a + self.height * sin_a
        new_h = self.width * sin_a + self.height * cos_a
        return fitz.Rect(
            self.x - new_w / 2,
            self.y - new_h / 2,
            self.x + new_w / 2,
            self.y + new_h / 2,
        )


class SafeZoneFinder:
    """Encuentra colocaciones seguras de la firma en una página."""

    def __init__(
        self,
        margin: float = 18.0,
        text_padding: float = 4.0,
        spiral_step: float = 8.0,
        max_attempts: int = 80,
        snap_to_line_distance: float = 40.0,
    ):
        self.margin = margin
        self.text_padding = text_padding
        self.spiral_step = spiral_step
        self.max_attempts = max_attempts
        self.snap_to_line_distance = snap_to_line_distance

    def find_safe_placement(
        self,
        analysis: PageAnalysis,
        desired: Placement,
    ) -> Placement:
        """Devuelve una colocación segura cercana a la deseada."""
        # 1) ¿La deseada ya es válida?
        if self._is_valid(analysis, desired):
            snapped = self._try_snap_to_line(analysis, desired)
            if snapped is not None:
                return snapped
            return desired

        # 2) Búsqueda en espiral cuadrada
        best = self._spiral_search(analysis, desired)
        if best is not None:
            snapped = self._try_snap_to_line(analysis, best)
            if snapped is not None:
                return snapped
            return best

        # 3) Fallback duro: colócala en el último cuarto inferior, lejos del texto
        fallback = self._fallback_position(analysis, desired)
        if fallback is not None:
            return fallback

        # 4) Si todo falla, devuelve la deseada marcada como no-limpia
        return Placement(
            x=desired.x, y=desired.y,
            width=desired.width, height=desired.height,
            angle=desired.angle, opacity=desired.opacity,
            clean=False,
        )

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #

    def _is_valid(self, analysis: PageAnalysis, p: Placement) -> bool:
        bbox = p.rotated_bbox
        if not analysis.inside_page(bbox, margin=self.margin):
            return False
        if analysis.intersects_text(bbox, padding=self.text_padding):
            return False
        return True

    def _spiral_search(
        self, analysis: PageAnalysis, desired: Placement
    ) -> Optional[Placement]:
        """Búsqueda en espiral cuadrada alrededor del punto deseado."""
        step = self.spiral_step
        # Direcciones: derecha, abajo, izquierda, arriba
        dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        x, y = desired.x, desired.y
        leg = 1
        direction = 0
        attempts = 0

        while attempts < self.max_attempts:
            for _ in range(2):  # cada dos cambios de dirección, se incrementa la "pierna"
                dx, dy = dirs[direction]
                for _ in range(leg):
                    x += dx * step
                    y += dy * step
                    attempts += 1
                    candidate = Placement(
                        x=x, y=y,
                        width=desired.width, height=desired.height,
                        angle=desired.angle, opacity=desired.opacity,
                    )
                    if self._is_valid(analysis, candidate):
                        return candidate
                    if attempts >= self.max_attempts:
                        return None
                direction = (direction + 1) % 4
            leg += 1
        return None

    def _try_snap_to_line(
        self, analysis: PageAnalysis, p: Placement
    ) -> Optional[Placement]:
        """Si hay una línea de firma cerca, ajusta la firma sobre ella."""
        if not analysis.signature_lines:
            return None

        best_line = None
        best_dist = self.snap_to_line_distance
        for x0, y0, x1, y1 in analysis.signature_lines:
            cx = (x0 + x1) / 2
            cy = y0
            d = math.hypot(cx - p.x, cy - p.y)
            if d < best_dist:
                best_dist = d
                best_line = (x0, y0, x1, y1, cx, cy)

        if best_line is None:
            return None

        x0, y0, x1, y1, cx, cy = best_line
        # Colocar la firma centrada sobre la línea, ligeramente arriba
        new_x = cx
        new_y = cy - p.height / 2 - 2

        candidate = Placement(
            x=new_x, y=new_y,
            width=p.width, height=p.height,
            angle=p.angle, opacity=p.opacity,
            snapped_to_line=True,
        )
        if self._is_valid(analysis, candidate):
            return candidate
        return None

    def _fallback_position(
        self, analysis: PageAnalysis, desired: Placement
    ) -> Optional[Placement]:
        """Barrido en grilla del cuarto inferior buscando espacio."""
        step = max(self.spiral_step, 12)
        y_min = analysis.height * 0.55
        y_max = analysis.height - self.margin - desired.height / 2
        x_min = self.margin + desired.width / 2
        x_max = analysis.width - self.margin - desired.width / 2

        y = y_max
        while y > y_min:
            x = x_max
            while x > x_min:
                candidate = Placement(
                    x=x, y=y,
                    width=desired.width, height=desired.height,
                    angle=desired.angle, opacity=desired.opacity,
                )
                if self._is_valid(analysis, candidate):
                    return candidate
                x -= step
            y -= step
        return None
