from datetime import datetime


def _touch_pdf(path):
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(path)


def test_pdf_tray_add_items_stores_enriched_metadata(tmp_path):
    from shell.tray import PdfTray

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")

    tray.add_items(
        [first, second],
        "Firmador",
        kind="output",
        source_tool_id="firmador",
        source_tool_title="Firmador masivo",
        parent_ids=["original-1"],
    )

    items = tray.items
    assert tray.paths() == [first, second]
    assert len({item.id for item in items}) == 2
    assert len({item.batch_id for item in items}) == 1
    assert [item.kind for item in items] == ["output", "output"]
    assert [item.status for item in items] == ["available", "available"]
    assert [item.source_tool for item in items] == ["Firmador", "Firmador"]
    assert [item.source_tool_id for item in items] == ["firmador", "firmador"]
    assert [item.source_tool_title for item in items] == [
        "Firmador masivo",
        "Firmador masivo",
    ]
    assert [item.parent_ids for item in items] == [["original-1"], ["original-1"]]


def test_pdf_tray_replace_with_keeps_legacy_paths_contract(tmp_path):
    from shell.tray import PdfTray

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    missing = str(tmp_path / "missing.pdf")
    emissions = []
    tray.changed.connect(lambda: emissions.append(tray.paths()))

    tray.add_items([first], "Compresor")
    tray.replace_with(
        [second, first, second, missing],
        "Membretado",
        kind="output",
        source_tool_id="membretado",
        batch_id="batch-membretado",
    )

    assert tray.paths() == [second, first]
    assert [item.batch_id for item in tray.items] == [
        "batch-membretado",
        "batch-membretado",
    ]
    assert [item.source_tool_id for item in tray.items] == [
        "membretado",
        "membretado",
    ]
    assert emissions == [[first], [second, first]]


def test_pdf_tray_marks_work_sent_and_missing_statuses(tmp_path):
    from shell.tray import PdfTray

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    tray.add_items([first, second], "Compresor")

    first_before = tray.items[0].last_used_at
    tray.mark_in_work([first])
    assert tray.items[0].status == "in_work"
    assert tray.items[0].last_used_at >= first_before
    assert tray.items[1].status == "available"

    sent_before = tray.items[0].last_used_at
    tray.mark_sent([first])
    assert tray.items[0].status == "sent"
    assert tray.items[0].last_used_at >= sent_before

    (tmp_path / "second.pdf").unlink()
    tray.refresh_missing()
    assert tray.items[0].status == "sent"
    assert tray.items[1].status == "missing"


def test_pdf_tray_items_by_group_preserves_insertion_order(tmp_path):
    from shell.tray import PdfTray

    tray = PdfTray()
    first = _touch_pdf(tmp_path / "first.pdf")
    second = _touch_pdf(tmp_path / "second.pdf")
    third = _touch_pdf(tmp_path / "third.pdf")

    tray.add_items([first, second], "Compresor", batch_id="batch-a")
    tray.add_items([third], "Firmador", batch_id="batch-b")

    groups = tray.items_by_group()
    assert list(groups) == ["batch-a", "batch-b"]
    assert [item.path for item in groups["batch-a"]] == [first, second]
    assert [item.path for item in groups["batch-b"]] == [third]
    assert all(isinstance(item.created_at, datetime) for item in tray.items)


def test_pdf_tray_supports_source_summaries_and_mass_cleanup(tmp_path):
    from shell.tray import PdfTray

    tray = PdfTray()
    output = _touch_pdf(tmp_path / "output.pdf")
    converted = _touch_pdf(tmp_path / "converted.pdf")
    original = _touch_pdf(tmp_path / "original.pdf")
    manual = _touch_pdf(tmp_path / "manual.pdf")
    missing = _touch_pdf(tmp_path / "missing.pdf")
    tray.add_items([output], "Compresor", kind="output")
    tray.add_items([converted], "Word a PDF", kind="converted")
    tray.add_items([original], "Importado", kind="original")
    tray.add_items([manual], "Usuario", kind="manual")
    tray.add_items([missing], "Importado", kind="original")
    (tmp_path / "missing.pdf").unlink()

    assert tray.source_counts() == {
        "Compresor": 1,
        "Word a PDF": 1,
        "Importado": 2,
        "Usuario": 1,
    }

    tray.clear_results()
    assert tray.paths() == [original, manual, missing]
    tray.remove_missing()
    assert tray.paths() == [original, manual]
    tray.clear_originals()
    assert tray.paths() == []
