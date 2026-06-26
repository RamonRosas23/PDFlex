"""
Generador de variación natural para firmas.

Cada página recibe una pequeña variación pseudoaleatoria de:
  - ángulo
  - escala
  - posición (offset)
  - opacidad (sutil)
  - "pressure jitter" y variacion interna de trazo/tinta

La variación es determinista a partir de una semilla (seed) para que
el resultado sea reproducible y previsible en el visor final.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import random


@dataclass
class VariationConfig:
    """Rangos máximos de variación. Todos los valores son ±."""
    angle_deg: float = 2.5
    scale_pct: float = 4.0          # ±4% de escala
    offset_x: float = 4.0           # ±4 pt
    offset_y: float = 4.0           # ±4 pt
    opacity_min: float = 0.92
    opacity_max: float = 1.0
    enable_pressure_jitter: bool = True
    stroke_mode: str = "antefirma"  # exacta, natural, antefirma
    stroke_strength: float = 0.70   # 0..1, intensidad interna de trazo/tinta
    seed: int = 42

    def clamp(self) -> None:
        self.angle_deg = max(0.0, min(self.angle_deg, 15.0))
        self.scale_pct = max(0.0, min(self.scale_pct, 25.0))
        self.offset_x = max(0.0, min(self.offset_x, 30.0))
        self.offset_y = max(0.0, min(self.offset_y, 30.0))
        self.opacity_min = max(0.5, min(self.opacity_min, 1.0))
        self.opacity_max = max(self.opacity_min, min(self.opacity_max, 1.0))
        mode = str(self.stroke_mode or "exacta").strip().lower()
        aliases = {
            "exact": "exacta",
            "exacto": "exacta",
            "off": "exacta",
            "none": "exacta",
            "ante-firma": "antefirma",
        }
        self.stroke_mode = aliases.get(mode, mode)
        if self.stroke_mode not in {"exacta", "natural", "antefirma"}:
            self.stroke_mode = "natural"
        self.stroke_strength = max(0.0, min(float(self.stroke_strength), 1.0))


@dataclass
class Variation:
    """Resultado de una variación aplicable a una colocación base."""
    d_angle: float
    scale_factor: float
    d_x: float
    d_y: float
    opacity: float
    pressure: float  # 0..1, fuerza del jitter
    stroke_seed: int = 0
    stroke_mode: str = "exacta"
    stroke_strength: float = 0.0
    stretch_x: float = 1.0
    stretch_y: float = 1.0
    stroke_width_delta: float = 0.0
    ink_flow: float = 0.0
    dryness: float = 0.0

    @property
    def has_stroke_variation(self) -> bool:
        return self.stroke_strength > 0.0 and self.stroke_mode != "exacta"


class VariationGenerator:
    """Genera variaciones deterministas por (documento, página)."""

    def __init__(self, config: VariationConfig):
        self.config = config
        self.config.clamp()

    def variation_for(self, doc_id: str, page_index: int) -> Variation:
        # hashlib evita la aleatorización por proceso de hash() de Python.
        # Misma configuración + documento + página = mismo resultado exacto.
        payload = f"{self.config.seed}\0{doc_id}\0{page_index}".encode("utf-8")
        seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        rng = random.Random(seed)

        d_angle = rng.uniform(-self.config.angle_deg, self.config.angle_deg)
        # Escala: factor centrado en 1.0
        scale_factor = 1.0 + rng.uniform(
            -self.config.scale_pct / 100.0,
            self.config.scale_pct / 100.0,
        )
        d_x = rng.uniform(-self.config.offset_x, self.config.offset_x)
        d_y = rng.uniform(-self.config.offset_y, self.config.offset_y)
        opacity = rng.uniform(self.config.opacity_min, self.config.opacity_max)
        pressure = rng.uniform(0.0, 1.0) if self.config.enable_pressure_jitter else 0.0
        mode = self.config.stroke_mode
        if not self.config.enable_pressure_jitter or mode == "exacta":
            stroke_strength = 0.0
            mode = "exacta"
        else:
            mode_gain = 0.68 if mode == "natural" else 1.0
            stroke_strength = self.config.stroke_strength * mode_gain

        shape_range = 0.018 if mode == "natural" else 0.032
        shape_range *= stroke_strength
        stretch_x = 1.0 + rng.uniform(-shape_range, shape_range)
        stretch_y = 1.0 + rng.uniform(-shape_range * 0.75, shape_range * 0.75)
        stroke_width_delta = rng.uniform(-1.0, 1.0) * stroke_strength
        ink_flow = rng.uniform(-1.0, 1.0) * stroke_strength
        dryness = rng.uniform(0.0, 1.0) * stroke_strength
        stroke_seed = rng.randrange(0, 2**31)

        return Variation(
            d_angle=d_angle,
            scale_factor=scale_factor,
            d_x=d_x,
            d_y=d_y,
            opacity=opacity,
            pressure=pressure,
            stroke_seed=stroke_seed,
            stroke_mode=mode,
            stroke_strength=stroke_strength,
            stretch_x=stretch_x,
            stretch_y=stretch_y,
            stroke_width_delta=stroke_width_delta,
            ink_flow=ink_flow,
            dryness=dryness,
        )
