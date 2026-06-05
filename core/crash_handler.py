"""Capturador global de errores no esperados en PDFlex.

Cubre los 3 caminos donde puede ocurrir una excepción no capturada:

  1. sys.excepthook          — hilo principal (antes y durante el event loop)
  2. CrashHandlerApp.notify  — excepciones en slots / callbacks de Qt
  3. threading.excepthook    — hilos Python (threading.Thread)

Para QThread.run() sin try/except, cada thread debe envolver su run()
manualmente (ya hecho en core/updater.py).

Integración en main.py:
    from core.crash_handler import CrashHandlerApp, install_crash_handlers
    app = CrashHandlerApp(sys.argv)
    install_crash_handlers()
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import traceback
import types
from datetime import datetime
from pathlib import Path
from typing import Type

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from core.update_config import APP_VERSION
from ui.common.icons import icon_pixmap, set_button_icon
from ui.styles import COLORS


# ─────────────────────────────────────────────────────────────────────────────
# Contacto de soporte
# ─────────────────────────────────────────────────────────────────────────────

SUPPORT_TEAM  = "Equipo de Sistemas — GRUPO OCMX"
SUPPORT_EMAIL = "sistemas@grupocmx.mx"


# ─────────────────────────────────────────────────────────────────────────────
# Guardia anti-recursión
# ─────────────────────────────────────────────────────────────────────────────

_CRASH_IN_PROGRESS: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Formateado del informe
# ─────────────────────────────────────────────────────────────────────────────

def format_report(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: types.TracebackType | None,
    *,
    context: str = "",
) -> str:
    """Genera el texto completo del informe para copiar / guardar."""
    import platform
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip()

    lines = [
        "=" * 60,
        "  REPORTE DE ERROR — PDFlex",
        "=" * 60,
        f"Fecha:    {ts}",
        f"Versión:  PDFlex v{APP_VERSION}",
        f"Python:   {sys.version.split()[0]}",
    ]
    try:
        lines.append(f"Windows:  {platform.version()}")
    except Exception:
        pass
    if context:
        lines.append(f"Contexto: {context}")
    lines += [
        "",
        f"EXCEPCIÓN: {exc_type.__name__}",
        f"MENSAJE:   {exc_value}",
        "",
        "TRACEBACK:",
        tb_text,
        "",
        "-" * 60,
        f"Por favor envíe este informe a: {SUPPORT_EMAIL}",
        f'Asunto: "Error PDFlex v{APP_VERSION}"',
        "=" * 60,
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Guardado del log en disco (siempre, independiente de Qt)
# ─────────────────────────────────────────────────────────────────────────────

def _save_log(report: str) -> Path | None:
    try:
        log_dir = Path(tempfile.gettempdir()) / "PDFlex" / "crash_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        h = hashlib.md5(report.encode(), usedforsecurity=False).hexdigest()[:6]
        log_file = log_dir / f"crash_{ts}_{h}.txt"
        log_file.write_text(report, encoding="utf-8")
        return log_file
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Fallback nativo (cuando Qt no está disponible)
# ─────────────────────────────────────────────────────────────────────────────

def _native_fallback(report: str) -> None:
    try:
        import ctypes
        short = report[:1200] + ("\n[...truncado...]" if len(report) > 1200 else "")
        ctypes.windll.user32.MessageBoxW(
            0,
            f"PDFlex encontró un error inesperado.\n\n"
            f"Comuníquese con {SUPPORT_EMAIL}\n\n---\n{short}",
            f"PDFlex v{APP_VERSION} — Error",
            0x10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo de crash (hilo principal únicamente)
# ─────────────────────────────────────────────────────────────────────────────

class CrashDialog(QDialog):
    """Diálogo modal que muestra el error y permite copiar el informe."""

    def __init__(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_tb: types.TracebackType | None,
        *,
        log_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._report  = format_report(exc_type, exc_value, exc_tb)
        self._exc_tb  = exc_tb
        self._exc_type  = exc_type
        self._exc_value = exc_value
        self._log_path  = log_path
        self._drag_pos  = None

        self.setWindowTitle("Error inesperado — PDFlex")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(560)
        self.setMaximumWidth(720)
        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())
        self._build()

    # ── Construcción ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("CrashShell")
        shell.setStyleSheet(f"""
            QFrame#CrashShell {{
                background: {COLORS['surface']};
                border: 1px solid rgba(229, 72, 77, 0.55);
                border-radius: 12px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(shell)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 16)
        shell.setGraphicsEffect(shadow)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("CrashHeader")
        header.setStyleSheet(f"""
            QFrame#CrashHeader {{
                background: {COLORS['surface_2']};
                border-bottom: 1px solid rgba(229, 72, 77, 0.30);
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 15, 14, 15)
        h.setSpacing(13)

        icon_box = QFrame()
        icon_box.setFixedSize(42, 42)
        icon_box.setStyleSheet("""
            QFrame {
                background: rgba(229, 72, 77, 0.18);
                border: 1px solid rgba(229, 72, 77, 0.50);
                border-radius: 9px;
            }
        """)
        ib = QVBoxLayout(icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        ib_lbl = QLabel()
        ib_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib_lbl.setPixmap(icon_pixmap("x", COLORS["danger"], 22))
        ib_lbl.setStyleSheet("background: transparent;")
        ib.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("Error inesperado en PDFlex")
        t.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            "background: transparent;"
        )
        title_col.addWidget(t)
        summary = f"{self._exc_type.__name__}: {str(self._exc_value)[:80]}"
        s = QLabel(summary)
        s.setStyleSheet(
            f"color: {COLORS['danger']}; font-size: 11px; background: transparent;"
        )
        s.setToolTip(str(self._exc_value))
        title_col.addWidget(s)
        h.addLayout(title_col, 1)

        close_btn = QPushButton()
        close_btn.setProperty("class", "IconBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.setToolTip("Cerrar PDFlex")
        set_button_icon(close_btn, "x", size=14, icon_only=True)
        close_btn.clicked.connect(self.accept)
        h.addWidget(close_btn)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(14)

        # Aviso de contacto
        contact_box = QFrame()
        contact_box.setStyleSheet("""
            QFrame {
                background: rgba(245, 166, 35, 0.10);
                border: 1px solid rgba(245, 166, 35, 0.32);
                border-radius: 8px;
            }
        """)
        cb = QHBoxLayout(contact_box)
        cb.setContentsMargins(13, 11, 13, 11)
        cb.setSpacing(11)

        wi = QLabel()
        wi.setFixedSize(18, 18)
        wi.setPixmap(icon_pixmap("warning", COLORS["warning"], 18))
        wi.setStyleSheet("background: transparent;")
        cb.addWidget(wi, 0, Qt.AlignmentFlag.AlignTop)

        wt_col = QVBoxLayout()
        wt_col.setSpacing(3)
        wt1 = QLabel("Pedimos disculpas por el inconveniente.")
        wt1.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; font-weight: 600;"
            "background: transparent;"
        )
        wt_col.addWidget(wt1)
        wt2 = QLabel(
            f"Comuníquese con <b>{SUPPORT_TEAM}</b><br>"
            f'<a href="mailto:{SUPPORT_EMAIL}" style="color:#5E6AD2;">'
            f"{SUPPORT_EMAIL}</a>"
        )
        wt2.setTextFormat(Qt.TextFormat.RichText)
        wt2.setOpenExternalLinks(True)
        wt2.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent;"
        )
        wt_col.addWidget(wt2)
        cb.addLayout(wt_col, 1)
        v.addWidget(contact_box)

        # Traceback
        detail_hdr = QLabel("DETALLE TÉCNICO")
        detail_hdr.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 0.8px; background: transparent;"
        )
        v.addWidget(detail_hdr)

        tb_text = "".join(
            traceback.format_exception(self._exc_type, self._exc_value, self._exc_tb)
        ).rstrip()

        tb_box = QTextEdit()
        tb_box.setReadOnly(True)
        tb_box.setPlainText(tb_text)
        tb_box.setFont(QFont("Consolas", 10))
        tb_box.setMinimumHeight(180)
        tb_box.setMaximumHeight(280)
        tb_box.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS['surface_3']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                color: {COLORS['text_muted']};
                padding: 10px 12px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 10px;
            }}
            QScrollBar:vertical {{
                background: transparent; width: 10px;
                margin: 5px 2px 5px 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border_strong']}; min-height: 22px; border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical  {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical  {{ background: none; }}
        """)
        # Auto-scroll al final donde está el nombre de la excepción
        tb_box.verticalScrollBar().setValue(tb_box.verticalScrollBar().maximum())
        v.addWidget(tb_box)

        if self._log_path:
            log_lbl = QLabel(f"Log guardado: {self._log_path}")
            log_lbl.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px; background: transparent;"
            )
            v.addWidget(log_lbl)

        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("CrashFooter")
        footer.setStyleSheet(f"""
            QFrame#CrashFooter {{
                background: {COLORS['surface_2']};
                border-top: 1px solid rgba(229, 72, 77, 0.20);
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(18, 12, 18, 12)
        f.setSpacing(8)

        ts_lbl = QLabel(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ts_lbl.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; background: transparent;"
        )
        f.addWidget(ts_lbl, 1)

        copy_btn = QPushButton("Copiar informe")
        copy_btn.setFixedHeight(34)
        copy_btn.setMinimumWidth(120)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['surface_3']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 7px;
                color: {COLORS['text']};
                font-weight: 500;
                padding: 0 14px;
            }}
            QPushButton:hover  {{ background: {COLORS['border']}; border-color: #44444E; }}
            QPushButton:pressed {{ background: {COLORS['surface_2']}; }}
        """)
        copy_btn.clicked.connect(self._copy_report)
        f.addWidget(copy_btn)

        close_btn = QPushButton("Cerrar PDFlex")
        close_btn.setFixedHeight(34)
        close_btn.setMinimumWidth(130)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(229, 72, 77, 0.18);
                border: 1px solid #E5484D;
                border-radius: 7px;
                color: #FF8A90;
                font-weight: 700;
                padding: 0 14px;
            }
            QPushButton:hover   { background: rgba(229, 72, 77, 0.28); }
            QPushButton:pressed { background: rgba(229, 72, 77, 0.38); }
        """)
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        f.addWidget(close_btn)
        return footer

    def _copy_report(self) -> None:
        app = QApplication.instance()
        if app:
            app.clipboard().setText(self._report)
        btn = self.sender()
        if isinstance(btn, QPushButton):
            original = btn.text()
            btn.setText("¡Copiado!")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1800, lambda: btn.setText(original))

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

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada central (solo hilo principal para diálogos)
# ─────────────────────────────────────────────────────────────────────────────

def _show_dialog(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: types.TracebackType | None,
    log_path: Path | None,
) -> None:
    """Muestra el diálogo de crash. Llamar SOLO desde el hilo principal."""
    app = QApplication.instance()
    if app is None:
        return
    try:
        dlg = CrashDialog(
            exc_type, exc_value, exc_tb,
            log_path=log_path,
            parent=app.activeWindow(),
        )
        dlg.exec()
    except Exception:
        pass  # Si el diálogo mismo falla, salir igualmente


def handle_crash(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: types.TracebackType | None,
    *,
    context: str = "",
    fatal: bool = True,
) -> None:
    """Punto de entrada único para todos los hooks de excepción.

    fatal=True  → muestra diálogo en hilo principal + sys.exit(1)
    fatal=False → solo loguea (hilos de fondo: sus señales manejan el error)
    """
    global _CRASH_IN_PROGRESS

    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    if _CRASH_IN_PROGRESS:
        return
    _CRASH_IN_PROGRESS = True

    # 1. Imprimir siempre a stderr
    try:
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    except Exception:
        pass

    # 2. Guardar log en disco
    report = format_report(exc_type, exc_value, exc_tb, context=context)
    log_path = _save_log(report)

    if not fatal:
        # Los hilos de fondo ya tienen señales de error propias;
        # aquí solo nos aseguramos de guardar el log.
        _CRASH_IN_PROGRESS = False
        return

    # 3. Mostrar diálogo (solo hilo principal)
    app = QApplication.instance()
    if app is not None:
        _show_dialog(exc_type, exc_value, exc_tb, log_path)
    else:
        _native_fallback(report)

    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# QApplication con notify() sobreescrito
# ─────────────────────────────────────────────────────────────────────────────

class CrashHandlerApp(QApplication):
    """QApplication que captura excepciones en slots Qt vía notify()."""

    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_type and not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
                handle_crash(
                    exc_type, exc_value, exc_tb,
                    context=f"Qt slot — {type(receiver).__name__}",
                    fatal=True,
                )
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Instalación de hooks
# ─────────────────────────────────────────────────────────────────────────────

def install_crash_handlers() -> None:
    """Instala sys.excepthook y threading.excepthook.

    Llamar después de crear la instancia de CrashHandlerApp.
    """
    def _excepthook(
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_tb: types.TracebackType | None,
    ) -> None:
        handle_crash(exc_type, exc_value, exc_tb, fatal=True)

    sys.excepthook = _excepthook

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type and not issubclass(
            args.exc_type, (KeyboardInterrupt, SystemExit)
        ):
            handle_crash(
                args.exc_type,
                args.exc_value,       # type: ignore[arg-type]
                args.exc_traceback,
                context=f"Thread: {getattr(args.thread, 'name', '?')}",
                fatal=False,
            )

    threading.excepthook = _thread_excepthook


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper para QThread.run() sin manejo de errores
# ─────────────────────────────────────────────────────────────────────────────

def wrap_qthread(thread_instance, *, fatal: bool = False) -> None:
    """Envuelve el run() de un QThread para capturar excepciones no esperadas."""
    from PyQt6.QtCore import QThread
    original_run = thread_instance.run

    def safe_run() -> None:
        try:
            original_run()
        except Exception:
            exc_type, exc_value, exc_tb = sys.exc_info()
            if exc_type:
                handle_crash(
                    exc_type, exc_value, exc_tb,
                    context=f"QThread: {type(thread_instance).__name__}",
                    fatal=fatal,
                )

    thread_instance.run = safe_run  # type: ignore[method-assign]
