"""Premium bootstrapper for the PDFlex Windows installer.

The bootstrapper is the user-facing setup experience. It validates and launches
the internal Inno Setup engine in silent mode, while keeping compatibility with
automation and the existing PDFlex updater.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from core.update_config import APP_VERSION
except Exception:
    APP_VERSION = "2.0.3"


APP_NAME = "PDFlex"
APP_PUBLISHER = "GRUPO OCMX"
APP_URL = "https://grupocmx.mx"
ENGINE_FILE = f"{APP_NAME}_{APP_VERSION}_Engine.exe"
MANIFEST_FILE = "setup_bootstrapper_manifest.json"
REGISTRY_PATH = rf"Software\{APP_PUBLISHER}\{APP_NAME}"
DEFAULT_INSTALL_DIR = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / APP_PUBLISHER
    / APP_NAME
)


@dataclass
class SetupManifest:
    app_name: str = APP_NAME
    version: str = APP_VERSION
    publisher: str = APP_PUBLISHER
    engine_file: str = ENGINE_FILE
    engine_sha256: str = ""
    engine_size_bytes: int = 0
    built_at: str = ""


@dataclass
class CliOptions:
    engine_path: Path | None
    passthrough_args: list[str]
    force_ui: bool
    self_test_ui: bool
    silent: bool
    help_requested: bool


@dataclass
class InstallOptions:
    engine_path: Path
    manifest: SetupManifest
    install_dir: Path
    create_desktop_shortcut: bool
    launch_after_install: bool
    extra_engine_args: list[str]
    log_path: Path


class SetupLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")


def parse_cli(argv: list[str]) -> CliOptions:
    engine_path: Path | None = None
    passthrough: list[str] = []
    force_ui = False
    self_test_ui = False
    help_requested = False

    index = 0
    while index < len(argv):
        arg = argv[index]
        lower = arg.lower()
        if lower in ("--help", "-h", "/?"):
            help_requested = True
        elif lower == "--ui":
            force_ui = True
        elif lower == "--self-test-ui":
            self_test_ui = True
        elif lower == "--engine" and index + 1 < len(argv):
            index += 1
            engine_path = Path(argv[index]).expanduser()
        elif lower.startswith("--engine="):
            engine_path = Path(arg.split("=", 1)[1]).expanduser()
        elif lower in ("--silent", "-s"):
            passthrough.append("/SILENT")
        elif lower in ("--very-silent", "--verysilent"):
            passthrough.append("/VERYSILENT")
        else:
            passthrough.append(arg)
        index += 1

    silent = any(
        arg.upper().startswith("/SILENT") or arg.upper().startswith("/VERYSILENT")
        for arg in passthrough
    )
    return CliOptions(engine_path, passthrough, force_ui, self_test_ui, silent, help_requested)


def resource_roots() -> list[Path]:
    roots: list[Path] = []
    base_values = (
        getattr(sys, "_MEIPASS", None),
        Path(__file__).resolve().parent,
        Path(sys.executable).resolve().parent,
        Path.cwd(),
    )
    for value in base_values:
        if value:
            path = Path(value)
            if path not in roots:
                roots.append(path)
            for extra in (path / ".nuitka_build", path.parent / ".nuitka_build"):
                if extra not in roots:
                    roots.append(extra)
    return roots


def load_manifest() -> SetupManifest:
    for root in resource_roots():
        candidate = root / MANIFEST_FILE
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return SetupManifest(
                    app_name=str(data.get("app_name") or APP_NAME),
                    version=str(data.get("version") or APP_VERSION),
                    publisher=str(data.get("publisher") or APP_PUBLISHER),
                    engine_file=str(data.get("engine_file") or ENGINE_FILE),
                    engine_sha256=str(data.get("engine_sha256") or ""),
                    engine_size_bytes=int(data.get("engine_size_bytes") or 0),
                    built_at=str(data.get("built_at") or ""),
                )
            except Exception:
                continue
    return SetupManifest()


def find_engine(manifest: SetupManifest, explicit_path: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(explicit_path)

    engine_names = [manifest.engine_file, ENGINE_FILE]
    for root in resource_roots():
        for name in engine_names:
            candidates.extend(
                [
                    root / name,
                    root / "dist" / name,
                    root.parent / "dist" / name,
                    root.parent / name,
                ]
            )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    searched = "\n".join(str(path) for path in candidates[:12])
    raise FileNotFoundError(
        f"No se encontró el motor de instalación {manifest.engine_file}.\n"
        f"Rutas revisadas:\n{searched}"
    )


def logs_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / APP_NAME / "Setup" / "logs"


def create_log_path(prefix: str = "PDFlexSetup") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return logs_dir() / f"{prefix}_{APP_VERSION}_{stamp}.log"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_engine(engine_path: Path, manifest: SetupManifest, logger: SetupLogger) -> None:
    logger.write(f"Validando motor: {engine_path}")
    if not engine_path.exists():
        raise FileNotFoundError(f"Motor de instalación no encontrado: {engine_path}")

    size = engine_path.stat().st_size
    if size < 5 * 1024 * 1024:
        raise RuntimeError("El motor de instalación parece incompleto.")

    if manifest.engine_size_bytes and size != manifest.engine_size_bytes:
        raise RuntimeError(
            "El tamaño del motor no coincide con el manifest del build."
        )

    if manifest.engine_sha256:
        actual_hash = file_sha256(engine_path)
        logger.write(f"SHA-256 calculado: {actual_hash}")
        if actual_hash.lower() != manifest.engine_sha256.lower():
            raise RuntimeError("La integridad del motor de instalación no es válida.")


def read_install_path_from_registry() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, REGISTRY_PATH) as key:
                    value, _ = winreg.QueryValueEx(key, "InstallPath")
                    if value:
                        return Path(str(value))
            except OSError:
                continue
    except Exception:
        return None
    return None


def installed_version() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, REGISTRY_PATH) as key:
                    value, _ = winreg.QueryValueEx(key, "Version")
                    if value:
                        return str(value)
            except OSError:
                continue
    except Exception:
        return None
    return None


def build_engine_args(options: InstallOptions) -> list[str]:
    args = [
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        f"/LOG={options.log_path}",
        f"/DIR={options.install_dir}",
    ]
    args.append("/TASKS=desktopicon" if options.create_desktop_shortcut else "/TASKS=")

    for arg in options.extra_engine_args:
        if arg.upper().startswith("/LOG="):
            continue
        if arg.upper().startswith("/DIR="):
            continue
        if arg.upper().startswith("/TASKS="):
            continue
        args.append(arg)
    return args


def ensure_log_arg(args: list[str], log_path: Path) -> list[str]:
    if any(arg.upper().startswith("/LOG") for arg in args):
        return args
    return [*args, f"/LOG={log_path}"]


def run_engine_and_wait(engine_path: Path, args: list[str], logger: SetupLogger) -> int:
    logger.write("Ejecutando motor:")
    logger.write(str(engine_path))
    logger.write(subprocess.list2cmdline(args))

    if sys.platform != "win32":
        completed = subprocess.run([str(engine_path), *args], cwd=str(engine_path.parent))
        return int(completed.returncode)

    params = subprocess.list2cmdline(args)
    return shell_execute_wait(engine_path, params, engine_path.parent, logger)


def shell_execute_wait(
    executable: Path,
    parameters: str,
    working_dir: Path,
    logger: SetupLogger,
) -> int:
    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_SHOWNORMAL = 1
    INFINITE = 0xFFFFFFFF

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p),
            ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p),
            ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p),
            ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p),
            ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong),
            ("hIcon", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = parameters
    info.lpDirectory = str(working_dir)
    info.nShow = SW_SHOWNORMAL

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = kernel32.GetLastError()
        logger.write(f"ShellExecuteExW falló con código Windows {error}.")
        return int(error or 1)

    kernel32.WaitForSingleObject(info.hProcess, INFINITE)
    exit_code = ctypes.c_ulong()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
    kernel32.CloseHandle(info.hProcess)
    logger.write(f"Codigo de salida del motor: {exit_code.value}")
    return int(exit_code.value)


def launch_pdflex(install_dir: Path, logger: SetupLogger) -> None:
    exe = install_dir / "PDFlex.exe"
    if not exe.exists():
        registry_path = read_install_path_from_registry()
        if registry_path:
            exe = registry_path / "PDFlex.exe"
    if exe.exists():
        logger.write(f"Lanzando PDFlex: {exe}")
        subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
    else:
        logger.write("PDFlex.exe no fue localizado para abrir al finalizar.")


def summarize_exit_code(code: int) -> str:
    if code == 0:
        return "Instalación completada correctamente."
    if code == 1223:
        return "Permiso de administrador cancelado por el usuario."
    if code == 2:
        return "La instalación fue cancelada."
    return f"El motor de instalación terminó con código {code}."


def print_help() -> None:
    text = f"""
