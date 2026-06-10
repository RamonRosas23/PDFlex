"""Proyecto .flexproj: zip con manifest/elementos/reglas/capas/assets; round-trip total."""
import json
import zipfile

import pytest

from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import ImageElement, TextElement
from core.editor.model.layers import Layer
from core.editor.model.page_target import PageTarget
from core.editor.model.placement import Frame
from core.editor.model.rules import PageRule
from core.editor.project.format import ProjectStore, SCHEMA_VERSION


def _doc(src="x.pdf"):
    geo = PageGeometry(index=0, width_pt=595, height_pt=842, rotation=0,
                       derotation_matrix=(1, 0, 0, 1, 0, 0),
                       rotation_matrix=(1, 0, 0, 1, 0, 0))
    return EditorDocument(source_path=src, source_sha256="a" * 64,
                          page_geometries=[geo])


def test_save_load_roundtrip(tmp_path):
    doc = _doc()
    doc.layers.add(Layer(id="sellos", name="Sellos", z=5, opacity=0.8))
    doc.assets["i1"] = b"\x89PNG fake-bytes"
    doc.add_element(1, TextElement(text="hola {pagina}", variables_enabled=True,
                                   frame=Frame(1, 2, 3, 4), layer_id="sellos"))
    doc.add_element(1, ImageElement(asset_id="i1", frame=Frame(9, 9, 50, 50)))
    doc.add_rule(PageRule(element=TextElement(text="regla"),
                          target=PageTarget(mode="even")))
    path = tmp_path / "proyecto.flexproj"

    ProjectStore().save(doc, path)
    loaded = ProjectStore().load(path)

    assert loaded.source_path == doc.source_path
    assert loaded.source_sha256 == doc.source_sha256
    assert len(loaded.page_geometries) == 1
    assert loaded.page_geometries[0].rotation_matrix == (1, 0, 0, 1, 0, 0)
    assert loaded.assets["i1"] == b"\x89PNG fake-bytes"
    els = loaded.elements_by_page[1]
    assert els[0] == doc.elements_by_page[1][0]
    assert els[1] == doc.elements_by_page[1][1]
    assert loaded.rules[0] == doc.rules[0]
    assert loaded.layers.get("sellos").opacity == 0.8


def test_flexproj_is_valid_zip_with_manifest(tmp_path):
    path = tmp_path / "p.flexproj"
    ProjectStore().save(_doc(), path)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert {"manifest.json", "document.json", "elements.json",
                "rules.json", "layers.json"} <= names
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["schema_version"] == SCHEMA_VERSION


def test_load_rejects_newer_schema(tmp_path):
    path = tmp_path / "p.flexproj"
    ProjectStore().save(_doc(), path)
    # Reescribir el manifest con una versión futura
    bumped = tmp_path / "b.flexproj"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(bumped, "w") as zout:
        for item in zin.namelist():
            data = zin.read(item)
            if item == "manifest.json":
                m = json.loads(data)
                m["schema_version"] = 999
                data = json.dumps(m).encode()
            zout.writestr(item, data)
    with pytest.raises(ValueError, match="versión"):
        ProjectStore().load(bumped)


def test_atomic_save_never_leaves_partial_file(tmp_path):
    """Guardar sobre un proyecto existente: el contenido queda actualizado y
    no sobreviven temporales (escritura a .tmp + os.replace)."""
    path = tmp_path / "p.flexproj"
    ProjectStore().save(_doc("uno.pdf"), path)
    ProjectStore().save(_doc("dos.pdf"), path)
    assert ProjectStore().load(path).source_path == "dos.pdf"
    assert not list(tmp_path.glob("*.tmp*"))


def test_autosaver_respects_dirty_and_interval(tmp_path):
    from core.editor.project.autosave import Autosaver
    doc = _doc()
    saver = Autosaver(interval_s=0.0, directory=tmp_path)
    assert saver.maybe_autosave(doc) is None          # sin cambios → no guarda
    saver.mark_dirty()
    p = saver.maybe_autosave(doc)
    assert p is not None and p.exists()
    assert saver.maybe_autosave(doc) is None          # ya no está dirty
    saver.mark_dirty()
    saver.discard(doc)
    assert saver.pending_recoveries() == []
