"""Custom dialogs shared by PDFlex tools.

This avoids stock message/input windows so modal feedback keeps the
same dark, polished visual language as the rest of the app.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from ui.common.icons import icon_pixmap, set_button_icon
from ui.styles import COLORS


@dataclass(frozen=True)
class DialogAction:
    key: str
    text: str
    role: str = "secondary"  # primary, secondary, danger


_TONE = {
    "info": {
        "icon": "info",
        "color": COLORS["accent"],
        "soft": "rgba(94, 106, 210, 0.16)",
    },
    "success": {
        "icon": "check",
        "color": COLORS["success"],
        "soft": "rgba(59, 211, 124, 0.14)",
    },
    "warning": {
        "icon": "warning",
        "color": COLORS["warning"],
        "soft": "rgba(245, 166, 35, 0.14)",
    },
    "error": {
        "icon": "x",
        "color": COLORS["danger"],
        "soft": "rgba(229, 72, 77, 0.14)",
    },
    "question": {
        "icon": "info",
        "color": COLORS["accent"],
        "soft": "rgba(94, 106, 210, 0.16)",
    },
}


class AppDialog(QDialog):
    """Small frameless modal dialog with PDFlex styling."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        tone: str = "info",
        details: str = "",
        actions: Iterable[DialogAction] | None = None,
        default_key: str = "ok",
        cancel_key: str = "cancel",
    ) -> None:
        super().__init__(parent)
        self._tone = _TONE.get(tone, _TONE["info"])
        self._result_key = cancel_key
        self._default_key = default_key
        self._cancel_key = cancel_key
        self._drag_pos: Optional[QPoint] = None

        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(620)
        from ui.common.icons import app_qicon
        self.setWindowIcon(app_qicon())

        self._build(title, message, details, list(actions or [
            DialogAction("ok", "OK", "primary"),
        ]))

    def _build(
        self,
        title: str,
        message: str,
        details: str,
        actions: list[DialogAction],
    ) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("AppDialogShell")
        shell.setStyleSheet(f"""
            QFrame#AppDialogShell {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 10px;
            }}
        """)
        outer.addWidget(shell)

        root = QVBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: icon badge + title + close ─────────────────────────
        header = QFrame()
        header.setObjectName("AppDialogHeader")
        header.setStyleSheet(f"""
            QFrame#AppDialogHeader {{
                background-color: {COLORS['surface_2']};
                border-bottom: 1px solid {COLORS['border']};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
        """)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 13, 12, 13)
        h.setSpacing(11)

        icon_box = QFrame()
        icon_box.setFixedSize(36, 36)
        icon_box.setStyleSheet(f"""
            QFrame {{
                background-color: {self._tone['soft']};
                border: 1px solid {self._tone['color']};
                border-radius: 8px;
            }}
        """)
        ib_layout = QVBoxLayout(icon_box)
        ib_layout.setContentsMargins(0, 0, 0, 0)
        ib_lbl = QLabel()
        ib_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ib_lbl.setPixmap(icon_pixmap(self._tone["icon"], self._tone["color"], 18))
        ib_lbl.setStyleSheet("background: transparent;")
        ib_layout.addWidget(ib_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(icon_box)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 14px; font-weight: 600; "
            "background: transparent;"
        )
        h.addWidget(title_lbl, 1)

        close_btn = QPushButton()
        close_btn.setProperty("class", "IconBtn")
        close_btn.setFixedSize(26, 26)
        close_btn.setToolTip("Cerrar")
        set_button_icon(close_btn, "x", size=13, icon_only=True)
        close_btn.clicked.connect(self.reject)
        h.addWidget(close_btn)
        root.addWidget(header)

        # ── Body: message (compact) ─────────────────────────────────────
        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 14)
        body.setSpacing(10)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextFormat(Qt.TextFormat.PlainText)
        msg_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13px; "
            "background: transparent;"
        )
        msg_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.addWidget(msg_lbl)

        if details:
            detail_box = QTextEdit()
            detail_box.setReadOnly(True)
            detail_box.setPlainText(details)
            detail_box.setFixedHeight(80)
            detail_box.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {COLORS['surface_2']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 7px;
                    padding: 6px 10px;
                    color: {COLORS['text_muted']};
                    font-size: 12px;
                }}
            """)
            body.addWidget(detail_box)

        root.addLayout(body)

        # ── Footer: action buttons ──────────────────────────────────────
        footer = QFrame()
        footer.setObjectName("AppDialogFooter")
        footer.setStyleSheet(f"""
            QFrame#AppDialogFooter {{
                background-color: {COLORS['surface_2']};
                border-top: 1px solid {COLORS['border']};
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
            }}
        """)
        f = QHBoxLayout(footer)
        f.setContentsMargins(16, 11, 16, 11)
        f.setSpacing(8)
        f.addStretch(1)

        for action in actions:
            btn = QPushButton(action.text)
            btn.setMinimumWidth(88)
            btn.setFixedHeight(34)
            btn.setProperty("dialogRole", action.role)
            btn.setStyleSheet(_button_style(action.role, self._tone["color"]))
            btn.clicked.connect(lambda _, key=action.key: self._finish(key))
            if action.key == self._default_key:
                btn.setDefault(True)
            f.addWidget(btn)
        root.addWidget(footer)

    def _finish(self, key: str) -> None:
        self._result_key = key
        self.accept()

    def result_key(self) -> str:
        return self._result_key

    def reject(self) -> None:
        self._result_key = self._cancel_key
        super().reject()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class NumberInputDialog(AppDialog):
    """Custom integer input dialog."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        value: int,
        minimum: int,
        maximum: int,
    ) -> None:
        self._spin = QSpinBox()
        self._spin.setRange(minimum, maximum)
        self._spin.setValue(value)
        super().__init__(
            parent,
            title=title,
            message=message,
            tone="question",
            actions=[
                DialogAction("cancel", "Cancelar", "secondary"),
                DialogAction("ok", "Aplicar", "primary"),
            ],
            default_key="ok",
            cancel_key="cancel",
        )
        self._inject_spinbox()

    def _inject_spinbox(self) -> None:
        shell = self.findChild(QFrame, "AppDialogShell")
        if not shell:
            return
        root = shell.layout()
        body_item = root.itemAt(1)
        if body_item is None:
            return
        body_layout = body_item.layout()
        if body_layout is None:
            return
        self._spin.setFixedHeight(36)
        self._spin.setMinimumWidth(140)
        self._spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {COLORS['surface_2']};
                border: 1px solid {COLORS['border_strong']};
                border-radius: 7px;
                padding: 8px 12px;
                color: {COLORS['text']};
                font-size: 13px;
            }}
            QSpinBox:focus {{
                border-color: {COLORS['accent']};
            }}
        """)
        body_layout.addWidget(self._spin)
        self._spin.setFocus()
        self._spin.selectAll()

    def value(self) -> int:
        return int(self._spin.value())


def show_info(parent: QWidget | None, title: str, message: str, *, details: str = "") -> None:
    _show_message(parent, title, message, "info", details)


def show_success(parent: QWidget | None, title: str, message: str, *, details: str = "") -> None:
    _show_message(parent, title, message, "success", details)


def show_warning(parent: QWidget | None, title: str, message: str, *, details: str = "") -> None:
    _show_message(parent, title, message, "warning", details)


def show_error(parent: QWidget | None, title: str, message: str, *, details: str = "") -> None:
    _show_message(parent, title, message, "error", details)


def ask_question(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    accept_text: str = "Continuar",
    cancel_text: str = "Cancelar",
    danger: bool = False,
) -> bool:
    dlg = AppDialog(
        parent,
        title=title,
        message=message,
        tone="warning" if danger else "question",
        actions=[
            DialogAction("cancel", cancel_text, "secondary"),
            DialogAction("accept", accept_text, "danger" if danger else "primary"),
        ],
        default_key="accept",
        cancel_key="cancel",
    )
    dlg.exec()
    return dlg.result_key() == "accept"


def choose_dialog_action(
    parent: QWidget | None,
    title: str,
    message: str,
    actions: Iterable[DialogAction],
    *,
    tone: str = "question",
    default_key: str = "",
    cancel_key: str = "cancel",
) -> str:
    action_list = list(actions)
    if not default_key and action_list:
        default_key = action_list[-1].key
    dlg = AppDialog(
        parent,
        title=title,
        message=message,
        tone=tone,
        actions=action_list,
        default_key=default_key,
        cancel_key=cancel_key,
    )
    dlg.exec()
    return dlg.result_key()


def ask_int(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    value: int,
    minimum: int,
    maximum: int,
) -> tuple[int, bool]:
    dlg = NumberInputDialog(
        parent,
        title=title,
        message=message,
        value=value,
        minimum=minimum,
        maximum=maximum,
    )
    dlg.exec()
    return dlg.value(), dlg.result_key() == "ok"


def _show_message(
    parent: QWidget | None,
    title: str,
    message: str,
    tone: str,
    details: str,
) -> None:
    dlg = AppDialog(
        parent,
        title=title,
        message=message,
        tone=tone,
        details=details,
        actions=[DialogAction("ok", "OK", "primary")],
        default_key="ok",
        cancel_key="ok",
    )
    dlg.exec()


def _button_style(role: str, accent: str) -> str:
    if role == "primary":
        return f"""
            QPushButton {{
                background-color: {accent};
                border: 1px solid {accent};
                border-radius: 7px;
                color: white;
                font-weight: 600;
                padding: 8px 14px;
            }}
            QPushButton:hover {{ background-color: {_lighten(accent)}; }}
            QPushButton:pressed {{ background-color: {_darken(accent)}; }}
        """
    if role == "danger":
        return f"""
            QPushButton {{
                background-color: rgba(229, 72, 77, 0.14);
                border: 1px solid {COLORS['danger']};
                border-radius: 7px;
                color: #FF8A90;
                font-weight: 600;
                padding: 8px 14px;
            }}
            QPushButton:hover {{ background-color: rgba(229, 72, 77, 0.22); }}
            QPushButton:pressed {{ background-color: rgba(229, 72, 77, 0.30); }}
        """
    return f"""
        QPushButton {{
            background-color: {COLORS['surface_3']};
            border: 1px solid {COLORS['border_strong']};
            border-radius: 7px;
            color: {COLORS['text']};
            font-weight: 500;
            padding: 8px 14px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['border']};
            border-color: #44444E;
        }}
        QPushButton:pressed {{ background-color: {COLORS['surface_2']}; }}
    """


def _lighten(color: str) -> str:
    return _mix(color, "#FFFFFF", 0.13)


def _darken(color: str) -> str:
    return _mix(color, "#000000", 0.16)


def _mix(color: str, other: str, amount: float) -> str:
    try:
        value = color.strip().lstrip("#")
        other_value = other.strip().lstrip("#")
        c = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
        o = [int(other_value[i:i + 2], 16) for i in (0, 2, 4)]
        mixed = [round(a + (b - a) * amount) for a, b in zip(c, o)]
        return f"#{mixed[0]:02X}{mixed[1]:02X}{mixed[2]:02X}"
    except Exception:
        return color
