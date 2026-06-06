"""Smoke tests: verificar que todas las herramientas instancian sin errores.

No prueban funcionalidad — solo confirman que WindowClass(ctx) no lanza
excepciones con un contexto mínimo válido.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from shell.context import ShellContext
from shell.tray import PdfTray
from shell.word_to_pdf import WordToPdfConverter


# ── Fixtures ──────────────────────────────────────────────────────────────── #


@pytest.fixture(scope="module")
def app():
    """QApplication compartida para todo el módulo."""
    instance = QApplication.instance() or QApplication(sys.argv)
    yield instance


@pytest.fixture
def ctx():
    """ShellContext mínimo usando objetos Qt reales para las señales."""
    return ShellContext(
        tray=PdfTray(),
        word_converter=WordToPdfConverter(),
        open_tool=lambda tool_id, inputs=None: None,
    )


# ── Lista de herramientas ─────────────────────────────────────────────────── #

# (tool_id, module_path, class_name)
TOOLS = [
    ("clasificador",    "ui.clasificador.window",    "ClasificadorWindow"),
    ("comparador",      "ui.comparador.window",      "ComparadorWindow"),
    ("compresor",       "ui.compresor.window",       "CompresorWindow"),
    ("extraer_imagenes","ui.extraer_imagenes.window","ExtraerImagenesWindow"),
    ("firmador",        "ui.firmador.window",        "FirmadorWindow"),
    ("foleador",        "ui.foleador.window",        "FoleadorWindow"),
    ("formularios",     "ui.formularios.window",     "FormulariosWindow"),
    ("imgs_a_pdf",      "ui.imgs_a_pdf.window",      "ImgsAPdfWindow"),
    ("marca_agua",      "ui.marca_agua.window",      "MarcaAguaWindow"),
    ("membretado",      "ui.membretado.window",      "MembretadoWindow"),
    ("ocr",             "ui.ocr.window",             "OcrWindow"),
    ("organizador",     "ui.organizador.window",     "OrganizadorWindow"),
    ("pdf_to_imgs",     "ui.pdf_to_imgs.window",     "PdfToImgsWindow"),
    ("pdf_to_word",     "ui.pdf_to_word.window",     "PdfToWordWindow"),
    ("protector",       "ui.protector.window",       "ProtectorWindow"),
    ("quitar_fondo",    "ui.quitar_fondo.window",    "QuitarFondoWindow"),
    ("redactor",        "ui.redactor.window",        "RedactorWindow"),
    ("reparador",       "ui.reparador.window",       "ReparadorWindow"),
    ("separador",       "ui.separador.window",       "SeparadorWindow"),
    ("unir",            "ui.unir.window",            "UnirWindow"),
    ("word_a_pdf",      "ui.word_a_pdf.window",      "WordAPdfWindow"),
]


# ── Smoke test paramétrico ────────────────────────────────────────────────── #


@pytest.mark.parametrize("tool_id,module_path,class_name", TOOLS, ids=[t[0] for t in TOOLS])
def test_tool_instancia_sin_errores(app, ctx, tool_id, module_path, class_name):
    """Cada herramienta debe instanciarse sin lanzar excepciones."""
    module = __import__(module_path, fromlist=[class_name])
    WindowClass = getattr(module, class_name)
    window = WindowClass(ctx)
    assert window is not None
    window.deleteLater()
    app.processEvents()