PDFlex Setup {APP_VERSION}

Uso:
  PDFlex_{APP_VERSION}_Setup.exe
  PDFlex_{APP_VERSION}_Setup.exe /SILENT /NORESTART
  PDFlex_{APP_VERSION}_Setup.exe --engine C:\\ruta\\PDFlex_{APP_VERSION}_Engine.exe

Opciones:
  --ui              Fuerza la interfaz gráfica aunque se pasen argumentos.
  --engine <ruta>   Usa un motor Inno externo para pruebas.
  --silent          Alias de /SILENT.
  --very-silent     Alias de /VERYSILENT.
  --self-test-ui    Inicializa la UI y termina sin instalar.
"""
    print(text.strip())


def run_headless(cli: CliOptions) -> int:
    manifest = load_manifest()
    log_path = create_log_path()
    logger = SetupLogger(log_path)
    try:
        engine = find_engine(manifest, cli.engine_path)
        validate_engine(engine, manifest, logger)
        args = ensure_log_arg(cli.passthrough_args, log_path)
        if not any(arg.upper().startswith("/SUPPRESSMSGBOXES") for arg in args):
            args.append("/SUPPRESSMSGBOXES")
        code = run_engine_and_wait(engine, args, logger)
        logger.write(summarize_exit_code(code))
        return code
    except Exception as exc:
        logger.write(f"Error fatal: {exc}")
        return 1


def import_qt():
    from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QSizePolicy,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    return {
        "QApplication": QApplication,
        "QCheckBox": QCheckBox,
        "QColor": QColor,
        "QDesktopServices": QDesktopServices,
        "QFileDialog": QFileDialog,
        "QFont": QFont,
        "QFrame": QFrame,
        "QGraphicsDropShadowEffect": QGraphicsDropShadowEffect,
        "QHBoxLayout": QHBoxLayout,
        "QIcon": QIcon,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMessageBox": QMessageBox,
        "QPainter": QPainter,
        "QPixmap": QPixmap,
        "QProgressBar": QProgressBar,
        "QPushButton": QPushButton,
        "QSizePolicy": QSizePolicy,
        "QTextEdit": QTextEdit,
        "QThread": QThread,
        "QTimer": QTimer,
        "QUrl": QUrl,
        "Qt": Qt,
        "QVBoxLayout": QVBoxLayout,
        "QHBoxLayout": QHBoxLayout,
        "QWidget": QWidget,
        "pyqtSignal": pyqtSignal,
    }


QT = None


def icon_path() -> Path | None:
    for root in resource_roots():
        for candidate in (root / "assets" / "icon.png", root / "icon.png"):
            if candidate.exists():
                return candidate
    return None


def create_qt_classes():
    global QT
    if QT is None:
        QT = import_qt()

    QThread = QT["QThread"]
    pyqtSignal = QT["pyqtSignal"]
    QFrame = QT["QFrame"]
    QLabel = QT["QLabel"]
    QHBoxLayout = QT["QHBoxLayout"]
    QVBoxLayout = QT["QVBoxLayout"]
    QWidget = QT["QWidget"]
    Qt = QT["Qt"]
    QPainter = QT["QPainter"]
    QColor = QT["QColor"]
    QPixmap = QT["QPixmap"]
    QFont = QT["QFont"]
    QGraphicsDropShadowEffect = QT["QGraphicsDropShadowEffect"]
    QLineEdit = QT["QLineEdit"]
    QPushButton = QT["QPushButton"]
    QCheckBox = QT["QCheckBox"]
    QProgressBar = QT["QProgressBar"]
    QTextEdit = QT["QTextEdit"]

    class InstallerWorker(QThread):
        progress = pyqtSignal(int, str)
        detail = pyqtSignal(str)
        finished = pyqtSignal(int, str, str)

        def __init__(self, options: InstallOptions) -> None:
            super().__init__()
            self.options = options

        def run(self) -> None:
            logger = SetupLogger(self.options.log_path)
            started = time.monotonic()
            try:
                self.detail.emit(f"Log: {self.options.log_path}")
                self.progress.emit(8, "Validando integridad del instalador")
                validate_engine(self.options.engine_path, self.options.manifest, logger)
                self.detail.emit("Motor validado correctamente.")

                self.progress.emit(28, "Preparando instalación")
                args = build_engine_args(self.options)
                self.detail.emit("Solicitando permisos de administrador de Windows.")

                self.progress.emit(44, "Instalando PDFlex")
                code = run_engine_and_wait(self.options.engine_path, args, logger)
                if code != 0:
                    message = summarize_exit_code(code)
                    logger.write(message)
                    self.finished.emit(code, message, str(self.options.log_path))
                    return

                self.progress.emit(88, "Verificando resultado")
                install_path = read_install_path_from_registry() or self.options.install_dir
                exe_path = install_path / "PDFlex.exe"
                if not exe_path.exists():
                    logger.write(f"Advertencia: no se encontró {exe_path}")

                if self.options.launch_after_install:
                    launch_pdflex(install_path, logger)

                elapsed = time.monotonic() - started
                logger.write(f"Instalación finalizada en {elapsed:.1f}s.")
                self.progress.emit(100, "Listo")
                self.finished.emit(0, "PDFlex quedó instalado correctamente.", str(self.options.log_path))
            except Exception as exc:
                logger.write(f"Error fatal: {exc}")
                self.finished.emit(1, str(exc), str(self.options.log_path))

    class AccentPanel(QFrame):
        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("AccentPanel")
            self.setMinimumWidth(310)
            self.setMaximumWidth(330)

        def paintEvent(self, event) -> None:  # noqa: N802
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect()
            painter.fillRect(rect, QColor("#0f7a68"))
            painter.setBrush(QColor(255, 255, 255, 26))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(rect.width() - 165, 24, 260, 260)
            painter.setBrush(QColor(255, 255, 255, 18))
            painter.drawEllipse(-92, rect.height() - 190, 250, 250)
            super().paintEvent(event)

    class StepItem(QFrame):
        def __init__(self, number: int, title: str, text: str) -> None:
            super().__init__()
            self.setObjectName("StepItem")
            self.dot = QLabel(str(number))
            self.dot.setObjectName("StepDot")
            self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.title = QLabel(title)
            self.title.setObjectName("StepTitle")
            self.text = QLabel(text)
            self.text.setObjectName("StepText")
            self.text.setWordWrap(True)

            body = QVBoxLayout()
            body.setContentsMargins(0, 0, 0, 0)
            body.setSpacing(2)
            body.addWidget(self.title)
            body.addWidget(self.text)

            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(body, 1)
            self.set_state("pending")

        def set_state(self, state: str) -> None:
            self.setProperty("state", state)
            self.dot.setProperty("state", state)
            self.title.setProperty("state", state)
            for widget in (self, self.dot, self.title):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    class SetupWindow(QWidget):
        def __init__(self, cli: CliOptions) -> None:
            super().__init__()
            self.cli = cli
            self.manifest = load_manifest()
            self.engine_path = find_engine(self.manifest, cli.engine_path)
            self.log_path = create_log_path()
            self.worker = None
            self.progress_target = 0

            installed = installed_version()
            self.is_upgrade = installed is not None
            self.install_dir = read_install_path_from_registry() or DEFAULT_INSTALL_DIR

            self.setWindowTitle(f"{APP_NAME} Setup")
            self.setMinimumSize(860, 620)
            self.resize(900, 620)
            icon = icon_path()
            if icon:
                self.setWindowIcon(QT["QIcon"](str(icon)))

            self._build_ui(installed)
            self._apply_style()
            self._set_steps(0)

            self.progress_timer = QT["QTimer"](self)
            self.progress_timer.timeout.connect(self._animate_progress)

        def _build_ui(self, installed: str | None) -> None:
            root = QHBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)

            accent = AccentPanel()
            accent_layout = QVBoxLayout(accent)
            accent_layout.setContentsMargins(24, 32, 24, 28)
            accent_layout.setSpacing(18)

            logo = QLabel()
            logo.setObjectName("Logo")
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon = icon_path()
            if icon:
                pix = QPixmap(str(icon)).scaled(
                    74,
                    74,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                logo.setPixmap(pix)
            logo_wrap = QFrame()
            logo_wrap.setObjectName("LogoWrap")
            logo_layout = QVBoxLayout(logo_wrap)
            logo_layout.setContentsMargins(14, 14, 14, 14)
            logo_layout.addWidget(logo)
            accent_layout.addWidget(logo_wrap, 0, Qt.AlignmentFlag.AlignLeft)

            brand = QLabel("PDFlex")
            brand.setObjectName("Brand")
            brand.setMinimumHeight(44)
            subtitle = QLabel("Suite profesional para flujo documental PDF")
            subtitle.setObjectName("BrandSubtitle")
            subtitle.setWordWrap(True)
            accent_layout.addWidget(brand)
            accent_layout.addWidget(subtitle)
            accent_layout.addSpacing(12)

            bullets = [
                "Instalación verificada",
                "Actualizaciones limpias",
                "Integridad SHA-256",
                "Logs para soporte",
            ]
            for text in bullets:
                lbl = QLabel(f"✓  {text}")
                lbl.setObjectName("Bullet")
                lbl.setMinimumHeight(24)
                accent_layout.addWidget(lbl)
            accent_layout.addStretch(1)

            meta = QLabel(f"v{self.manifest.version}  ·  {APP_PUBLISHER}")
            meta.setObjectName("Meta")
            accent_layout.addWidget(meta)
            root.addWidget(accent)

            content = QFrame()
            content.setObjectName("Content")
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(34, 30, 34, 28)
            content_layout.setSpacing(18)

            eyebrow = QLabel("INSTALADOR OFICIAL")
            eyebrow.setObjectName("Eyebrow")
            content_layout.addWidget(eyebrow)

            title = QLabel(
                "Actualizar PDFlex" if self.is_upgrade else "Instalar PDFlex"
            )
            title.setObjectName("Title")
            content_layout.addWidget(title)

            status_text = (
                f"Versión instalada: {installed}. Se instalará v{self.manifest.version}."
                if installed
                else f"Se instalará PDFlex v{self.manifest.version} en este equipo."
            )
            intro = QLabel(status_text)
            intro.setObjectName("Intro")
            intro.setWordWrap(True)
            content_layout.addWidget(intro)

            options = QFrame()
            options.setObjectName("Options")
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(26)
            shadow.setColor(QColor(17, 24, 39, 36))
            shadow.setOffset(0, 8)
            options.setGraphicsEffect(shadow)
            options_layout = QVBoxLayout(options)
            options_layout.setContentsMargins(18, 16, 18, 16)
            options_layout.setSpacing(12)

            path_label = QLabel("Carpeta de instalación")
            path_label.setObjectName("FieldLabel")
            options_layout.addWidget(path_label)

            path_row = QHBoxLayout()
            self.path_input = QLineEdit(str(self.install_dir))
            self.path_input.setObjectName("PathInput")
            self.path_input.setMinimumHeight(44)
            browse = QPushButton("Cambiar")
            browse.setObjectName("SecondaryButton")
            browse.setMinimumHeight(44)
            browse.clicked.connect(self._browse_dir)
            path_row.addWidget(self.path_input, 1)
            path_row.addWidget(browse)
            options_layout.addLayout(path_row)

            self.desktop_check = QCheckBox("Crear acceso directo en el Escritorio")
            self.desktop_check.setChecked(False)
            self.desktop_check.setMinimumHeight(26)
            self.launch_check = QCheckBox("Abrir PDFlex al finalizar")
            self.launch_check.setChecked(True)
            self.launch_check.setMinimumHeight(26)
            options_layout.addWidget(self.desktop_check)
            options_layout.addWidget(self.launch_check)
            content_layout.addWidget(options)

            steps_wrap = QFrame()
            steps_wrap.setObjectName("Steps")
            steps_layout = QHBoxLayout(steps_wrap)
            steps_layout.setContentsMargins(0, 0, 0, 0)
            steps_layout.setSpacing(18)
            self.steps = [
                StepItem(1, "Validar", "Comprueba integridad del build."),
                StepItem(2, "Instalar", "Aplica archivos, accesos y registro."),
                StepItem(3, "Verificar", "Confirma el resultado final."),
            ]
            for step in self.steps:
                steps_layout.addWidget(step, 1)
            content_layout.addWidget(steps_wrap)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setTextVisible(False)
            content_layout.addWidget(self.progress)

            self.status_label = QLabel("Listo para comenzar.")
            self.status_label.setObjectName("Status")
            content_layout.addWidget(self.status_label)

            self.details = QTextEdit()
            self.details.setObjectName("Details")
            self.details.setReadOnly(True)
            self.details.setVisible(False)
            self.details.setMinimumHeight(120)
            content_layout.addWidget(self.details)

            actions = QHBoxLayout()
            self.details_btn = QPushButton("Ver detalles")
            self.details_btn.setObjectName("GhostButton")
            self.details_btn.clicked.connect(self._toggle_details)
            self.log_btn = QPushButton("Abrir log")
            self.log_btn.setObjectName("GhostButton")
            self.log_btn.clicked.connect(self._open_log)
            self.log_btn.setEnabled(False)
            actions.addWidget(self.details_btn)
            actions.addWidget(self.log_btn)
            actions.addStretch(1)

            self.cancel_btn = QPushButton("Cancelar")
            self.cancel_btn.setObjectName("SecondaryButton")
            self.cancel_btn.setMinimumHeight(42)
            self.cancel_btn.clicked.connect(self.close)
            self.install_btn = QPushButton("Instalar ahora")
            self.install_btn.setMinimumHeight(42)
            if self.is_upgrade:
                self.install_btn.setText("Actualizar ahora")
            self.install_btn.setObjectName("PrimaryButton")
            self.install_btn.clicked.connect(self._start_install)
            actions.addWidget(self.cancel_btn)
            actions.addWidget(self.install_btn)
            content_layout.addLayout(actions)
            root.addWidget(content, 1)

        def _apply_style(self) -> None:
            self.setStyleSheet(
                """
                QWidget {
                    background: #f6f8fb;
                    color: #111827;
                    font-family: "Segoe UI", Arial, sans-serif;
                    font-size: 13px;
                }
                QLabel {
                    background: transparent;
                }
                #Content { background: #f6f8fb; }
                #AccentPanel {
                    background: #0f7a68;
                }
                #AccentPanel QLabel {
                    background: transparent;
                }
                #Logo {
                    background: transparent;
                }
                #LogoWrap {
                    background: rgba(255,255,255,0.18);
                    border: 1px solid rgba(255,255,255,0.28);
                    border-radius: 18px;
                }
                #Brand {
                    background: transparent;
                    color: white;
                    font-size: 34px;
                    font-weight: 800;
                    letter-spacing: 0;
                }
                #BrandSubtitle {
                    background: transparent;
                    color: rgba(255,255,255,0.86);
                    font-size: 15px;
                    line-height: 1.35;
                }
                #Bullet {
                    background: transparent;
                    color: rgba(255,255,255,0.92);
                    font-size: 14px;
                    padding: 4px 0;
                }
                #Meta {
                    background: transparent;
                    color: rgba(255,255,255,0.78);
                    font-size: 12px;
                }
                #Eyebrow {
                    color: #0f7a68;
                    font-size: 11px;
                    font-weight: 800;
                    letter-spacing: 1px;
                }
                #Title {
                    color: #111827;
                    font-size: 30px;
                    font-weight: 800;
                }
                #Intro {
                    color: #4b5563;
                    font-size: 14px;
                }
                #Options {
                    background: white;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                }
                #FieldLabel {
                    color: #374151;
                    font-size: 12px;
                    font-weight: 700;
                }
                QLineEdit {
                    background: #f9fafb;
                    border: 1px solid #d1d5db;
                    border-radius: 8px;
                    padding: 10px 12px;
                }
                QLineEdit:focus {
                    border: 1px solid #0f7a68;
                    background: white;
                }
                QCheckBox {
                    background: transparent;
                    color: #374151;
                    spacing: 8px;
                }
                #StepItem {
                    background: transparent;
                }
                QCheckBox::indicator {
                    width: 17px;
                    height: 17px;
                    border-radius: 4px;
                    border: 1px solid #9ca3af;
                    background: white;
                }
                QCheckBox::indicator:checked {
                    background: #0f7a68;
                    border: 1px solid #0f7a68;
                }
                #StepDot {
                    min-width: 26px;
                    max-width: 26px;
                    min-height: 26px;
                    max-height: 26px;
                    border-radius: 13px;
                    background: #e5e7eb;
                    color: #6b7280;
                    font-weight: 800;
                }
                #StepDot[state="active"], #StepDot[state="done"] {
                    background: #0f7a68;
                    color: white;
                }
                #StepTitle {
                    color: #374151;
                    font-weight: 800;
                }
                #StepTitle[state="active"], #StepTitle[state="done"] {
                    color: #0f7a68;
                }
                #StepText {
                    color: #6b7280;
                    font-size: 12px;
                }
                QProgressBar {
                    background: #e5e7eb;
                    border: 0;
                    border-radius: 5px;
                    height: 10px;
                }
                QProgressBar::chunk {
                    background: #0f7a68;
                    border-radius: 5px;
                }
                #Status {
                    color: #374151;
                    font-weight: 650;
                }
                #Details {
                    background: #111827;
                    color: #d1fae5;
                    border: 0;
                    border-radius: 8px;
                    font-family: "Cascadia Mono", Consolas, monospace;
                    font-size: 12px;
                    padding: 10px;
                }
                QPushButton {
                    border-radius: 8px;
                    padding: 10px 16px;
                    font-weight: 750;
                }
                #PrimaryButton {
                    background: #0f7a68;
                    color: white;
                    border: 1px solid #0f7a68;
                }
                #PrimaryButton:hover { background: #0b6b5b; }
                #PrimaryButton:disabled {
                    background: #9ca3af;
                    border: 1px solid #9ca3af;
                }
                #SecondaryButton {
                    background: white;
                    color: #111827;
                    border: 1px solid #d1d5db;
                }
                #SecondaryButton:hover { background: #f3f4f6; }
                #GhostButton {
                    background: transparent;
                    color: #0f7a68;
                    border: 1px solid transparent;
                    padding-left: 4px;
                    padding-right: 4px;
                }
                #GhostButton:hover { color: #0b6b5b; }
                """
            )

        def _browse_dir(self) -> None:
            directory = QT["QFileDialog"].getExistingDirectory(
                self,
                "Seleccionar carpeta de instalación",
                self.path_input.text(),
            )
            if directory:
                self.path_input.setText(directory)

        def _toggle_details(self) -> None:
            visible = not self.details.isVisible()
            self.details.setVisible(visible)
            self.details_btn.setText("Ocultar detalles" if visible else "Ver detalles")

        def _open_log(self) -> None:
            if self.log_path.exists():
                QT["QDesktopServices"].openUrl(QT["QUrl"].fromLocalFile(str(self.log_path)))

        def _append_detail(self, text: str) -> None:
            self.details.append(text)

        def _set_steps(self, active_index: int, done: bool = False) -> None:
            for index, step in enumerate(self.steps):
                if done:
                    state = "done"
                elif index < active_index:
                    state = "done"
                elif index == active_index:
                    state = "active"
                else:
                    state = "pending"
                step.set_state(state)

        def _start_install(self) -> None:
            try:
                install_dir = Path(self.path_input.text()).expanduser()
                if not str(install_dir).strip():
                    raise ValueError("Selecciona una carpeta de instalación.")

                options = InstallOptions(
                    engine_path=self.engine_path,
                    manifest=self.manifest,
                    install_dir=install_dir,
                    create_desktop_shortcut=self.desktop_check.isChecked(),
                    launch_after_install=self.launch_check.isChecked(),
                    extra_engine_args=self.cli.passthrough_args,
                    log_path=self.log_path,
                )
                self._lock_ui(True)
                self.details.clear()
                self._append_detail(f"Motor: {self.engine_path}")
                self._append_detail(f"Destino: {install_dir}")
                self._append_detail(f"Log: {self.log_path}")

                self.worker = InstallerWorker(options)
                self.worker.progress.connect(self._on_progress)
                self.worker.detail.connect(self._append_detail)
                self.worker.finished.connect(self._on_finished)
                self.progress_timer.start(160)
                self.worker.start()
            except Exception as exc:
                QT["QMessageBox"].warning(self, "PDFlex Setup", str(exc))

        def _lock_ui(self, locked: bool) -> None:
            self.install_btn.setEnabled(not locked)
            self.cancel_btn.setEnabled(not locked)
            self.path_input.setEnabled(not locked)
            self.desktop_check.setEnabled(not locked)
            self.launch_check.setEnabled(not locked)
            self.status_label.setText("Preparando instalación...")

        def _on_progress(self, value: int, text: str) -> None:
            self.progress_target = max(self.progress_target, value)
            self.status_label.setText(text)
            if value < 35:
                self._set_steps(0)
            elif value < 88:
                self._set_steps(1)
            elif value < 100:
                self._set_steps(2)
            else:
                self._set_steps(0, done=True)

        def _animate_progress(self) -> None:
            current = self.progress.value()
            target = min(self.progress_target, 94)
            if current < target:
                self.progress.setValue(current + 1)

        def _on_finished(self, code: int, message: str, log_path: str) -> None:
            self.progress_timer.stop()
            self.log_path = Path(log_path)
            self.log_btn.setEnabled(self.log_path.exists())
            self._append_detail(message)
            self._lock_ui(False)
            self.cancel_btn.setText("Cerrar")
            self.install_btn.setText("Finalizar")
            self.install_btn.clicked.disconnect()
            self.install_btn.clicked.connect(self.close)

            if code == 0:
                self.progress.setValue(100)
                self.status_label.setText(message)
                self._set_steps(0, done=True)
            else:
                self.status_label.setText(message)
                self.install_btn.setText("Cerrar")
                QT["QMessageBox"].critical(self, "PDFlex Setup", message)

    return InstallerWorker, SetupWindow


def run_ui(cli: CliOptions) -> int:
    global QT
    if QT is None:
        QT = import_qt()
    QApplication = QT["QApplication"]

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} Setup")
    app.setOrganizationName(APP_PUBLISHER)
    icon = icon_path()
    if icon:
        app.setWindowIcon(QT["QIcon"](str(icon)))

    try:
        _, SetupWindow = create_qt_classes()
        window = SetupWindow(cli)
    except Exception as exc:
        log_path = create_log_path()
        SetupLogger(log_path).write(f"Error inicializando UI: {exc}")
        QT["QMessageBox"].critical(
            None,
            "PDFlex Setup",
            f"No se pudo iniciar el instalador.\n\n{exc}\n\nLog: {log_path}",
        )
        return 1

    window.show()
    return int(app.exec())


def run_ui_self_test(cli: CliOptions) -> int:
    global QT
    if QT is None:
        QT = import_qt()

    app = QT["QApplication"](sys.argv)
    app.setApplicationName(f"{APP_NAME} Setup Self Test")
    try:
        _, SetupWindow = create_qt_classes()
        window = SetupWindow(cli)
        window.deleteLater()
        app.processEvents()
        return 0
    except Exception as exc:
        log_path = create_log_path("PDFlexSetupSelfTest")
        SetupLogger(log_path).write(f"Self-test UI falló: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    cli = parse_cli(list(argv or sys.argv[1:]))
    if cli.help_requested:
        print_help()
        return 0
    if cli.self_test_ui:
        return run_ui_self_test(cli)
    if cli.silent and not cli.force_ui:
        return run_headless(cli)
    return run_ui(cli)


if __name__ == "__main__":
    raise SystemExit(main())
