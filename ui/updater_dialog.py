"""UpdaterDialog — diálogo completo de actualización automática de PDFlex.

Estados (QStackedWidget):
  AVAILABLE   → muestra info de la versión + notas
  DOWNLOADING → barra de progreso + velocidad + ETA
  VERIFYING   → spinner SHA-256
  READY       → confirmación antes de instalar
  ERROR       → mensaje de error + reintentar

Protecciones:
  · Singleton: una sola instancia activa a la vez.
  · Mandatory: botón X y tecla Escape cierran PDFlex completo cuando la
    actualización es obligatoria o la versión está por debajo del mínimo.
  · No se puede cerrar mientras descarga o verifica.
  · No se puede iniciar dos descargas paralelas.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget, QApplication,
)

from core.update_config import APP_VERSION
from core.updater import (
    UpdateDownloadThread,
    UpdateDownloadWorker,
    UpdateInfo,
    format_bytes,
    is_update_forced,
    launch_installer_and_quit,
)
from ui.common.icons import icon_pixmap, set_button_icon
from ui.styles import COLORS


# ─────────────────────────────────────────────────────────────────────────────
# Constantes de estados
# ─────────────────────────────────────────────────────────────────────────────

_PAGE_AVAILABLE   = 0
_PAGE_DOWNLOADING = 1
_PAGE_VERIFYING   = 2
_PAGE_READY       = 3
_PAGE_ERROR       = 4

_SPINNER_FRAMES   = 12
_SPINNER_STEP_DEG = 360 // _SPINNER_FRAMES


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo principal
# ─────────────────────────────────────────────────────────────────────────────

class UpdaterDialog(QDialog):
    """Diálogo único de actualización. Usa show_update() para mostrarlo."""

    _active: Optional["UpdaterDialog"] = None

    # ── API pública ───────────────────────────────────────────────────────────

    @classmethod
    def show_update(cls, info: UpdateInfo, parent=None) -> None:
        """Muestra el diálogo para una actualización. Previene duplicados."""
        if cls._active is not None and cls._active.isVisible():
            cls._active.raise_()
            cls._active.activateWindow()
            return
        dlg = cls(info, parent)
        cls._active = dlg
        if is_update_forced(info):
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.show()

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(self, info: UpdateInfo, parent=None) -> None:
        super().__init__(parent)
        self._info                              = info
        self._forced                            = is_update_forced(info)
        self._installer_path: Optional[str]     = None
        self._download_worker: Optional[UpdateDownloadWorker] = None
        self._download_thread: Optional[UpdateDownloadThread] = None
        self._spinner_frame                     = 0
        self._drag_pos: Optional[QPoint]        = None
        self._quitting_app                      = False

        self.setWindowTitle("Actualización de PDFlex")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(500)
        self.setMaximumWidth(600)
        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())

        # Spinner para estados VERIFYING
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(80)
        self._spinner_timer.timeout.connect(self._tick_spinner)

        self._build_ui()
        self._set_page(_PAGE_AVAILABLE)

    # ─────────────────────────────────────────────────────────────────────────
    # Construcción de la interfaz
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("UpdaterDialogShell")
        shell.setStyleSheet(f"""
            QFrame#UpdaterDialogShell {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 140))
        shadow.setOffset(0, 14)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("UpdaterHeader")
        header.setStyleSheet(f"""
            QFrame#UpdaterHeader {{
                background-color: {COLORS['surface_2']};
                border-bottom: 1px solid {COLORS['border']};
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 15, 14, 15)
        h.setSpacing(13)

        # Ícono badge (download, accent)
        icon_box = QFrame()
        icon_box.setFixedSize(42, 42)
        icon_box.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(94, 106, 210, 0.18);
                border: 1px solid rgba(94, 106, 210, 0.45);
                border-radius: 9px;
            }}
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = QLabel()
        ib_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib_lbl.setPixmap(icon_pixmap("download", COLORS["accent"], 22))
        ib_lbl.setStyleSheet("background: transparent;")
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        # Columna de título + subtítulo
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_col.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel("Actualización disponible")
        self._title_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(self._title_lbl)

        self._subtitle_lbl = QLabel(f"PDFlex v{APP_VERSION} instalado")
        self._subtitle_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        title_col.addWidget(self._subtitle_lbl)

        h.addLayout(title_col, 1)

        # Botón cerrar
        self._close_btn = QPushButton()
        self._close_btn.setProperty("class", "IconBtn")
        self._close_btn.setFixedSize(28, 28)
        set_button_icon(self._close_btn, "x", size=14, icon_only=True)
        self._close_btn.clicked.connect(self.reject)
        if self._forced:
            self._close_btn.setToolTip("Cerrar PDFlex")
        else:
            self._close_btn.setToolTip("Cerrar")
        h.addWidget(self._close_btn)

        return header

    # ── Body (StackedWidget) ──────────────────────────────────────────────────

    def _build_body(self) -> QStackedWidget:
        self._body_stack = QStackedWidget()
        self._body_stack.addWidget(self._page_available())    # 0
        self._body_stack.addWidget(self._page_downloading())  # 1
        self._body_stack.addWidget(self._page_verifying())    # 2
        self._body_stack.addWidget(self._page_ready())        # 3
        self._body_stack.addWidget(self._page_error())        # 4
        return self._body_stack

    # ── Footer ────────────────────────────────────────────────────────────────

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("UpdaterFooter")
        footer.setStyleSheet(f"""
            QFrame#UpdaterFooter {{
                background-color: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 12, 18, 12)
        f.setSpacing(8)

        self._footer_info = QLabel("")
        self._footer_info.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; background: transparent;"
        )
        self._footer_info.setWordWrap(True)
        f.addWidget(self._footer_info, 1)

        # Botón cancelar descarga (visible solo en DOWNLOADING, no-forzado)
        self._btn_cancel_dl = QPushButton("Cancelar descarga")
        self._btn_cancel_dl.setFixedHeight(34)
        self._btn_cancel_dl.setMinimumWidth(110)
        self._btn_cancel_dl.setStyleSheet(self._style_secondary())
        self._btn_cancel_dl.clicked.connect(self._cancel_download)
        self._btn_cancel_dl.setVisible(False)
        f.addWidget(self._btn_cancel_dl)

        # Botón "Más tarde" (visible en AVAILABLE / ERROR, no-forzado)
        self._btn_later = QPushButton("Más tarde")
        self._btn_later.setFixedHeight(34)
        self._btn_later.setMinimumWidth(90)
        self._btn_later.setStyleSheet(self._style_secondary())
        self._btn_later.clicked.connect(self.reject)
        self._btn_later.setVisible(not self._forced)
        f.addWidget(self._btn_later)

        # Botón primario (context-sensitive)
        self._btn_primary = QPushButton("Descargar e instalar")
        self._btn_primary.setFixedHeight(34)
        self._btn_primary.setMinimumWidth(170)
        self._btn_primary.setStyleSheet(self._style_primary())
        self._btn_primary.clicked.connect(self._on_primary_clicked)
        f.addWidget(self._btn_primary)

        return footer

    # ─────────────────────────────────────────────────────────────────────────
    # Páginas del StackedWidget
    # ─────────────────────────────────────────────────────────────────────────

    def _page_available(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(14)

        # Fila de badges
        badges_row = QHBoxLayout()
        badges_row.setSpacing(8)

        ver_badge = QLabel(f"v{self._info.version}")
        ver_badge.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['accent']};
                background: rgba(94, 106, 210, 0.15);
                border: 1px solid rgba(94, 106, 210, 0.38);
                border-radius: 6px;
                padding: 3px 11px;
                font-size: 13px;
                font-weight: 700;
            }}
        """)
        badges_row.addWidget(ver_badge)

        if self._forced:
            oblig_badge = QLabel("⚠ OBLIGATORIA")
            oblig_badge.setStyleSheet(f"""
                QLabel {{
                    color: #FFB84D;
                    background: rgba(245, 166, 35, 0.14);
                    border: 1px solid rgba(245, 166, 35, 0.38);
                    border-radius: 6px;
                    padding: 3px 10px;
                    font-size: 10px;
                    font-weight: 700;
                    letter-spacing: 0.6px;
                }}
            """)
            badges_row.addWidget(oblig_badge)

        badges_row.addStretch()
        v.addLayout(badges_row)

        # Notas de versión
        if self._info.notes:
            notes_header = QLabel("NOTAS DE LA VERSIÓN")
            notes_header.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700;"
                "letter-spacing: 0.8px; background: transparent;"
            )
            v.addWidget(notes_header)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(108)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setStyleSheet(f"""
                QScrollArea {{
                    background: {COLORS['surface_3']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 8px;
                }}
                QScrollBar:vertical {{
                    background: transparent; width: 10px;
                    margin: 5px 2px 5px 4px;
                }}
                QScrollBar::handle:vertical {{
                    background: {COLORS['scroll_handle']}; min-height: 22px; border-radius: 3px;
                }}
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical  {{ height: 0; background: none; }}
                QScrollBar::add-page:vertical,
                QScrollBar::sub-page:vertical  {{ background: none; }}
            """)
            notes_lbl = QLabel(self._info.notes)
            notes_lbl.setWordWrap(True)
            notes_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            notes_lbl.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 12px; "
                "background: transparent; padding: 10px 12px;"
            )
            scroll.setWidget(notes_lbl)
            v.addWidget(scroll)

        # Aviso obligatorio
        if self._forced:
            warn = QFrame()
            warn.setStyleSheet(f"""
                QFrame {{
                    background: rgba(245, 166, 35, 0.10);
                    border: 1px solid rgba(245, 166, 35, 0.30);
                    border-radius: 8px;
                }}
            """)
            wl = QHBoxLayout(warn)
            wl.setContentsMargins(12, 10, 12, 10)
            wl.setSpacing(10)

            wi = QLabel()
            wi.setFixedSize(16, 16)
            wi.setPixmap(icon_pixmap("warning", COLORS["warning"], 16))
            wi.setStyleSheet("background: transparent;")
            wl.addWidget(wi)

            wt = QLabel(
                "Esta actualización es obligatoria. "
                "PDFlex se reiniciará para instalarla."
            )
            wt.setWordWrap(True)
            wt.setStyleSheet(
                f"color: {COLORS['warning']}; font-size: 12px; background: transparent;"
            )
            wl.addWidget(wt, 1)
            v.addWidget(warn)

        return w

    def _page_downloading(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)

        # Nombre del archivo
        filename = (
            self._info.url.rsplit("/", 1)[-1]
            or f"PDFlex_{self._info.version}_setup.exe"
        )
        fname_row = QHBoxLayout()
        fname_row.setSpacing(8)
        fi = QLabel()
        fi.setFixedSize(15, 15)
        fi.setPixmap(icon_pixmap("download", COLORS["accent"], 15))
        fi.setStyleSheet("background: transparent;")
        fname_row.addWidget(fi)
        fn_lbl = QLabel(filename)
        fn_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; font-weight: 600;"
            "background: transparent;"
        )
        fn_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        fname_row.addWidget(fn_lbl, 1)
        v.addLayout(fname_row)

        # Barra de progreso
        self._dl_bar = QProgressBar()
        self._dl_bar.setRange(0, 1000)
        self._dl_bar.setValue(0)
        self._dl_bar.setTextVisible(False)
        self._dl_bar.setFixedHeight(5)
        self._dl_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {COLORS['border']};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {COLORS['accent']};
                border-radius: 3px;
            }}
        """)
        v.addWidget(self._dl_bar)

        # Estadísticas
        self._dl_stats = QLabel("Iniciando descarga…")
        self._dl_stats.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        v.addWidget(self._dl_stats)

        v.addStretch()
        return w

    def _page_verifying(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(22, 26, 22, 26)
        v.setSpacing(0)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addStretch()

        self._spin_lbl = QLabel()
        self._spin_lbl.setFixedSize(26, 26)
        self._spin_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_lbl.setStyleSheet("background: transparent;")
        self._spin_lbl.setPixmap(icon_pixmap("loader", COLORS["accent"], 22))
        row.addWidget(self._spin_lbl)

        spin_text = QLabel("Verificando integridad SHA-256…")
        spin_text.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 13px; background: transparent;"
        )
        row.addWidget(spin_text)
        row.addStretch()
        v.addLayout(row)

        return w

    def _page_ready(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)

        # Fila de éxito
        row = QHBoxLayout()
        row.setSpacing(13)

        ok_box = QFrame()
        ok_box.setFixedSize(42, 42)
        ok_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(59, 211, 124, 0.14);
                border: 1px solid rgba(59, 211, 124, 0.40);
                border-radius: 9px;
            }}
        """)
        ob = QVBoxLayout(ok_box)
        ob.setContentsMargins(0, 0, 0, 0)
        ok_icon = QLabel()
        ok_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok_icon.setPixmap(icon_pixmap("check", COLORS["success"], 22))
        ok_icon.setStyleSheet("background: transparent;")
        ob.addWidget(ok_icon, 0, Qt.AlignmentFlag.AlignCenter)
        row.addWidget(ok_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        ready_title = QLabel("¡Actualización lista para instalar!")
        ready_title.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        text_col.addWidget(ready_title)
        ready_sub = QLabel(
            f"PDFlex v{self._info.version}  ·  Integridad SHA-256 verificada ✓"
        )
        ready_sub.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        text_col.addWidget(ready_sub)
        row.addLayout(text_col, 1)
        v.addLayout(row)

        # Info de reinicio
        info_box = QFrame()
        info_box.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['surface_3']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
        """)
        ib_layout = QHBoxLayout(info_box)
        ib_layout.setContentsMargins(12, 10, 12, 10)
        ib_layout.setSpacing(9)

        info_icon = QLabel()
        info_icon.setFixedSize(14, 14)
        info_icon.setPixmap(icon_pixmap("info", COLORS["text_dim"], 14))
        info_icon.setStyleSheet("background: transparent;")
        ib_layout.addWidget(info_icon)

        info_text = QLabel(
            "PDFlex se cerrará e iniciará el instalador automáticamente."
        )
        info_text.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 12px; background: transparent;"
        )
        ib_layout.addWidget(info_text, 1)
        v.addWidget(info_box)

        return w

    def _page_error(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(13)

        err_box = QFrame()
        err_box.setFixedSize(42, 42)
        err_box.setStyleSheet(f"""
            QFrame {{
                background: rgba(229, 72, 77, 0.14);
                border: 1px solid rgba(229, 72, 77, 0.40);
                border-radius: 9px;
            }}
        """)
        eb = QVBoxLayout(err_box)
        eb.setContentsMargins(0, 0, 0, 0)
        err_icon = QLabel()
        err_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_icon.setPixmap(icon_pixmap("x", COLORS["danger"], 22))
        err_icon.setStyleSheet("background: transparent;")
        eb.addWidget(err_icon, 0, Qt.AlignmentFlag.AlignCenter)
        row.addWidget(err_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        err_title = QLabel("Error al actualizar")
        err_title.setStyleSheet(
            f"color: {COLORS['danger']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        text_col.addWidget(err_title)

        self._err_msg = QLabel("Ha ocurrido un error inesperado.")
        self._err_msg.setWordWrap(True)
        self._err_msg.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent;"
        )
        text_col.addWidget(self._err_msg)
        row.addLayout(text_col, 1)
        v.addLayout(row)

        v.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # Máquina de estados
    # ─────────────────────────────────────────────────────────────────────────

    def _set_page(self, page: int) -> None:
        self._body_stack.setCurrentIndex(page)
        self._footer_info.setText("")
        self._spinner_timer.stop()

        if page == _PAGE_AVAILABLE:
            self._title_lbl.setText("Actualización disponible")
            size_str = format_bytes(self._info.size_bytes) if self._info.size_bytes else ""
            self._subtitle_lbl.setText(
                f"v{APP_VERSION} instalado  →  v{self._info.version} disponible"
                + (f"  ·  {size_str}" if size_str else "")
            )
            self._btn_primary.setText("Descargar e instalar")
            self._btn_primary.setEnabled(True)
            self._btn_primary.setStyleSheet(self._style_primary())
            self._btn_later.setVisible(not self._forced)
            self._btn_cancel_dl.setVisible(False)
            self._close_btn.setEnabled(True)

        elif page == _PAGE_DOWNLOADING:
            self._title_lbl.setText("Descargando actualización")
            size_str = format_bytes(self._info.size_bytes) if self._info.size_bytes else ""
            self._subtitle_lbl.setText(
                f"v{self._info.version}" + (f"  ·  {size_str}" if size_str else "")
            )
            self._btn_primary.setText("Descargando…")
            self._btn_primary.setEnabled(False)
            self._btn_primary.setStyleSheet(self._style_primary(disabled=True))
            self._btn_later.setVisible(False)
            self._btn_cancel_dl.setVisible(not self._forced)
            self._close_btn.setEnabled(self._forced)
            self._dl_bar.setValue(0)
            self._dl_stats.setText("Iniciando descarga…")

        elif page == _PAGE_VERIFYING:
            self._title_lbl.setText("Verificando integridad")
            self._subtitle_lbl.setText("Comprobando firma SHA-256…")
            self._btn_primary.setText("Verificando…")
            self._btn_primary.setEnabled(False)
            self._btn_primary.setStyleSheet(self._style_primary(disabled=True))
            self._btn_later.setVisible(False)
            self._btn_cancel_dl.setVisible(False)
            self._close_btn.setEnabled(self._forced)
            self._spinner_frame = 0
            self._spinner_timer.start()

        elif page == _PAGE_READY:
            self._title_lbl.setText("Lista para instalar")
            self._subtitle_lbl.setText(
                "PDFlex se cerrará para iniciar el instalador"
            )
            self._btn_primary.setText("Instalar y reiniciar")
            self._btn_primary.setEnabled(True)
            self._btn_primary.setStyleSheet(self._style_success())
            self._btn_later.setVisible(False)
            self._btn_cancel_dl.setVisible(False)
            self._close_btn.setEnabled(self._forced)

        elif page == _PAGE_ERROR:
            self._title_lbl.setText("Error al actualizar")
            self._subtitle_lbl.setText("No se pudo completar la actualización")
            self._btn_primary.setText("Reintentar descarga")
            self._btn_primary.setEnabled(True)
            self._btn_primary.setStyleSheet(self._style_primary())
            self._btn_later.setVisible(not self._forced)
            self._btn_cancel_dl.setVisible(False)
            self._close_btn.setEnabled(True)

    # ─────────────────────────────────────────────────────────────────────────
    # Lógica de descarga
    # ─────────────────────────────────────────────────────────────────────────

    def _on_primary_clicked(self) -> None:
        page = self._body_stack.currentIndex()
        if page in (_PAGE_AVAILABLE, _PAGE_ERROR):
            self._start_download()
        elif page == _PAGE_READY:
            self._do_install()

    def _start_download(self) -> None:
        """Inicia la descarga. Evita doble inicio."""
        if self._download_thread and self._download_thread.isRunning():
            return

        self._set_page(_PAGE_DOWNLOADING)

        self._download_worker = UpdateDownloadWorker(self._info)
        self._download_thread = UpdateDownloadThread(self._download_worker)

        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.status_message.connect(self._on_status_msg)
        self._download_worker.verifying.connect(lambda: self._set_page(_PAGE_VERIFYING))
        self._download_worker.verified.connect(self._on_verified)
        self._download_worker.hash_mismatch.connect(self._on_hash_mismatch)
        self._download_worker.download_error.connect(self._on_dl_error)

        self._download_thread.start()

    def _cancel_download(self) -> None:
        if self._download_worker:
            self._download_worker.cancel()
        if self._download_thread:
            self._download_thread.quit()
            self._download_thread.wait(3_000)
        self._download_worker = None
        self._download_thread = None
        self._set_page(_PAGE_AVAILABLE)

    # ── Slots del worker ──────────────────────────────────────────────────────

    def _on_progress(self, downloaded: int, total: int, speed: float) -> None:
        if total > 0:
            self._dl_bar.setValue(int(downloaded / total * 1000))

        parts = [format_bytes(downloaded)]
        if total > 0:
            parts.append(f"de {format_bytes(total)}")
        if speed > 100:
            parts.append(f"·  {format_bytes(int(speed))}/s")
            remaining = (total - downloaded) / speed if (total > downloaded and speed > 0) else 0
            if 1 < remaining < 3_600:
                if remaining < 60:
                    parts.append(f"·  ~{int(remaining)}s")
                else:
                    parts.append(f"·  ~{int(remaining / 60)}min")

        self._dl_stats.setText("  ".join(parts))

    def _on_status_msg(self, msg: str) -> None:
        self._dl_stats.setText(msg)

    def _on_verified(self, installer_path: str) -> None:
        self._installer_path = installer_path
        self._set_page(_PAGE_READY)

    def _on_hash_mismatch(self) -> None:
        self._err_msg.setText(
            "La verificación de integridad falló.\n\n"
            "El archivo descargado está corrupto o fue modificado en tránsito.\n"
            "Intenta de nuevo; si el problema persiste contacta soporte."
        )
        self._set_page(_PAGE_ERROR)

    def _on_dl_error(self, msg: str) -> None:
        self._err_msg.setText(msg)
        self._set_page(_PAGE_ERROR)

    # ── Instalación ───────────────────────────────────────────────────────────

    def _do_install(self) -> None:
        if not self._installer_path:
            self._err_msg.setText("Ruta del instalador no disponible. Intenta descargar de nuevo.")
            self._set_page(_PAGE_ERROR)
            return
        try:
            launch_installer_and_quit(self._installer_path)
        except FileNotFoundError:
            self._err_msg.setText(
                "El archivo del instalador ya no existe en la ubicación temporal.\n"
                "Por favor descarga de nuevo."
            )
            self._installer_path = None
            self._set_page(_PAGE_ERROR)
        except Exception as exc:
            self._err_msg.setText(f"No se pudo iniciar el instalador:\n{exc}")
            self._set_page(_PAGE_ERROR)

    # ─────────────────────────────────────────────────────────────────────────
    # Spinner
    # ─────────────────────────────────────────────────────────────────────────

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % _SPINNER_FRAMES
        angle = self._spinner_frame * _SPINNER_STEP_DEG
        self._spin_lbl.setPixmap(icon_pixmap("loader", COLORS["accent"], 22, angle))

    # ─────────────────────────────────────────────────────────────────────────
    # Eventos de ventana
    # ─────────────────────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            page = self._body_stack.currentIndex()
            if self._forced:
                self._quit_pdflex()
                event.accept()
                return
            if page in (_PAGE_DOWNLOADING, _PAGE_VERIFYING, _PAGE_READY):
                event.accept()
                return
        super().keyPressEvent(event)

    def reject(self) -> None:
        page = self._body_stack.currentIndex()
        if self._forced:
            self._quit_pdflex()
            return
        if page in (_PAGE_DOWNLOADING, _PAGE_VERIFYING):
            return  # usa el botón Cancelar descarga
        if page == _PAGE_READY:
            return  # debe instalar
        self._safe_cleanup_thread()
        UpdaterDialog._active = None
        super().reject()

    def closeEvent(self, event) -> None:
        # Fallback: captura cierres externos (OS, close() explícito, etc.)
        self._safe_cleanup_thread()
        UpdaterDialog._active = None
        if self._forced and not self._quitting_app:
            self._quitting_app = True
            QTimer.singleShot(0, QApplication.quit)
        event.accept()

    def _quit_pdflex(self) -> None:
        self._quitting_app = True
        self._safe_cleanup_thread()
        UpdaterDialog._active = None
        self.close()
        QTimer.singleShot(0, QApplication.quit)

    def _safe_cleanup_thread(self) -> None:
        self._spinner_timer.stop()
        if self._download_thread and self._download_thread.isRunning():
            if self._download_worker:
                self._download_worker.cancel()
            self._download_thread.quit()
            self._download_thread.wait(3_000)

    # ─────────────────────────────────────────────────────────────────────────
    # Drag para mover la ventana frameless
    # ─────────────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ─────────────────────────────────────────────────────────────────────────
    # Estilos de botones
    # ─────────────────────────────────────────────────────────────────────────

    def _style_primary(self, disabled: bool = False) -> str:
        if disabled:
            return f"""
                QPushButton {{
                    background: {COLORS['surface_3']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 7px;
                    color: {COLORS['text_dim']};
                    font-weight: 600;
                    padding: 0 14px;
                }}
            """
        return f"""
            QPushButton {{
                background: {COLORS['accent']};
                border: 1px solid {COLORS['accent']};
                border-radius: 7px;
                color: white;
                font-weight: 600;
                padding: 0 14px;
            }}
            QPushButton:hover   {{ background: {COLORS['accent_hover']}; }}
            QPushButton:pressed {{ background: {COLORS['accent_press']}; }}
        """

    def _style_secondary(self) -> str:
        return f"""
            QPushButton {{
                background: {COLORS['surface_3']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 7px;
                color: {COLORS['text']};
                font-weight: 500;
                padding: 0 14px;
            }}
            QPushButton:hover   {{
                background: {COLORS['border']};
                border-color: #44444E;
            }}
            QPushButton:pressed {{ background: {COLORS['surface_2']}; }}
        """

    def _style_success(self) -> str:
        return f"""
            QPushButton {{
                background: {COLORS['success']};
                border: 1px solid {COLORS['success']};
                border-radius: 7px;
                color: #0A0A0B;
                font-weight: 700;
                padding: 0 14px;
            }}
            QPushButton:hover   {{ background: #4EE090; }}
            QPushButton:pressed {{ background: #2EC668; }}
        """
