"""
Algoritmo de búsqueda de zona segura.

Dado un punto deseado para colocar la firma y un tamaño de firma,
busca la posición más cercana posible que:
  - No tape bloques de texto
  - Esté dentro de los límites físicos de la página
  - Idealmente esté cerca de una línea de firma si la hay

Estrategia:
  1. Encajar siempre el bounding box rotado dentro del papel
  2. Si la posición deseada es segura → usarla (con posible snap a línea)
  3. Búsqueda en espiral pequeña alrededor del punto (radio máximo ~1.5cm)
  4. Barrido completo de la página, priorizando posiciones cercanas
  5. Si todo falla → conservar la posición físicamente limitada (clean=False)
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Iterable, Optional, Sequence, Tuple
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
    adjusted_to_page: bool = False
    scaled_to_fit: bool = False
    moved_to_safe_zone: bool = False
    collides_with_text: bool = False
    overlaps_signature: bool = False

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


def fit_placement_inside_page(
    placement: Placement,
    page_width: float,
    page_height: float,
    margin: float = 0.0,
) -> Placement:
    """Ajusta una firma para que su bbox rotado quede dentro de la página.

    Esta es la barrera física compartida por UI y motor. Si la firma no cabe,
    reduce ancho y alto proporcionalmente antes de limitar su centro.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError("El tamaño de página debe ser mayor que cero.")
    if placement.width <= 0 or placement.height <= 0:
        raise ValueError("El tamaño de firma debe ser mayor que cero.")

    safe_margin = max(0.0, float(margin))
    max_margin = max(0.0, min(page_width, page_height) / 2.0 - 1e-6)
    safe_margin = min(safe_margin, max_margin)
    available_w = max(1e-6, page_width - 2.0 * safe_margin)
    available_h = max(1e-6, page_height - 2.0 * safe_margin)

    result = placement
    bbox = result.rotated_bbox
    scale = min(1.0, available_w / bbox.width, available_h / bbox.height)
    scaled = scale < 1.0 - 1e-9
    if scaled:
        result = replace(
            result,
            width=result.width * scale,
            height=result.height * scale,
            adjusted_to_page=True,
            scaled_to_fit=True,
        )
        bbox = result.rotated_bbox

    half_w = bbox.width / 2.0
    half_h = bbox.height / 2.0
    min_x = safe_margin + half_w
    max_x = page_width - safe_margin - half_w
    min_y = safe_margin + half_h
    max_y = page_height - safe_margin - half_h

    # El escalado anterior garantiza que cada rango sea válido. El punto
    # medio evita pequeñas inversiones por precisión flotante.
    if min_x > max_x:
        min_x = max_x = page_width / 2.0
    if min_y > max_y:
        min_y = max_y = page_height / 2.0

    new_x = min(max(result.x, min_x), max_x)
    new_y = min(max(result.y, min_y), max_y)
    moved = abs(new_x - result.x) > 1e-7 or abs(new_y - result.y) > 1e-7
    if moved:
        result = replace(
            result,
            x=new_x,
            y=new_y,
            adjusted_to_page=True,
        )

    return result


