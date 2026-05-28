"""
Generador de iconos PNG en runtime para uso en QSS.

Qt6 no rasteriza bien triángulos hechos con border-CSS, y los data URIs
SVG inline no siempre funcionan. La solución más confiable es generar
PNGs pequeños en un directorio temporal y referenciarlos por path absoluto.
"""
import os
import tempfile
from PIL import Image, ImageDraw


# Cache global de paths generados
_assets_cache: dict = {}


def _build_assets() -> dict:
    """Genera todos los iconos y devuelve un dict con sus paths."""
    if _assets_cache:
        return _assets_cache

    tmpdir = tempfile.mkdtemp(prefix="firmador_assets_")

    def triangle(direction: str, color: tuple, size: tuple = (10, 6)) -> str:
        """Dibuja un triángulo en PNG y devuelve el path."""
        w, h = size
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if direction == "up":
            pts = [(0, h - 1), (w // 2, 0), (w - 1, h - 1)]
        elif direction == "down":
            pts = [(0, 0), (w // 2, h - 1), (w - 1, 0)]
        else:
            raise ValueError(direction)
        d.polygon(pts, fill=color)
        path = os.path.join(tmpdir, f"arrow_{direction}_{color[0]:02x}{color[1]:02x}{color[2]:02x}.png")
        img.save(path)
        return path

    # Flechas para SpinBox (8x5)
    _assets_cache["arrow_up"] = triangle("up", (144, 148, 160, 255), size=(8, 5))
    _assets_cache["arrow_down"] = triangle("down", (144, 148, 160, 255), size=(8, 5))
    _assets_cache["arrow_up_hover"] = triangle("up", (236, 237, 238, 255), size=(8, 5))
    _assets_cache["arrow_down_hover"] = triangle("down", (236, 237, 238, 255), size=(8, 5))

    # Flecha para ComboBox (10x6)
    _assets_cache["combo_arrow"] = triangle("down", (144, 148, 160, 255), size=(10, 6))
    _assets_cache["combo_arrow_hover"] = triangle("down", (236, 237, 238, 255), size=(10, 6))

    # Check para CheckBox (12x12)
    img = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(2, 6), (5, 9), (10, 3)], fill=(255, 255, 255, 255), width=2)
    check_path = os.path.join(tmpdir, "check.png")
    img.save(check_path)
    _assets_cache["check"] = check_path

    return _assets_cache


def get_assets() -> dict:
    """Devuelve el dict de paths a iconos."""
    return _build_assets()


def asset_url(name: str) -> str:
    """Devuelve la URL forward-slash para usar en QSS."""
    path = get_assets()[name]
    # QSS necesita forward slashes incluso en Windows
    return path.replace("\\", "/")
