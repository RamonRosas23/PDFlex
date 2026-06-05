"""Cards, headers y divisores reutilizables."""
from __future__ import annotations
from typing import Optional

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel


def make_card(title: Optional[str] = None, hint: Optional[str] = None) -> QFrame:
    card = QFrame()
    card.setProperty("class", "Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(10)
    if title:
        lbl = QLabel(title)
        lbl.setProperty("class", "CardTitle")
        layout.addWidget(lbl)
    if hint:
        h = QLabel(hint)
        h.setProperty("class", "CardHint")
        h.setWordWrap(True)
        layout.addWidget(h)
    return card


def card_layout(card: QFrame) -> QVBoxLayout:
    return card.layout()


def make_page_header(title: str, subtitle: str) -> QVBoxLayout:
    v = QVBoxLayout()
    v.setSpacing(4)
    v.setContentsMargins(0, 0, 0, 0)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    v.addWidget(t)
    s = QLabel(subtitle)
    s.setObjectName("PageSubtitle")
    s.setWordWrap(True)
    v.addWidget(s)
    return v


def make_divider() -> QFrame:
    f = QFrame()
    f.setProperty("class", "Divider")
    f.setFixedHeight(1)
    return f
