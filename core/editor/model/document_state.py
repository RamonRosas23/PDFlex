"""EditorDocument: estado completo del proyecto + resolución por página.

resolved_elements(page) es LA función que consumen el canvas y el exportador:
elementos concretos + instancias de reglas, con anclas resueltas al tamaño real
de la página, variables sustituidas, filtrado de ocultos y orden (z capa, z el.).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.editor.geometry import PageGeometry
from .layers import LayerStack
from .model_types import ResolvedElement
from .placement import resolve_frame
from .rules import PageRule
from .variables import RenderContext, render_text


@dataclass
class EditorDocument:
    source_path: str
    source_sha256: str
    page_geometries: list[PageGeometry]
    layers: LayerStack = field(default_factory=LayerStack)
    elements_by_page: dict[int, list] = field(default_factory=dict)   # 1-based
    rules: list[PageRule] = field(default_factory=list)
    assets: dict[str, bytes] = field(default_factory=dict)            # id → binario

    @property
    def page_count(self) -> int:
        return len(self.page_geometries)

    # ── mutaciones (las invocan los comandos del historial) ─────────
    def add_element(self, page: int, element) -> None:
        self.elements_by_page.setdefault(page, []).append(element)

    def remove_element(self, page: int, element_id: str):
        items = self.elements_by_page.get(page, [])
        for i, el in enumerate(items):
            if el.id == element_id:
                return items.pop(i)
        return None

    def add_rule(self, rule: PageRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> PageRule | None:
        for i, r in enumerate(self.rules):
            if r.id == rule_id:
                return self.rules.pop(i)
        return None

    # ── resolución ──────────────────────────────────────────────────
    def resolved_elements(self, page: int, now: datetime | None = None) -> list[ResolvedElement]:
        geo = self.page_geometries[page - 1]
        now = now or datetime.now()
        out: list[ResolvedElement] = []

        def _emit(el, from_rule_id: str | None) -> None:
            layer = self.layers.get(el.layer_id)
            if el.hidden or (layer is not None and not layer.visible):
                return
            frame = resolve_frame(el.frame, el.placement, geo)
            text = getattr(el, "text", None)
            if text is not None and getattr(el, "variables_enabled", False):
                ctx = RenderContext(page=page, total=self.page_count,
                                    doc_name=Path(self.source_path).stem,
                                    now=now, folio_n=page)
                text = render_text(text, ctx)
            layer_z = layer.z if layer is not None else 0
            layer_op = layer.opacity if layer is not None else 1.0
            out.append(ResolvedElement(
                element=el, frame=frame, text=text,
                effective_opacity=el.opacity * layer_op,
                layer_z=layer_z, from_rule_id=from_rule_id,
            ))

        for el in self.elements_by_page.get(page, []):
            _emit(el, None)
        for rule in self.rules:
            if page in rule.target.resolve(self.page_count, current_page=page):
                _emit(rule.element, rule.id)

        out.sort(key=lambda r: (r.layer_z, r.element.z))
        return out
