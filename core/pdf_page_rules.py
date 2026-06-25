"""Page-aware compression rule parsing and planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid


@dataclass(frozen=True)
class PageRulePreset:
    id: str
    label: str
    profile_id: str
    color: str
    excluded: bool = False
    description: str = ""


PAGE_RULE_PRESETS: dict[str, PageRulePreset] = {
    "exclude": PageRulePreset(
        id="exclude",
        label="No comprimir",
        profile_id="quality",
        color="#60A5FA",
        excluded=True,
        description="Protege paginas sensibles de recomprimir imagenes.",
    ),
    "quality": PageRulePreset(
        id="quality",
        label="Alta legibilidad",
        profile_id="quality",
        color="#3BD37C",
        description="Conservador para tablas, sellos, firmas o letras pequenas.",
    ),
    "balanced": PageRulePreset(
        id="balanced",
        label="Equilibrado",
        profile_id="balanced",
        color="#FACC15",
        description="Balance entre tamano y legibilidad.",
    ),
    "email": PageRulePreset(
        id="email",
        label="Maxima reduccion",
        profile_id="email",
        color="#F87171",
        description="Compresion agresiva para paginas visuales o anexos pesados.",
    ),
    "custom": PageRulePreset(
        id="custom",
        label="Personalizado",
        profile_id="balanced",
        color="#A78BFA",
        description="Usa parametros propios de DPI, calidad y validacion.",
    ),
}

_PRESET_ALIASES = {
    "no_comprimir": "exclude",
    "skip": "exclude",
    "omit": "exclude",
    "alta": "quality",
    "alta_legibilidad": "quality",
    "legibility": "quality",
    "max": "email",
    "maxima": "email",
    "maximum": "email",
    "correo": "email",
    "personal": "custom",
    "personalizado": "custom",
}


@dataclass(frozen=True)
class PageCompressionRule:
    page_spec: str
    preset: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    label: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    def normalized_preset(self) -> str:
        return normalize_rule_preset(self.preset)


@dataclass(frozen=True)
class EffectivePageCompression:
    page_index: int
    preset: str
    profile_id: str
    source_rule_id: str | None
    label: str
    color: str
    excluded: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageCompressionPlan:
    page_count: int
    effective: list[EffectivePageCompression]
    explicit_rules: list[PageCompressionRule] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_explicit_rules(self) -> bool:
        return bool(self.explicit_rules)

    @property
    def pages_excluded(self) -> int:
        return sum(1 for item in self.effective if item.excluded)

    @property
    def pages_custom(self) -> int:
        return sum(1 for item in self.effective if item.preset == "custom")

    @property
    def pages_with_rules(self) -> int:
        return sum(1 for item in self.effective if item.source_rule_id)

    @property
    def pages_compressible(self) -> int:
        return sum(1 for item in self.effective if not item.excluded)

    @property
    def summary(self) -> str:
        if not self.has_explicit_rules:
            return "Sin reglas por pagina"
        parts = [
            f"{self.pages_with_rules}/{self.page_count} paginas con regla",
            f"{self.pages_excluded} sin comprimir",
        ]
        if self.pages_custom:
            parts.append(f"{self.pages_custom} personalizadas")
        return " · ".join(parts)

    def rule_for_page(self, page_index: int) -> EffectivePageCompression:
        return self.effective[page_index]


def normalize_rule_preset(value: str) -> str:
    preset = (value or "balanced").strip().lower().replace(" ", "_").replace("-", "_")
    preset = _PRESET_ALIASES.get(preset, preset)
    if preset not in PAGE_RULE_PRESETS:
        raise ValueError("Preset de regla no reconocido.")
    return preset


def parse_page_spec(text: str, page_count: int) -> list[int]:
    """Parse a user page range into 0-based page indexes."""
    if page_count <= 0:
        raise ValueError("El PDF no tiene paginas.")
    raw = (text or "").strip().lower()
    if not raw:
        raise ValueError("Escribe un rango de paginas.")
    normalized = (
        raw.replace(";", ",")
        .replace(" y ", ",")
        .replace(" paginas ", " ")
        .replace(" pagina ", " ")
    )
    if normalized in {"todo", "todas", "todos", "all", "*", "1-final", "1-fin"}:
        return list(range(page_count))
    if normalized in {"pares", "par", "even"}:
        return [idx for idx in range(page_count) if (idx + 1) % 2 == 0]
    if normalized in {"impares", "impar", "odd"}:
        return [idx for idx in range(page_count) if (idx + 1) % 2 == 1]

    selected: set[int] = set()
    tokens = [
        token.strip()
        for chunk in normalized.split(",")
        for token in chunk.split()
        if token.strip()
    ]
    for token in tokens:
        if "-" in token:
            left, right = token.split("-", 1)
            start = _parse_page_token(left, page_count, default=1)
            end = _parse_page_token(right, page_count, default=page_count)
            if start > end:
                raise ValueError(f"Rango invertido: {token}")
            selected.update(range(start - 1, end))
        else:
            selected.add(_parse_page_token(token, page_count) - 1)

    if not selected:
        raise ValueError("El rango no contiene paginas validas.")
    return sorted(selected)


def build_page_compression_plan(
    page_count: int,
    global_profile_id: str,
    rules: list[PageCompressionRule] | None = None,
) -> PageCompressionPlan:
    if page_count <= 0:
        raise ValueError("El PDF no tiene paginas.")

    global_profile = _safe_profile_id(global_profile_id)
    effective = [
        EffectivePageCompression(
            page_index=index,
            preset="global",
            profile_id=global_profile,
            source_rule_id=None,
            label="Perfil global",
            color="#6B7280",
            excluded=False,
        )
        for index in range(page_count)
    ]

    occupied: dict[int, PageCompressionRule] = {}
    explicit_rules: list[PageCompressionRule] = []
    for rule in rules or []:
        preset_id = rule.normalized_preset()
        preset = PAGE_RULE_PRESETS[preset_id]
        pages = parse_page_spec(rule.page_spec, page_count)
        overlap = [page for page in pages if page in occupied]
        if overlap:
            overlap_text = compact_page_indexes(overlap)
            raise ValueError(
                f"Las paginas {overlap_text} ya tienen una regla. "
                "Edita o elimina la regla existente."
            )
        explicit_rules.append(rule)
        label = rule.label.strip() or preset.label
        profile_id = (
            _safe_profile_id(str(rule.options.get("profile_id") or preset.profile_id))
            if preset_id == "custom"
            else preset.profile_id
        )
        for page_index in pages:
            occupied[page_index] = rule
            effective[page_index] = EffectivePageCompression(
                page_index=page_index,
                preset=preset_id,
                profile_id=profile_id,
                source_rule_id=rule.id,
                label=label,
                color=preset.color,
                excluded=preset.excluded,
                options=dict(rule.options),
            )

    return PageCompressionPlan(
        page_count=page_count,
        effective=effective,
        explicit_rules=explicit_rules,
    )


def compact_page_indexes(page_indexes: list[int] | set[int]) -> str:
    if not page_indexes:
        return "Ninguna"
    pages = sorted({int(idx) + 1 for idx in page_indexes})
    ranges: list[str] = []
    start = prev = pages[0]
    for page in pages[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = page
    ranges.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def _parse_page_token(
    token: str,
    page_count: int,
    *,
    default: int | None = None,
) -> int:
    clean = token.strip().lower()
    if not clean:
        if default is None:
            raise ValueError("Pagina vacia en el rango.")
        return default
    if clean in {"fin", "final", "ultima", "ultimo", "última", "último", "last"}:
        return page_count
    if not clean.isdigit():
        raise ValueError(f"Pagina invalida: {token}")
    value = int(clean)
    if value < 1 or value > page_count:
        raise ValueError(f"Pagina fuera de rango: {token}")
    return value


def _safe_profile_id(value: str) -> str:
    profile_id = (value or "balanced").strip().lower()
    return profile_id if profile_id in {"email", "balanced", "quality"} else "balanced"
