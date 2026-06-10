"""Formato .flexproj (spec §17): zip con manifest + JSON + assets binarios."""
from __future__ import annotations
import json
import os
import zipfile
from dataclasses import asdict
from pathlib import Path

from core.editor.geometry import PageGeometry
from core.editor.model.document_state import EditorDocument
from core.editor.model.elements import element_from_dict
from core.editor.model.layers import LayerStack
from core.editor.model.rules import PageRule

SCHEMA_VERSION = 1


class ProjectStore:
    def save(self, doc: EditorDocument, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps({
                "schema_version": SCHEMA_VERSION, "app": "PDFlex Studio"}))
            z.writestr("document.json", json.dumps({
                "source_path": doc.source_path,
                "source_sha256": doc.source_sha256,
                "pages": [asdict(g) for g in doc.page_geometries]}))
            z.writestr("elements.json", json.dumps({
                str(page): [el.to_dict() for el in els]
                for page, els in doc.elements_by_page.items()}))
            z.writestr("rules.json", json.dumps([r.to_dict() for r in doc.rules]))
            z.writestr("layers.json", json.dumps(doc.layers.to_dict()))
            for asset_id, data in doc.assets.items():
                z.writestr(f"assets/{asset_id}", data)
        os.replace(tmp, path)

    def load(self, path: Path) -> EditorDocument:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
            version = manifest.get("schema_version", 0)
            if version > SCHEMA_VERSION:
                raise ValueError(
                    f"El proyecto usa una versión más nueva ({version}) que esta "
                    f"instalación de PDFlex ({SCHEMA_VERSION}). Actualiza PDFlex.")
            docd = json.loads(z.read("document.json"))
            geos = [PageGeometry(**{**g,
                                    "derotation_matrix": tuple(g["derotation_matrix"]),
                                    "rotation_matrix": tuple(g["rotation_matrix"])})
                    for g in docd["pages"]]
            doc = EditorDocument(
                source_path=docd["source_path"],
                source_sha256=docd["source_sha256"],
                page_geometries=geos,
                layers=LayerStack.from_dict(json.loads(z.read("layers.json"))))
            for page_str, els in json.loads(z.read("elements.json")).items():
                for d in els:
                    doc.add_element(int(page_str), element_from_dict(d))
            doc.rules = [PageRule.from_dict(d) for d in json.loads(z.read("rules.json"))]
            for name in z.namelist():
                if name.startswith("assets/") and not name.endswith("/"):
                    doc.assets[name.split("/", 1)[1]] = z.read(name)
        return doc