class SafeZoneFinder:
    """Encuentra colocaciones seguras de la firma en una página."""

    def __init__(
        self,
        margin: float = 0.0,
        text_padding: float = 4.0,
        spiral_step: float = 6.0,
        max_attempts: int = 24,
        grid_step: float = 12.0,
        snap_to_line_distance: float = 40.0,
        signature_padding: float = 4.0,
    ):
        self.margin = margin
        self.text_padding = text_padding
        self.spiral_step = spiral_step
        self.max_attempts = max_attempts           # ≈ 24 pasos × 6pt = radio ~40pt
        self.grid_step = grid_step
        self.snap_to_line_distance = snap_to_line_distance
        self.signature_padding = signature_padding

    def find_safe_placement(
        self,
        analysis: PageAnalysis,
        desired: Placement,
        occupied_rects: Sequence[fitz.Rect] = (),
    ) -> Placement:
        """Devuelve una colocación lo más cerca posible de la deseada.

        Prioridades:
          1. Snap a línea de firma cercana
          2. Posición exacta deseada si es válida
          3. Espiral pequeña alrededor (~40pt radio)
          4. Barrido completo de la página, priorizando puntos cercanos
          5. Posición físicamente limitada (clean=False)
        """
        # La firma nunca puede salir físicamente del documento, incluso si no
        # existe una zona sin texto o sin otras firmas.
        bounded = fit_placement_inside_page(
            desired, analysis.width, analysis.height, margin=0.0
        )

        # 0) ¿Hay una línea de firma muy cerca? → snapear antes de validar
        snapped = self._try_snap_to_line(analysis, bounded, occupied_rects)
        if snapped is not None:
            return snapped

        # 1) ¿La deseada ya es válida?
        if self._is_valid(analysis, bounded, occupied_rects):
            return bounded

        # 2) Búsqueda en espiral pequeña (radio máximo ~40pt ≈ 1.4cm)
        best = self._spiral_search(analysis, bounded, occupied_rects)
        if best is not None:
            return best

        # 3) Si cerca no hay hueco, buscar toda la página antes de aceptar
        #    una colisión. Los candidatos se prueban por distancia.
        best = self._grid_search(analysis, bounded, occupied_rects)
        if best is not None:
            return best

        # 4) Fallback: respetar la intención del usuario tanto como sea
        #    posible, pero nunca permitir que la firma salga de la página.
        collides_text = analysis.intersects_text(
            bounded.rotated_bbox, padding=self.text_padding
        )
        overlaps_signature = self._intersects_occupied(
            bounded.rotated_bbox, occupied_rects
        )
        return replace(
            bounded,
            clean=False,
            collides_with_text=collides_text,
            overlaps_signature=overlaps_signature,
        )

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #

    def _is_valid(
        self,
        analysis: PageAnalysis,
        p: Placement,
        occupied_rects: Sequence[fitz.Rect] = (),
    ) -> bool:
        bbox = p.rotated_bbox
        if not analysis.inside_page(bbox, margin=self.margin):
            return False
        if analysis.intersects_text(bbox, padding=self.text_padding):
            return False
        if self._intersects_occupied(bbox, occupied_rects):
            return False
        return True

    def _spiral_search(
        self,
        analysis: PageAnalysis,
        desired: Placement,
        occupied_rects: Sequence[fitz.Rect] = (),
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
                        adjusted_to_page=desired.adjusted_to_page,
                        scaled_to_fit=desired.scaled_to_fit,
                        moved_to_safe_zone=True,
                    )
                    if self._is_valid(analysis, candidate, occupied_rects):
                        return candidate
                    if attempts >= self.max_attempts:
                        return None
                direction = (direction + 1) % 4
            leg += 1
        return None

    def _grid_search(
        self,
        analysis: PageAnalysis,
        desired: Placement,
        occupied_rects: Sequence[fitz.Rect] = (),
    ) -> Optional[Placement]:
        """Busca un hueco válido en toda la página, priorizando cercanía."""
        bbox = desired.rotated_bbox
        half_w = bbox.width / 2.0
        half_h = bbox.height / 2.0
        x0 = self.margin + half_w
        x1 = analysis.width - self.margin - half_w
        y0 = self.margin + half_h
        y1 = analysis.height - self.margin - half_h
        if x0 > x1 or y0 > y1:
            return None

        xs = self._axis_points(x0, x1, self.grid_step)
        ys = self._axis_points(y0, y1, self.grid_step)
        points = sorted(
            ((x, y) for x in xs for y in ys),
            key=lambda point: (
                (point[0] - desired.x) ** 2 + (point[1] - desired.y) ** 2,
                point[1],
                point[0],
            ),
        )
        for x, y in points:
            candidate = Placement(
                x=x,
                y=y,
                width=desired.width,
                height=desired.height,
                angle=desired.angle,
                opacity=desired.opacity,
                adjusted_to_page=desired.adjusted_to_page,
                scaled_to_fit=desired.scaled_to_fit,
                moved_to_safe_zone=True,
            )
            if self._is_valid(analysis, candidate, occupied_rects):
                return candidate
        return None

    @staticmethod
    def _axis_points(start: float, end: float, step: float) -> Tuple[float, ...]:
        """Genera puntos de barrido incluyendo siempre ambos extremos."""
        if end <= start:
            return (start,)
        safe_step = max(1.0, step)
        points = [start]
        current = start + safe_step
        while current < end:
            points.append(current)
            current += safe_step
        if abs(points[-1] - end) > 1e-7:
            points.append(end)
        return tuple(points)

    def _intersects_occupied(
        self,
        rect: fitz.Rect,
        occupied_rects: Iterable[fitz.Rect],
    ) -> bool:
        padding = self.signature_padding
        expanded = fitz.Rect(
            rect.x0 - padding,
            rect.y0 - padding,
            rect.x1 + padding,
            rect.y1 + padding,
        )
        return any(expanded.intersects(other) for other in occupied_rects)

    def _try_snap_to_line(
        self,
        analysis: PageAnalysis,
        p: Placement,
        occupied_rects: Sequence[fitz.Rect] = (),
    ) -> Optional[Placement]:
        """Si hay una línea de firma cerca, ajusta la firma sobre ella."""
        if not analysis.signature_lines:
            return None

        nearby_lines = []
        for x0, y0, x1, y1 in analysis.signature_lines:
            cx = (x0 + x1) / 2
            cy = y0
            d = math.hypot(cx - p.x, cy - p.y)
            if d < self.snap_to_line_distance:
                nearby_lines.append((d, x0, y0, x1, y1, cx, cy))

        for _, x0, y0, x1, y1, cx, cy in sorted(nearby_lines):
            # Colocar la firma centrada sobre la línea, ligeramente arriba
            candidate = Placement(
                x=cx,
                y=cy - p.height / 2 - 2,
                width=p.width,
                height=p.height,
                angle=p.angle,
                opacity=p.opacity,
                snapped_to_line=True,
                adjusted_to_page=p.adjusted_to_page,
                scaled_to_fit=p.scaled_to_fit,
                moved_to_safe_zone=True,
            )
            if self._is_valid(analysis, candidate, occupied_rects):
                return candidate
        return None
