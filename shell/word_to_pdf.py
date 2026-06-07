"""WordToPdfConverter — convierte .doc/.docx a PDF usando Microsoft Word vía COM.

Requiere Microsoft Office instalado (Windows).
Si Office no está disponible, is_available() retorna False y las llamadas
a convert() lanzan WordNotAvailableError de forma controlada.

La conversión en hilo separado (WordConvertWorker) inicializa el COM
apartment correctamente con pythoncom.CoInitialize().
"""
from __future__ import annotations
import threading
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from core.output_paths import unique_output_path


class WordNotAvailableError(RuntimeError):
    pass


class WordToPdfConverter:
    """Wrapper de win32com para convertir documentos Word a PDF."""

    def __init__(self) -> None:
        self._available: bool | None = None   # None = no comprobado aún

    def is_available(self) -> bool:
        if self._available is None:
            self._available = self._probe()
        return self._available

    def _probe(self) -> bool:
        try:
            import win32com.client  # noqa: F401
            import pythoncom        # noqa: F401
        except ImportError:
            return False
        # Verificar que Word esté instalado consultando el registro de Windows
        try:
            import winreg
            # Cualquiera de las claves COM de Word indica que está instalado
            for key in (
                r"CLSID\{000209FF-0000-0000-C000-000000000046}",  # Word.Application
                r"CLSID\{000209FE-0000-0000-C000-000000000046}",  # Word.Application.16
            ):
                try:
                    winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key)
                    return True
                except OSError:
                    continue
            return False
        except Exception:
            # Si no podemos consultar el registro, asumir disponible
            return True

    # ------------------------------------------------------------------ #
    # API pública (llamar SOLO desde un hilo con CoInitialize activo)
    # ------------------------------------------------------------------ #

    def convert_many_in_thread(
        self,
        paths: List[str],
        out_dir: Path,
        progress: Callable[[int, int, str], None] | None = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[str]:
        """Convierte varios archivos Word a PDF.  Debe llamarse desde un
        hilo que ya haya llamado pythoncom.CoInitialize().
        """
        if not self.is_available():
            raise WordNotAvailableError(
                "Microsoft Office no está instalado o no es accesible."
            )

        import win32com.client

        out_dir.mkdir(parents=True, exist_ok=True)

        # Intentar reutilizar una instancia de Word ya abierta.
        # GetActiveObject ahorra ~2-5 s de arranque cuando Word está corriendo.
        owns_word = False
        try:
            word = win32com.client.GetActiveObject("Word.Application")
        except Exception:
            word = win32com.client.DispatchEx("Word.Application")
            owns_word = True

        word.Visible = False
        word.DisplayAlerts = 0

        results: List[str] = []
        total = len(paths)
        steps = total * 2   # 2 pasos por archivo: abrir + guardar

        try:
            reserved: set[str] = set()
            for i, src in enumerate(paths):
                if cancel_check and cancel_check():
                    break
                src_path = Path(src).resolve()
                out_path = unique_output_path(
                    out_dir,
                    f"{src_path.stem}.pdf",
                    reserved=reserved,
                )
                if progress:
                    progress(
                        i * 2, steps,
                        f"[{i + 1}/{total}] Abriendo {src_path.name}…",
                    )
                try:
                    # ConfirmConversions=False: no preguntar sobre formatos
                    # ReadOnly=True: evita bloqueos de archivo y prompts de guardado
                    # AddToRecentFiles=False: no contaminar el historial de Word
                    # Repair=False (vía OpenAndRepair=False): no intentar reparar
                    doc = word.Documents.Open(
                        str(src_path),
                        ConfirmConversions=False,
                        ReadOnly=True,
                        AddToRecentFiles=False,
                        OpenAndRepair=False,
                    )
                    if progress:
                        progress(
                            i * 2 + 1, steps,
                            f"[{i + 1}/{total}] Guardando {src_path.stem}.pdf…",
                        )
                    doc.SaveAs(str(out_path), FileFormat=17)  # 17 = wdFormatPDF
                    doc.Close(False)
                    results.append(str(out_path))
                except Exception as e:
                    raise RuntimeError(
                        f"Error al convertir {src_path.name}: {e}"
                    ) from e
        finally:
            try:
                if owns_word:
                    word.Quit()
            except Exception:
                pass

        if progress and not (cancel_check and cancel_check()):
            progress(steps, steps, "Conversión completa")

        return results


# ====================================================================== #
#  Worker de Qt para conversión en segundo plano
# ====================================================================== #

class WordConvertWorker(QObject):
    """Ejecuta la conversión Word→PDF en un QThread con COM inicializado."""

    progress = pyqtSignal(int, int, str)    # current, total, message
    finished = pyqtSignal(list)             # list[str] — PDFs convertidos
    error = pyqtSignal(str)

    def __init__(
        self,
        converter: WordToPdfConverter,
        paths: List[str],
        out_dir: Path,
    ) -> None:
        super().__init__()
        self._converter = converter
        self._paths = paths
        self._out_dir = out_dir
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            self.error.emit("pywin32 no está instalado.")
            return

        try:
            results = self._converter.convert_many_in_thread(
                self._paths,
                self._out_dir,
                progress=lambda c, t, m: self.progress.emit(c, t, m),
                cancel_check=self.is_cancelled,
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
