"""Procesamiento de imagen de firma.

Funciones:
  - remove_background : elimina el fondo blanco/uniforme con precisión perceptual.
  - colorize_signature: colorea el trazo de la firma al azul tinta estándar.

Algoritmo de remoción de fondo
-------------------------------
1. Convierte la imagen a RGBA float32.
2. Muestrea el borde de la imagen (12 px de margen, mediana) para estimar
   el color de fondo. La mediana es robusta frente a esquinas que ya contienen
   tinta o marcas.
3. Calcula la distancia perceptual ponderada (pesos ITU-R BT.601) de cada
   píxel al color de fondo estimado.
4. Genera la máscara alfa con una curva S (smoothstep) que produce bordes
   suaves, sin escalones ni dientes de sierra.
5. Aplica desenfoque gaussiano leve (radius 0.7) a la máscara para
   anti-aliasing en bordes finos.
6. Multiplica por el canal alfa original (preserva transparencias previas).

Algoritmo de colorización
--------------------------
1. Calcula la luminancia perceptual de cada píxel.
2. Trata la oscuridad (1 − luminancia) como "intensidad de tinta".
3. Interpola linealmente entre blanco y el color de tinta de destino
   usando esa intensidad.  Los píxeles ya transparentes no se ven afectados.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

# Azul tinta estándar de bolígrafo (RGB)
BLUE_INK: tuple[int, int, int] = (27, 77, 169)


def remove_background(
    img: Image.Image,
    tolerance: float = 30.0,
) -> Image.Image:
    """Elimina el fondo uniforme de una imagen de firma.

    Args:
        img:       Imagen de firma (cualquier modo; se convierte a RGBA).
        tolerance: Radio de color que se considera fondo (0–100; default 30).
                   Valores más bajos conservan más píxeles cercanos al fondo.
                   Valores más altos limpian fondos más variables.
    Returns:
        Imagen RGBA con el fondo removido.
    """
    img = img.convert("RGBA")
    data = np.asarray(img, dtype=np.float32)   # (H, W, 4)
    rgb = data[:, :, :3]
    h, w = data.shape[:2]

    # ── 1. Muestreo del fondo — borde de 12 px, mediana robusta ─────── #
    border = max(1, min(12, h // 6, w // 6))
    edge = np.concatenate([
        rgb[:border].reshape(-1, 3),
        rgb[-border:].reshape(-1, 3),
        rgb[:, :border].reshape(-1, 3),
        rgb[:, -border:].reshape(-1, 3),
    ])
    bg = np.median(edge, axis=0)   # (3,) — color representativo del fondo

    # ── 2. Distancia perceptual ponderada (pesos BT.601) ─────────────── #
    w_rgb = np.array([0.299, 0.587, 0.114], dtype=np.float32)
    diff = (rgb - bg) * w_rgb            # (H, W, 3)
    dist = np.sqrt(np.sum(diff ** 2, axis=2))   # (H, W), max ≈ 141

    # ── 3. Máscara alfa — smoothstep sobre distancia normalizada ─────── #
    t = dist / max(float(tolerance), 1.0)
    t_c = np.clip(t, 0.0, 1.0)
    # Smoothstep S(t) = 3t² − 2t³  →  C¹ continua en 0 y 1
    alpha = t_c * t_c * (3.0 - 2.0 * t_c)
    # Píxeles muy distintos al fondo (t > 1) → completamente opacos
    alpha = np.where(t > 1.0, 1.0, alpha)

    # ── 4. Preservar alfa original + feathering suave ────────────────── #
    orig_alpha = data[:, :, 3] / 255.0
    alpha = alpha * orig_alpha

    # Gaussian blur en el canal alfa → anti-aliasing en bordes finos
    a_pil = Image.fromarray(
        (alpha * 255.0).clip(0, 255).astype(np.uint8), "L"
    )
    a_pil = a_pil.filter(ImageFilter.GaussianBlur(radius=0.7))

    result = np.array(img, dtype=np.uint8)
    result[:, :, 3] = np.asarray(a_pil, dtype=np.uint8)
    return Image.fromarray(result, "RGBA")


def colorize_signature(
    img: Image.Image,
    ink_color: tuple[int, int, int] = BLUE_INK,
) -> Image.Image:
    """Colorea el trazo de una firma en el color indicado.

    Preserva la textura y el matiz del trazo: los píxeles oscuros (tinta)
    se convierten al tono de destino y los claros permanecen claros o
    transparentes.

    Args:
        img:       Imagen RGBA de firma.
        ink_color: Color RGB de tinta (default: azul estándar BLUE_INK).
    Returns:
        Imagen RGBA con el trazo coloreado.
    """
    img = img.convert("RGBA")
    data = np.asarray(img, dtype=np.float32)   # (H, W, 4)
    r, g, b = data[:, :, 0], data[:, :, 1], data[:, :, 2]

    # Luminancia perceptual (0 = negro/tinta, 1 = blanco/fondo)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0

    # Intensidad de tinta: oscuro → 1.0, claro → 0.0
    ink = 1.0 - lum

    # Interpolar: blanco*(1-ink) + ink_color*ink
    ir, ig, ib = float(ink_color[0]), float(ink_color[1]), float(ink_color[2])
    result = data.copy()
    result[:, :, 0] = np.clip(255.0 - ink * (255.0 - ir), 0.0, 255.0)
    result[:, :, 1] = np.clip(255.0 - ink * (255.0 - ig), 0.0, 255.0)
    result[:, :, 2] = np.clip(255.0 - ink * (255.0 - ib), 0.0, 255.0)
    # Canal alfa sin cambios

    return Image.fromarray(result.astype(np.uint8), "RGBA")
