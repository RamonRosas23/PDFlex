"""
Tema profesional para la aplicación.

Paleta inspirada en interfaces modernas tipo Linear/Vercel/Notion.
Estilos consistentes para TODOS los widgets de Qt (incluyendo
QSpinBox/QDoubleSpinBox/QComboBox que requieren reglas explícitas
para sus sub-controles).
"""
import tempfile
from pathlib import Path as _Path

# Genera el SVG del checkmark una sola vez al cargar el módulo
def _write_check_svg() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
        '<polyline points="2,6 5,9.5 10,3" stroke="white" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
        '</svg>'
    )
    tmp = _Path(tempfile.gettempdir()).resolve() / "PDFlex" / "check.svg"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(svg, encoding="utf-8")
    return str(tmp).replace("\\", "/")

_CHECK_SVG = _write_check_svg()

# Paleta refinada
COLORS = {
    "bg":            "#0A0A0B",
    "surface":       "#111114",
    "surface_2":     "#16161A",
    "surface_3":     "#1C1C21",
    "border":        "#26262C",
    "border_strong": "#33333B",
    "border_focus":  "#5E6AD2",
    "text":          "#ECEDEE",
    "text_muted":    "#9094A0",
    "text_dim":      "#6B6F7A",
    "accent":        "#5E6AD2",
    "accent_hover":  "#6F7BDF",
    "accent_press":  "#4F5BC8",
    "success":       "#3BD37C",
    "warning":       "#F5A623",
    "danger":        "#E5484D",
    "scroll_handle": "#34343C",   # handle de scrollbars en toda la app
}


