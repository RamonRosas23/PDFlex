"""Registro declarativo de herramientas de PDFlex.

Cada ToolDescriptor describe una herramienta.  El launcher lee esta lista
para construir las tarjetas; el shell la usa para instanciar ventanas.

Para agregar una nueva herramienta:
  1. Crear ui/<tool>/window.py con la clase que extiende PipelineWindow.
  2. Agregar un ToolDescriptor a TOOLS con enabled=True.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, TYPE_CHECKING

if TYPE_CHECKING:
    from shell.context import ShellContext
    from PyQt6.QtWidgets import QWidget


@dataclass
class ToolDescriptor:
    id: str
    title: str
    tagline: str
    description_md: str
    accent_color: str
    enabled: bool
    window_factory: Callable[["ShellContext"], "QWidget"]
    icon_letter: str = ""     # letra/símbolo mostrado en el icono generado
    input_extensions: tuple[str, ...] = (".pdf",)


def _make_firmador():
    from ui.firmador.window import FirmadorWindow
    return FirmadorWindow


def _make_organizador():
    from ui.organizador.window import OrganizadorWindow
    return OrganizadorWindow


def _make_compresor():
    from ui.compresor.window import CompresorWindow
    return CompresorWindow


def _make_marca_agua():
    from ui.marca_agua.window import MarcaAguaWindow
    return MarcaAguaWindow


def _make_redactor():
    from ui.redactor.window import RedactorWindow
    return RedactorWindow


def _make_protector():
    from ui.protector.window import ProtectorWindow
    return ProtectorWindow


def _make_formularios():
    from ui.formularios.window import FormulariosWindow
    return FormulariosWindow


def _make_comparador():
    from ui.comparador.window import ComparadorWindow
    return ComparadorWindow


def _make_reparador():
    from ui.reparador.window import ReparadorWindow
    return ReparadorWindow


def _make_foleador():
    from ui.foleador.window import FoleadorWindow
    return FoleadorWindow


def _make_separador():
    from ui.separador.window import SeparadorWindow
    return SeparadorWindow


def _make_membretado():
    from ui.membretado.window import MembretadoWindow
    return MembretadoWindow


def _make_pdf_to_imgs():
    from ui.pdf_to_imgs.window import PdfToImgsWindow
    return PdfToImgsWindow


def _make_extraer_imagenes():
    from ui.extraer_imagenes.window import ExtraerImagenesWindow
    return ExtraerImagenesWindow


def _make_unir():
    from ui.unir.window import UnirWindow
    return UnirWindow


def _make_imgs_a_pdf():
    from ui.imgs_a_pdf.window import ImgsAPdfWindow
    return ImgsAPdfWindow


def _make_word_a_pdf():
    from ui.word_a_pdf.window import WordAPdfWindow
    return WordAPdfWindow


def _make_pdf_to_word():
    from ui.pdf_to_word.window import PdfToWordWindow
    return PdfToWordWindow


def _make_quitar_fondo():
    from ui.quitar_fondo.window import QuitarFondoWindow
    return QuitarFondoWindow


def _make_ocr():
    from ui.ocr.window import OcrWindow
    return OcrWindow


def _make_clasificador():
    from ui.clasificador.window import ClasificadorWindow
    return ClasificadorWindow


TOOLS: List[ToolDescriptor] = [
    ToolDescriptor(
        id="organizador",
        title="Organizador visual",
        tagline="Reordena, rota, duplica y extrae páginas",
        description_md=(
            "**¿Qué hace?**\n"
            "Permite reorganizar páginas PDF visualmente con miniaturas.\n\n"
            "**Características:**\n"
            "- Carga uno o varios PDFs\n"
            "- Reordena páginas arrastrando miniaturas\n"
            "- Rota, duplica, quita y extrae páginas seleccionadas\n"
            "- Genera un PDF final sin modificar los originales"
        ),
        accent_color="#14B8A6",
        enabled=True,
        window_factory=lambda ctx: _make_organizador()(ctx),
        icon_letter="O",
    ),
    ToolDescriptor(
        id="firmador",
        title="Firmador masivo",
        tagline="Firma PDFs con variación natural e inteligente",
        description_md=(
            "**¿Qué hace?**\n"
            "Aplica tu imagen de firma (PNG transparente) sobre uno o "
            "varios documentos PDF de forma masiva.\n\n"
            "**Características:**\n"
            "- Variación natural entre páginas (ángulo, escala, opacidad)\n"
            "- Anti-colisión automático: busca zona libre si hay texto\n"
            "- Snap a líneas de firma detectadas\n"
            "- Preview interactivo con arrastre y redimensionado"
        ),
        accent_color="#5E6AD2",
        enabled=True,
        window_factory=lambda ctx: _make_firmador()(ctx),
        icon_letter="F",
    ),
    ToolDescriptor(
        id="compresor",
        title="Comprimir PDF",
        tagline="Reduce peso con perfiles seguros",
        description_md=(
            "**¿Qué hace?**\n"
            "Optimiza PDFs por lote reduciendo el peso de imágenes internas "
            "y limpiando la estructura del documento.\n\n"
            "**Perfiles:**\n"
            "- Correo: máxima reducción razonable\n"
            "- Equilibrado: balance recomendado\n"
            "- Alta calidad: reducción conservadora\n\n"
            "Si un PDF ya está optimizado, PDFlex conserva una copia sin aumentar el peso."
        ),
        accent_color="#2DD4BF",
        enabled=True,
        window_factory=lambda ctx: _make_compresor()(ctx),
        icon_letter="C",
    ),
    ToolDescriptor(
        id="marca_agua",
        title="Marca de agua",
        tagline="Sellos de texto o imagen por lote",
        description_md=(
            "**¿Qué hace?**\n"
            "Aplica marcas de agua y sellos sobre PDFs por lote sin modificar "
            "los originales.\n\n"
            "**Características:**\n"
            "- Presets: Confidencial, Copia, Pagado y Recibido\n"
            "- Texto o imagen como sello\n"
            "- Opacidad, posición, rotación y tamaño ajustables\n"
            "- Aplicación a todas las páginas, primera, última o rango personalizado\n"
            "- Resultado temporal con visor y envío a otras herramientas"
        ),
        accent_color="#F97316",
        enabled=True,
        window_factory=lambda ctx: _make_marca_agua()(ctx),
        icon_letter="A",
    ),
    ToolDescriptor(
        id="redactor",
        title="Redaccion segura",
        tagline="Elimina informacion sensible de verdad",
        description_md=(
            "**¿Qué hace?**\n"
            "Permite dibujar zonas de redacción sobre un PDF y exportar una "
            "copia segura donde el contenido queda eliminado, no solo cubierto.\n\n"
            "**Características:**\n"
            "- Redacción manual por rectángulos\n"
            "- Navegación por páginas\n"
            "- Deshacer, limpiar página y limpiar todo\n"
            "- Relleno negro o blanco\n"
            "- Aplica redacciones reales sobre texto, imágenes y gráficos tocados"
        ),
        accent_color="#EF4444",
        enabled=True,
        window_factory=lambda ctx: _make_redactor()(ctx),
        icon_letter="R",
    ),
    ToolDescriptor(
        id="protector",
        title="Proteger PDF",
        tagline="Contraseñas y permisos AES-256",
        description_md=(
            "**¿Qué hace?**\n"
            "Crea copias cifradas de PDFs con contraseña de apertura opcional "
            "y permisos configurables.\n\n"
            "**Características:**\n"
            "- Cifrado AES-256\n"
            "- Contraseña de apertura y de propietario\n"
            "- Permisos de impresión, copia, edición, formularios y organización\n"
            "- Salida temporal con visor y guardado posterior"
        ),
        accent_color="#0EA5E9",
        enabled=True,
        window_factory=lambda ctx: _make_protector()(ctx),
        icon_letter="P",
    ),
    ToolDescriptor(
        id="formularios",
        title="Formularios PDF",
        tagline="Rellena campos y aplana resultados",
        description_md=(
            "**¿Qué hace?**\n"
            "Detecta campos AcroForm, permite capturar valores y genera una "
            "copia rellena opcionalmente aplanada.\n\n"
            "**Características:**\n"
            "- Detecta textos, checkboxes, radios, combos y listas\n"
            "- Controles editables por tipo de campo\n"
            "- Salida editable o aplanada\n"
            "- Resultado temporal con visor y Guardar como"
        ),
        accent_color="#A855F7",
        enabled=True,
        window_factory=lambda ctx: _make_formularios()(ctx),
        icon_letter="L",
    ),
    ToolDescriptor(
        id="comparador",
        title="Comparar PDFs",
        tagline="Detecta cambios visuales y de texto",
        description_md=(
            "**¿Qué hace?**\n"
            "Compara dos versiones de un PDF y genera un reporte con resumen "
            "por página y diferencias resaltadas.\n\n"
            "**Características:**\n"
            "- Comparación visual por render de página\n"
            "- Comparación de texto nativo normalizado\n"
            "- Detección de páginas agregadas o eliminadas\n"
            "- Sensibilidad rápida, equilibrada o detallada\n"
            "- Reporte PDF temporal con visor y Guardar como"
        ),
        accent_color="#F59E0B",
        enabled=True,
        window_factory=lambda ctx: _make_comparador()(ctx),
        icon_letter="V",
    ),
    ToolDescriptor(
        id="reparador",
        title="Reparar PDF",
        tagline="Reescribe y normaliza documentos",
        description_md=(
            "**¿Qué hace?**\n"
            "Genera copias normalizadas de PDFs para mejorar compatibilidad "
            "y recuperar documentos con estructura dañada cuando MuPDF pueda abrirlos.\n\n"
            "**Características:**\n"
            "- Reescritura con limpieza interna, garbage y deflate\n"
            "- Perfil de compatibilidad sin object streams\n"
            "- Detección de PDFs reparados al abrir\n"
            "- Verificación posterior de páginas y apertura\n"
            "- Salida temporal con visor, Guardar como y Guardar todo"
        ),
        accent_color="#84CC16",
        enabled=True,
        window_factory=lambda ctx: _make_reparador()(ctx),
        icon_letter="Z",
    ),
    ToolDescriptor(
        id="foleador",
        title="Foleador",
        tagline="Numeración secuencial con formatos personalizados",
        description_md=(
            "**¿Qué hace?**\n"
            "Agrega números de folio a las páginas de tus documentos.\n\n"
            "**Formatos disponibles:**\n"
            "- `{n:05}` → 00001, 00002 … (ancho fijo, sin correrse)\n"
            "- `FOLIO-{n:04}` → FOLIO-0001\n"
            "- `{doc}-{n:03}` → reinicia por documento\n"
            "- `{n:05}/{total:05}` → número / total\n\n"
            "El folio 100 con `{n:05}` es **00100** (no 0000100)."
        ),
        accent_color="#3BD37C",
        enabled=True,
        window_factory=lambda ctx: _make_foleador()(ctx),
        icon_letter="N",
    ),
    ToolDescriptor(
        id="separador",
        title="Separador de PDF",
        tagline="Divide un PDF en múltiples archivos por rangos",
        description_md=(
            "**¿Qué hace?**\n"
            "Separa un PDF en varios archivos definiendo rangos de páginas.\n\n"
            "**Ejemplo:** PDF de 100 páginas →\n"
            "- Rango 1–11 → `parte1.pdf`\n"
            "- Rango 12–31 → `parte2.pdf`\n"
            "- Rango 32–100 → `parte3.pdf`\n\n"
            "**Próximamente**"
        ),
        accent_color="#F5A623",
        enabled=True,
        window_factory=lambda ctx: _make_separador()(ctx),
        icon_letter="S",
    ),
    ToolDescriptor(
        id="membretado",
        title="Membretado",
        tagline="Pega tus documentos sobre hojas membretadas",
        description_md=(
            "**¿Qué hace?**\n"
            "Superpone las páginas de tus documentos sobre una hoja membretada "
            "reutilizable.\n\n"
            "**Características:**\n"
            "- Biblioteca local de membretes frecuentes\n"
            "- Membretes PDF o Word (.doc/.docx convertido a PDF)\n"
            "- Detección automática de márgenes del membrete\n"
            "- Preview en tiempo real con marco de margen ajustable\n"
            "- Respeta logos superiores e inferiores"
        ),
        accent_color="#B87FF5",
        enabled=True,
        window_factory=lambda ctx: _make_membretado()(ctx),
        icon_letter="M",
    ),
    ToolDescriptor(
        id="pdf_to_imgs",
        title="PDF a Imágenes",
        tagline="Convierte páginas PDF a PNG, JPG o WebP",
        description_md=(
            "**¿Qué hace?**\n"
            "Exporta cada página de un PDF como imagen de alta resolución.\n\n"
            "**Opciones:**\n"
            "- Formatos: PNG, JPG, WebP\n"
            "- DPI configurable (72 – 600)\n"
            "- Una imagen por página o imagen panorámica vertical\n\n"
            "**Próximamente**"
        ),
        accent_color="#4CC9F0",
        enabled=True,
        window_factory=lambda ctx: _make_pdf_to_imgs()(ctx),
        icon_letter="I",
    ),
    ToolDescriptor(
        id="extraer_imagenes",
        title="Extraer imágenes",
        tagline="Saca recursos embebidos sin renderizar",
        description_md=(
            "**¿Qué hace?**\n"
            "Extrae imágenes y recursos embebidos directamente desde PDFs, "
            "sin convertir páginas completas.\n\n"
            "**Características:**\n"
            "- Conserva el formato original cuando PyMuPDF lo expone\n"
            "- Agrupa resultados por PDF origen\n"
            "- Evita duplicados por recurso interno\n"
            "- Filtro por tamaño mínimo\n"
            "- Vista previa, Guardar como y Guardar todo"
        ),
        accent_color="#06B6D4",
        enabled=True,
        window_factory=lambda ctx: _make_extraer_imagenes()(ctx),
        icon_letter="X",
    ),
    ToolDescriptor(
        id="unir",
        title="Unir PDFs",
        tagline="Combina múltiples documentos en un solo PDF",
        description_md=(
            "**¿Qué hace?**\n"
            "Fusiona varios archivos PDF en un único documento.\n\n"
            "**Características:**\n"
            "- Reordena los documentos antes de unir (arrastra)\n"
            "- Página en blanco opcional entre documentos\n"
            "- Marcadores de navegación automáticos por documento\n"
            "- Salida optimizada con compresión deflate"
        ),
        accent_color="#FF9B3E",
        enabled=True,
        window_factory=lambda ctx: _make_unir()(ctx),
        icon_letter="U",
    ),
    ToolDescriptor(
        id="imgs_a_pdf",
        title="Imágenes a PDF",
        tagline="Convierte y combina imágenes en un solo PDF",
        description_md=(
            "**¿Qué hace?**\n"
            "Toma una colección de imágenes (PNG, JPG, WebP, BMP, TIFF) "
            "y las convierte en un PDF con una página por imagen.\n\n"
            "**Opciones:**\n"
            "- Tamaño de página: A4, A3, Carta, Legal, adaptado a la imagen\n"
            "- Márgenes configurables (0–50 mm)\n"
            "- Ajuste: escalar, rellenar o tamaño original\n"
            "- Rotación automática según orientación de la imagen\n"
            "- Marcadores de navegación automáticos"
        ),
        accent_color="#E040FB",
        enabled=True,
        window_factory=lambda ctx: _make_imgs_a_pdf()(ctx),
        icon_letter="P",
        input_extensions=(
            ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif",
        ),
    ),
    ToolDescriptor(
        id="word_a_pdf",
        title="Word a PDF",
        tagline="Convierte DOC y DOCX en PDFs listos para usar",
        description_md=(
            "**¿Qué hace?**\n"
            "Convierte documentos Word (.doc y .docx) a PDF usando Microsoft "
            "Word instalado en el equipo.\n\n"
            "**Características:**\n"
            "- Conversión por lote\n"
            "- Progreso en segundo plano\n"
            "- Visor de PDFs convertidos\n"
            "- Envío directo a las demás herramientas PDF"
        ),
        accent_color="#4299E1",
        enabled=True,
        window_factory=lambda ctx: _make_word_a_pdf()(ctx),
        icon_letter="W",
        input_extensions=(".doc", ".docx"),
    ),
    ToolDescriptor(
        id="pdf_to_word",
        title="PDF a Word",
        tagline="Convierte PDFs en DOCX editable",
        description_md=(
            "**¿Qué hace?**\n"
            "Convierte PDFs con texto nativo o escaneados en documentos Word "
            "editables.\n\n"
            "**Características:**\n"
            "- Conserva texto nativo cuando ya existe\n"
            "- Usa OCR local como fallback para escaneos\n"
            "- Genera DOCX por lote\n"
            "- Preview del texto reconocido\n"
            "- Envio directo a Word a PDF para cerrar el ciclo"
        ),
        accent_color="#2563EB",
        enabled=True,
        window_factory=lambda ctx: _make_pdf_to_word()(ctx),
        icon_letter="D",
    ),
    ToolDescriptor(
        id="ocr",
        title="OCR de PDF",
        tagline="Convierte escaneos e imágenes en texto editable",
        description_md=(
            "**¿Qué hace?**\n"
            "Extrae texto de documentos PDF, incluso si cada página es una imagen "
            "o un escaneo.\n\n"
            "**Precisión cuidada:**\n"
            "- Conserva texto nativo cuando ya es confiable\n"
            "- OCR local con modelos neuronales de alta calidad\n"
            "- Mejora escaneos tenues y recupera páginas giradas\n"
            "- Exporta Word editable y TXT\n\n"
            "Tus documentos se procesan localmente: no se suben a internet."
        ),
        accent_color="#FF6B9A",
        enabled=True,
        window_factory=lambda ctx: _make_ocr()(ctx),
        icon_letter="T",
    ),
    ToolDescriptor(
        id="clasificador",
        title="Clasificador OCR",
        tagline="Renombra PDFs por tipo, RFC, fecha y folio",
        description_md=(
            "**¿Qué hace?**\n"
            "Lee texto nativo u OCR de PDFs y genera copias temporales con "
            "nombres armados desde campos detectados.\n\n"
            "**Campos disponibles:**\n"
            "- Tipo de documento por reglas configurables\n"
            "- RFC, fecha, folio, cliente y nombre original\n"
            "- Plantillas como `{tipo}_{cliente}_{fecha}_{folio}`\n\n"
            "Ideal para ordenar lotes de facturas, recibos, contratos y expedientes."
        ),
        accent_color="#22C55E",
        enabled=True,
        window_factory=lambda ctx: _make_clasificador()(ctx),
        icon_letter="C",
    ),
    ToolDescriptor(
        id="quitar_fondo",
        title="Quitar fondo",
        tagline="Genera PNGs transparentes desde imágenes con fondo uniforme",
        description_md=(
            "**¿Qué hace?**\n"
            "Elimina fondos blancos o uniformes de imágenes y guarda el resultado "
            "como PNG con transparencia.\n\n"
            "**Características:**\n"
            "- Procesamiento por lote\n"
            "- Fuerza de limpieza ajustable\n"
            "- Preview del resultado\n"
            "- Ideal para firmas, sellos, logos y recortes simples"
        ),
        accent_color="#00B894",
        enabled=True,
        window_factory=lambda ctx: _make_quitar_fondo()(ctx),
        icon_letter="B",
        input_extensions=(
            ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif",
        ),
    ),
]


def get_tool(tool_id: str) -> ToolDescriptor | None:
    return next((t for t in TOOLS if t.id == tool_id), None)
