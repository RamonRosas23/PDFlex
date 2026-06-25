import pytest


def _touch_pdf(path):
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(path)


class _Harness:
    from shell.shell_window import ShellWindow

    _apply_transfer_tray_policy = ShellWindow._apply_transfer_tray_policy
    _clear_widget_inputs = ShellWindow._clear_widget_inputs
    _deliver_tool_inputs = ShellWindow._deliver_tool_inputs

    def __init__(self, tray):
        self._tray = tray


class _LegacyWidget:
    def __init__(self):
        self.clear_count = 0
        self.inputs = []

    def clear_inputs(self):
        self.clear_count += 1

    def set_inputs(self, paths):
        self.inputs.append(list(paths))


class _TransferAwareWidget:
    def __init__(self):
        self.transfer = None
        self.inputs = []

    def set_transfer(self, transfer):
        self.transfer = transfer

    def set_inputs(self, paths):
        self.inputs.append(list(paths))


def test_tool_transfer_validates_modes_and_policies():
    from shell.transfer import ToolTransfer

    assert ToolTransfer(["a.pdf"]).mode == "replace"
    assert ToolTransfer(["a.pdf"]).tray_policy == "keep"

    with pytest.raises(ValueError):
        ToolTransfer(["a.pdf"], mode="merge")

    with pytest.raises(ValueError):
        ToolTransfer(["a.pdf"], tray_policy="delete")


def test_shell_window_delivers_legacy_lists_without_transfer_policy(tmp_path):
    from shell.tray import PdfTray

    harness = _Harness(PdfTray())
    widget = _LegacyWidget()
    pdf = _touch_pdf(tmp_path / "a.pdf")

    harness._deliver_tool_inputs(widget, [pdf])

    assert widget.clear_count == 0
    assert widget.inputs == [[pdf]]


def test_shell_window_transfer_replace_clears_legacy_inputs_and_keeps_tray(tmp_path):
    from shell.tray import PdfTray
    from shell.transfer import ToolTransfer

    tray = PdfTray()
    pdf = _touch_pdf(tmp_path / "a.pdf")
    tray.add_items([pdf], "Compresor")
    harness = _Harness(tray)
    widget = _LegacyWidget()

    harness._deliver_tool_inputs(
        widget,
        ToolTransfer(
            [pdf],
            source_tool_id="compresor",
            source_tool_title="Compresor",
            mode="replace",
            tray_policy="keep",
        ),
    )

    assert widget.clear_count == 1
    assert widget.inputs == [[pdf]]
    assert tray.paths() == [pdf]
    assert tray.items[0].status == "sent"


def test_shell_window_transfer_append_does_not_clear_legacy_inputs(tmp_path):
    from shell.tray import PdfTray
    from shell.transfer import ToolTransfer

    tray = PdfTray()
    pdf = _touch_pdf(tmp_path / "a.pdf")
    harness = _Harness(tray)
    widget = _LegacyWidget()

    harness._deliver_tool_inputs(widget, ToolTransfer([pdf], mode="append"))

    assert widget.clear_count == 0
    assert widget.inputs == [[pdf]]


def test_shell_window_transfer_aware_widget_receives_full_contract(tmp_path):
    from shell.tray import PdfTray
    from shell.transfer import ToolTransfer

    tray = PdfTray()
    pdf = _touch_pdf(tmp_path / "a.pdf")
    harness = _Harness(tray)
    widget = _TransferAwareWidget()
    transfer = ToolTransfer(
        [pdf],
        source_tool_id="firmador",
        source_tool_title="Firmador masivo",
        mode="append",
        tray_policy="keep",
    )

    harness._deliver_tool_inputs(widget, transfer)

    assert widget.transfer is transfer
    assert widget.inputs == []


def test_shell_window_transfer_policy_replace_with_sent(tmp_path):
    from shell.tray import PdfTray
    from shell.transfer import ToolTransfer

    tray = PdfTray()
    old_pdf = _touch_pdf(tmp_path / "old.pdf")
    sent_pdf = _touch_pdf(tmp_path / "sent.pdf")
    tray.add_items([old_pdf], "Compresor")
    harness = _Harness(tray)

    harness._apply_transfer_tray_policy(
        ToolTransfer(
            [sent_pdf],
            source_tool_id="firmador",
            source_tool_title="Firmador masivo",
            tray_policy="replace_with_sent",
            batch_id="batch-sent",
            parent_ids=["original-1"],
        )
    )

    assert tray.paths() == [sent_pdf]
    assert tray.items[0].status == "sent"
    assert tray.items[0].batch_id == "batch-sent"
    assert tray.items[0].source_tool_id == "firmador"
    assert tray.items[0].parent_ids == ["original-1"]


def test_shell_window_transfer_policy_clear(tmp_path):
    from shell.tray import PdfTray
    from shell.transfer import ToolTransfer

    tray = PdfTray()
    old_pdf = _touch_pdf(tmp_path / "old.pdf")
    sent_pdf = _touch_pdf(tmp_path / "sent.pdf")
    tray.add_items([old_pdf, sent_pdf], "Compresor")
    harness = _Harness(tray)

    harness._apply_transfer_tray_policy(
        ToolTransfer([sent_pdf], tray_policy="clear")
    )

    assert tray.paths() == []