DARK_THEME = f"""
/* ============================================================
   Base
============================================================ */
* {{
    font-family: "Inter", "Segoe UI Variable", "Segoe UI",
                 "SF Pro Display", "Helvetica Neue", system-ui, sans-serif;
    font-size: 13px;
    color: {COLORS['text']};
    outline: 0;
}}

QMainWindow, QWidget {{
    background-color: {COLORS['bg']};
}}

QToolTip {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 6px 10px;
    border-radius: 6px;
}}

/* ============================================================
   Sidebar
============================================================ */
#Sidebar {{
    background-color: {COLORS['surface']};
    border: none;
    border-right: 1px solid {COLORS['border']};
}}

/* Marco de marca en la parte superior */
#SidebarBrandFrame {{
    background: transparent;
    border: none;
}}

/* El nombre de la herramienta se colorea vía _apply_tool_accent */
#SidebarBrandName {{
    color: {COLORS['accent']};
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.3px;
    background: transparent;
}}

/* Compat. legado — algunas rutas aún usan SidebarBrand */
#SidebarBrand {{
    color: {COLORS['text']};
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.2px;
    padding: 24px 22px 2px 22px;
}}

#SidebarTagline {{
    color: {COLORS['text_dim']};
    font-size: 11px;
    background: transparent;
}}

#SidebarSection {{
    color: {COLORS['text_dim']};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 6px 20px 4px 20px;
    text-transform: uppercase;
    background: transparent;
}}

/* Botones paso (estilo nuevo _StepBtn) — base */
#SidebarStep, #SidebarStepHover, #SidebarStepActive {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
}}

/* Botones legado QPushButton */
QPushButton[class="SidebarBtn"] {{
    background-color: transparent;
    color: {COLORS['text_muted']};
    border: none;
    padding: 10px 22px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    min-height: 22px;
}}
QPushButton[class="SidebarBtn"]:hover {{
    background-color: {COLORS['surface_2']};
    color: {COLORS['text']};
}}
QPushButton[class="SidebarBtn"][active="true"] {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text']};
    border-left: 2px solid {COLORS['accent']};
    padding-left: 20px;
}}

#SidebarFooter {{
    color: {COLORS['border_strong']};
    padding: 12px 20px;
    font-size: 11px;
    border-top: 1px solid {COLORS['border']};
    background: transparent;
}}

/* ============================================================
   Page header
============================================================ */
#PageTitle {{
    color: {COLORS['text']};
    font-size: 21px;
    font-weight: 700;
    letter-spacing: -0.5px;
    padding: 0;
    margin: 0;
    background: transparent;
}}

#PageSubtitle {{
    color: {COLORS['text_muted']};
    font-size: 13px;
    padding: 0;
    margin: 0;
    background: transparent;
}}

/* ============================================================
   Cards
============================================================ */
QFrame[class="Card"] {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}

QLabel[class="CardTitle"] {{
    color: {COLORS['text']};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: -0.1px;
    background: transparent;
}}

QLabel[class="CardHint"] {{
    color: {COLORS['text_muted']};
    font-size: 12px;
    background: transparent;
}}

QLabel[class="StatLabel"] {{
    color: {COLORS['text_dim']};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    background: transparent;
}}

QLabel[class="StatValue"] {{
    color: {COLORS['text']};
    font-size: 24px;
    font-weight: 600;
    letter-spacing: -0.5px;
    background: transparent;
}}

QLabel[class="Mono"] {{
    color: {COLORS['text']};
    font-family: "JetBrains Mono", "SF Mono", "Consolas", "Menlo", monospace;
    font-size: 12px;
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 10px;
}}

QLabel {{
    background: transparent;
}}

/* ============================================================
   Buttons
============================================================ */
QPushButton {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
    min-height: 18px;
    outline: none;
}}

QPushButton:focus {{
    outline: none;
    border: 1px solid {COLORS['border_strong']};
}}

QPushButton:hover {{
    background-color: {COLORS['border']};
    border-color: {COLORS['border_strong']};
}}

QPushButton:pressed {{
    background-color: {COLORS['surface_2']};
}}

QPushButton:disabled {{
    background-color: {COLORS['surface_2']};
    color: {COLORS['text_dim']};
    border-color: {COLORS['border']};
}}

QPushButton[class="Primary"], QPushButton.Primary {{
    background: {COLORS['accent']};
    background-color: {COLORS['accent']};
    color: #FFFFFF;
    border: 1px solid {COLORS['accent']};
    font-weight: 600;
}}

QPushButton[class="Primary"]:hover, QPushButton.Primary:hover {{
    background: {COLORS['accent_hover']};
    background-color: {COLORS['accent_hover']};
    border-color: {COLORS['accent_hover']};
}}

QPushButton[class="Primary"]:pressed, QPushButton.Primary:pressed {{
    background: {COLORS['accent_press']};
    background-color: {COLORS['accent_press']};
    border-color: {COLORS['accent_press']};
}}

QPushButton[class="Primary"]:disabled, QPushButton.Primary:disabled {{
    background: {COLORS['surface_3']};
    background-color: {COLORS['surface_3']};
    color: {COLORS['text_dim']};
    border-color: {COLORS['border']};
}}

QPushButton[class="Ghost"] {{
    background-color: transparent;
    border: 1px solid {COLORS['border']};
    color: {COLORS['text']};
}}

QPushButton[class="Ghost"]:hover {{
    background-color: {COLORS['surface_2']};
    border-color: {COLORS['border_strong']};
}}

QPushButton[class="Danger"] {{
    background-color: transparent;
    border: 1px solid {COLORS['border']};
    color: {COLORS['danger']};
}}

QPushButton[class="Danger"]:hover {{
    background-color: rgba(229, 72, 77, 0.08);
    border-color: {COLORS['danger']};
}}

QPushButton[class="IconBtn"] {{
    background-color: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 4px 10px;
    min-width: 28px;
    min-height: 28px;
    max-height: 30px;
    font-size: 13px;
}}

QPushButton[class="IconBtn"]:hover {{
    background-color: {COLORS['surface_3']};
    border-color: {COLORS['border_strong']};
}}

/* ============================================================
   Inputs — altura consistente y texto visible
============================================================ */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {{
    background-color: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 12px;
    color: {COLORS['text']};
    selection-background-color: {COLORS['accent']};
    selection-color: #FFFFFF;
    min-height: 22px;
    font-size: 13px;
}}

QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {COLORS['border_strong']};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border-color: {COLORS['accent']};
    background-color: {COLORS['surface_2']};
}}

QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_dim']};
}}

QLineEdit::placeholder {{
    color: {COLORS['text_dim']};
}}

/* SpinBox / DoubleSpinBox arrows */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 22px;
    height: 18px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-top-right-radius: 7px;
    background: transparent;
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
    background: {COLORS['surface_3']};
}}

QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed {{
    background: {COLORS['border']};
}}

QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 22px;
    height: 18px;
    border: none;
    border-left: 1px solid {COLORS['border']};
    border-top: 1px solid {COLORS['border']};
    border-bottom-right-radius: 7px;
    background: transparent;
}}

QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {COLORS['surface_3']};
}}

QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {COLORS['border']};
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    width: 7px;
    height: 7px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 6px solid {COLORS['text_muted']};
}}

QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {{
    border-bottom-color: {COLORS['text']};
}}

QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:off {{
    border-bottom-color: {COLORS['text_dim']};
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 7px;
    height: 7px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {COLORS['text_muted']};
}}

QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {{
    border-top-color: {COLORS['text']};
}}

QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled,
QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:off {{
    border-top-color: {COLORS['text_dim']};
}}

/* ComboBox */
QComboBox {{
    padding-right: 28px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    background: transparent;
}}

QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLORS['text_muted']};
    margin-right: 10px;
}}

QComboBox::down-arrow:on {{
    border-top: none;
    border-bottom: 5px solid {COLORS['text']};
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['surface_3']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 6px;
    color: {COLORS['text']};
    selection-background-color: {COLORS['accent']};
    selection-color: #FFFFFF;
    padding: 4px;
    outline: 0;
}}

QComboBox QAbstractItemView::item {{
    padding: 7px 10px;
    border-radius: 5px;
    min-height: 18px;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: {COLORS['border']};
}}

/* ============================================================
   Sliders
============================================================ */
QSlider {{
    background: transparent;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {COLORS['border']};
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background: {COLORS['accent']};
    border-radius: 2px;
}}

QSlider::add-page:horizontal {{
    background: {COLORS['border']};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 2px solid {COLORS['accent']};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {COLORS['text']};
    border-color: {COLORS['accent_hover']};
}}

QSlider::handle:horizontal:pressed {{
    background: {COLORS['accent']};
}}

/* ============================================================
   Progress
============================================================ */
QProgressBar {{
    background-color: {COLORS['surface_3']};
    border: none;
    border-radius: 3px;
    text-align: center;
    color: {COLORS['text']};
    height: 6px;
    font-size: 11px;
    font-weight: 600;
    max-height: 6px;
}}

QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 3px;
}}

/* ============================================================
   Lists
============================================================ */
QListWidget {{
    background-color: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 6px;
    outline: 0;
    color: {COLORS['text']};
    font-size: 13px;
}}

QListWidget::item {{
    padding: 10px 12px;
    border-radius: 6px;
    color: {COLORS['text_muted']};
    margin: 1px 0;
    min-height: 18px;
}}

QListWidget::item:hover {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text']};
}}

QListWidget::item:selected {{
    background-color: rgba(94, 106, 210, 0.18);
    color: {COLORS['text']};
    border: 1px solid rgba(94, 106, 210, 0.4);
}}

QListWidget::item:selected:!active {{
    background-color: rgba(94, 106, 210, 0.12);
}}

QListWidget#PageThumbList {{
    padding: 4px;
}}

QListWidget#PageThumbList::item {{
    padding: 4px;
    margin: 2px 0;
    min-height: 0;
    border-radius: 6px;
}}

QListWidget#PageThumbList::item:selected {{
    background-color: rgba(94, 106, 210, 0.18);
    border: 1px solid rgba(94, 106, 210, 0.4);
}}

QListWidget#ResultList {{
    padding: 6px;
}}

QListWidget#ResultList::item {{
    padding: 9px 10px;
    margin: 1px 0;
    border-radius: 6px;
}}

/* ============================================================
   Scrollbars
============================================================ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 0;
}}

QScrollBar::handle:vertical {{
    background: {COLORS['border_strong']};
    min-height: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: #44444E;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 4px 2px 4px;
}}

QScrollBar::handle:horizontal {{
    background: {COLORS['border_strong']};
    min-width: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: #44444E;
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ============================================================
   Checkboxes
============================================================ */
QCheckBox {{
    color: {COLORS['text']};
    spacing: 10px;
    background: transparent;
    font-size: 13px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {COLORS['border_strong']};
    border-radius: 4px;
    background: {COLORS['surface_2']};
}}

QCheckBox::indicator:hover {{
    border-color: {COLORS['accent']};
}}

QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border-color: {COLORS['accent']};
    border-radius: 4px;
    image: url({_CHECK_SVG});
}}

/* ============================================================
   Frames especiales
============================================================ */
QFrame[class="Divider"] {{
    background-color: {COLORS['border']};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

QFrame[class="PageContainer"] {{
    background-color: {COLORS['bg']};
    border: none;
}}

#PreviewCanvas {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}

#ResultCanvas {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}

/* ============================================================
   Drop zone
============================================================ */
#DropZone {{
    background-color: {COLORS['surface_3']};
    border: 1.5px dashed #3E3E4C;
    border-radius: 10px;
    color: {COLORS['text_muted']};
    min-height: 200px;
}}

#DropZone:hover {{
    background-color: #1E1E28;
    border-color: #50507A;
}}

#DropZoneActive {{
    background-color: rgba(94, 106, 210, 0.10);
    border: 2px dashed {COLORS['accent']};
    border-radius: 10px;
    color: {COLORS['text']};
}}

#DropZoneTitle {{
    color: {COLORS['text']};
    font-size: 14px;
    font-weight: 600;
    background: transparent;
}}

#DropZoneHint {{
    color: {COLORS['text_muted']};
    font-size: 12px;
    background: transparent;
}}

#PreviewEmptyState {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
}}

#PreviewEmptyTitle {{
    color: {COLORS['text']};
    font-size: 15px;
    font-weight: 600;
    background: transparent;
}}

#PreviewEmptyHint {{
    color: {COLORS['text_muted']};
    font-size: 13px;
    background: transparent;
}}

/* ============================================================
   Step badges
============================================================ */
#StepBadge {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text_dim']};
    font-size: 10px;
    font-weight: 700;
    border-radius: 4px;
    padding: 2px 7px;
    min-width: 18px;
    max-height: 16px;
    border: 1px solid {COLORS['border']};
}}

#StepBadgeActive {{
    background-color: {COLORS['accent']};
    color: #FFFFFF;
    font-size: 10px;
    font-weight: 700;
    border-radius: 4px;
    padding: 2px 7px;
    min-width: 18px;
    max-height: 16px;
    border: 1px solid {COLORS['accent']};
}}

/* ============================================================
   Panel izquierdo scrolleable (Firma y posición)
============================================================ */
#LeftPanelScroll {{
    background: transparent;
    border: none;
}}

#LeftPanelScroll > QWidget {{
    background: transparent;
}}

#LeftPanelScroll QScrollBar:vertical {{
    background: transparent;
    width: 16px;
    margin: 8px 2px 8px 10px;
}}

#LeftPanelScroll QScrollBar::handle:vertical {{
    background: #34343C;
    min-height: 36px;
    border-radius: 3px;
}}

#LeftPanelScroll QScrollBar::handle:vertical:hover {{
    background: {COLORS['accent']};
}}

#LeftPanelScroll QScrollBar::add-line:vertical,
#LeftPanelScroll QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}

#LeftPanelScroll QScrollBar::add-page:vertical,
#LeftPanelScroll QScrollBar::sub-page:vertical {{
    background: none;
}}

QListWidget#SignatureList {{
    padding: 4px;
}}

QListWidget#SignatureList::item {{
    padding: 6px 8px;
    margin: 1px 0;
    border-radius: 6px;
}}

#SignatureOptionsScope {{
    color: {COLORS['text']};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}

/* ============================================================
   Scrollbars del canvas de preview de firma
============================================================ */
#PdfPreview QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 14px 4px 14px 6px;
}}

#PdfPreview QScrollBar::handle:vertical {{
    background: #34343C;
    min-height: 40px;
    border-radius: 3px;
}}

#PdfPreview QScrollBar::handle:vertical:hover {{
    background: {COLORS['accent']};
}}

#PdfPreview QScrollBar::add-line:vertical,
#PdfPreview QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}

#PdfPreview QScrollBar::add-page:vertical,
#PdfPreview QScrollBar::sub-page:vertical {{
    background: none;
}}

#PdfPreview QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 6px 14px 4px 14px;
}}

#PdfPreview QScrollBar::handle:horizontal {{
    background: #34343C;
    min-width: 40px;
    border-radius: 3px;
}}

#PdfPreview QScrollBar::handle:horizontal:hover {{
    background: {COLORS['accent']};
}}

#PdfPreview QScrollBar::add-line:horizontal,
#PdfPreview QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

#PdfPreview QScrollBar::add-page:horizontal,
#PdfPreview QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ============================================================
   Shell — Topbar
============================================================ */
#ShellTopbar {{
    background-color: {COLORS['surface']};
    border-bottom: 1px solid {COLORS['border']};
}}

#TopbarLogo {{
    color: {COLORS['text']};
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.3px;
}}

#TopbarSep {{
    background-color: {COLORS['border']};
}}

#TopbarToolName {{
    color: {COLORS['text_muted']};
    font-size: 13px;
}}

#TrayBtn {{
    background-color: {COLORS['surface_2']};
    color: {COLORS['text_muted']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 0 12px;
    font-size: 12px;
}}

#TrayBtn:hover {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text']};
    border-color: {COLORS['border_strong']};
}}

#TrayBtn[has_items="true"] {{
    color: {COLORS['text']};
    border-color: {COLORS['border_strong']};
}}

/* ============================================================
   Shell — Launcher (rediseño v2)
============================================================ */

/* La tarjeta usa setStyleSheet() dinámico desde Python para el hover,
   estos valores son el fallback inicial */
#LauncherCard {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}

#ComingSoonBadge {{
    background-color: {COLORS['surface_3']};
    color: {COLORS['text_dim']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}

/* Títulos legacy (se mantienen por compatibilidad) */
#LauncherTitle {{
    color: {COLORS['text']};
    font-size: 34px;
    font-weight: 800;
    letter-spacing: -0.8px;
}}

#LauncherSubtitle {{
    color: {COLORS['text_dim']};
    font-size: 13px;
}}

#ToolCardTitle {{
    font-size: 14px;
    font-weight: 700;
    letter-spacing: -0.2px;
}}

#ToolCardTagline {{
    color: {COLORS['text_muted']};
    font-size: 12px;
}}

/* ============================================================
   Shell — Bandeja (Tray)
============================================================ */
#TrayPopup {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 8px;
}}

#TrayTitle {{
    color: {COLORS['text']};
    font-size: 13px;
    font-weight: 600;
}}

QFrame[class="TrayItemRow"] {{
    background-color: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
}}

QFrame[class="TrayItemRow"]:hover {{
    border-color: {COLORS['border_strong']};
}}

/* ============================================================
   Shell — Tippy
============================================================ */
#TippyPopover {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 8px;
}}

#TippyTitle {{
    color: {COLORS['text']};
    font-size: 13px;
    font-weight: 600;
}}

#TippyBody {{
    background-color: transparent;
    color: {COLORS['text_muted']};
    font-size: 12px;
    border: none;
}}

QPushButton[class="TippyBtn"] {{
    background-color: transparent;
    color: {COLORS['text_dim']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    padding: 0;
}}

QPushButton[class="TippyBtn"]:hover {{
    background-color: {COLORS['surface_2']};
    color: {COLORS['text_muted']};
    border-color: {COLORS['border_strong']};
}}
"""
