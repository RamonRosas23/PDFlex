from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import fitz

from core.membrete_library import (
    add_letterhead_to_library,
    load_letterhead_library,
    remove_letterhead_from_library,
)


class MembreteLibraryTests(unittest.TestCase):
    def test_add_load_and_remove_letterhead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_pdf(root / "Membrete Oficial.pdf")
            library_root = root / "library"

            entry = add_letterhead_to_library(source, root=library_root)
            loaded = load_letterhead_library(library_root)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, entry.id)
            self.assertEqual(loaded[0].label, "Membrete Oficial")
            self.assertEqual(loaded[0].page_count, 1)
            self.assertTrue(Path(loaded[0].path).exists())
            self.assertNotEqual(Path(loaded[0].path), source)

            self.assertTrue(remove_letterhead_from_library(entry.id, library_root))
            self.assertEqual(load_letterhead_library(library_root), [])

    @staticmethod
    def _make_pdf(path: Path) -> Path:
        doc = fitz.open()
        page = doc.new_page(width=300, height=420)
        page.insert_text((36, 36), "Membrete")
        doc.save(path)
        doc.close()
        return path


if __name__ == "__main__":
    unittest.main()
