"""UI controls for page-aware PDF compression rules."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.pdf_page_rules import (
    PAGE_RULE_PRESETS,
    PageCompressionRule,
    build_page_compression_plan,
    compact_page_indexes,
    parse_page_spec,
)
from ui.common.icons import set_button_icon


_PRESET_ORDER = ("exclude", "quality", "balanced", "email", "custom")


class PageRulesPanel(QFrame):
    """Compact rule editor and page map for the compressor profile step."""

    rulesChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "Card")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._rules: list[PageCompressionRule] = []
        self._page_count = 0
        self._doc_label = ""
        self._global_profile_id = "balanced"
        self._editing_id = ""
        self._updating = False
        self._build()
        self._refresh()

    def rules(self) -> list[PageCompressionRule]:
        return list(self._rules)

    def has_rules(self) -> bool:
        return bool(self._rules)

    def clear_rules(self) -> None:
        self._rules = []
        self._editing_id = ""
        self._clear_editor()
        self._refresh(emit=True)

    def set_page_context(self, page_count: int, label: str = "") -> None:
        self._page_count = max(0, int(page_count or 0))
        self._doc_label = label
        self._refresh()

    def set_global_profile(self, profile_id: str) -> None:
        self._global_profile_id = profile_id or "balanced"
        self._refresh()

    def summary_text(self) -> str:
        if not self._rules:
            return "Sin reglas por pagina"
        if self._page_count <= 0:
            count = len(self._rules)
            return f"{count} regla" + ("" if count == 1 else "s")
        try:
            plan = build_page_compression_plan(
                self._page_count,
                self._global_profile_id,
                self._rules,
            )
            return plan.summary
        except ValueError as exc:
            return f"Revisar reglas: {exc}"

    def validation_error(self) -> str:
        if not self._rules:
            return ""
        custom_error = _custom_rules_error(self._rules)
        if custom_error:
            return custom_error
        if self._page_count <= 0:
            return ""
        try:
            build_page_compression_plan(
                self._page_count,
                self._global_profile_id,
                self._rules,
            )
        except ValueError as exc:
            return str(exc)
        return ""

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Reglas por paginas")
        title.setProperty("class", "CardTitle")
        root.addWidget(title)

        hint = QLabel("Define paginas protegidas o perfiles distintos por intervalo.")
        hint.setProperty("class", "CardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        editor = QGridLayout()
        editor.setHorizontalSpacing(10)
        editor.setVerticalSpacing(8)
        editor.setColumnStretch(0, 3)
        editor.setColumnStretch(1, 2)

        self._pages_edit = QLineEdit()
        self._pages_edit.setPlaceholderText("1-3, 7, 10-fin")
        self._pages_edit.setClearButtonEnabled(True)
        editor.addWidget(_field_label("Paginas"), 0, 0)
        editor.addWidget(self._pages_edit, 1, 0)

        self._preset_combo = QComboBox()
        for preset_id in _PRESET_ORDER:
            preset = PAGE_RULE_PRESETS[preset_id]
            self._preset_combo.addItem(preset.label, preset_id)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        editor.addWidget(_field_label("Preset"), 0, 1)
        editor.addWidget(self._preset_combo, 1, 1)

        self._save_btn = QPushButton("Agregar")
        self._save_btn.setProperty("class", "Primary")
        self._save_btn.setFixedHeight(34)
        self._save_btn.setMinimumWidth(118)
        set_button_icon(self._save_btn, "plus")
        self._save_btn.clicked.connect(self._save_rule)

        self._cancel_edit_btn = QPushButton()
        self._cancel_edit_btn.setProperty("class", "IconBtn")
        self._cancel_edit_btn.setFixedSize(34, 34)
        self._cancel_edit_btn.setToolTip("Cancelar edicion")
        set_button_icon(self._cancel_edit_btn, "x", size=14, icon_only=True)
        self._cancel_edit_btn.clicked.connect(self._cancel_edit)
        root.addLayout(editor)

        editor_actions = QHBoxLayout()
        editor_actions.setContentsMargins(0, 0, 0, 0)
        editor_actions.setSpacing(8)
        editor_actions.addStretch(1)
        editor_actions.addWidget(self._save_btn)
        editor_actions.addWidget(self._cancel_edit_btn)
        root.addLayout(editor_actions)

        self._custom_box = QWidget()
        custom = QGridLayout(self._custom_box)
        custom.setContentsMargins(0, 0, 0, 0)
        custom.setHorizontalSpacing(10)
        custom.setVerticalSpacing(8)
        custom.setColumnStretch(0, 1)
        custom.setColumnStretch(1, 1)
        custom.setColumnStretch(2, 1)
        self._dpi_target_spin = _make_spin(50, 600, " DPI")
        self._dpi_threshold_spin = _make_spin(72, 900, " DPI")
        self._quality_spin = _make_spin(35, 100, "%")
        self._quality_spin.setValue(76)
        self._gray_check = QCheckBox("Grises")
        self._validation_combo = QComboBox()
        self._validation_combo.addItem("Normal", "standard")
        self._validation_combo.addItem("Estricta", "strict")
        self._validation_combo.addItem("Flexible", "relaxed")
        self._validation_combo.setMinimumWidth(128)
        for col, (label, widget) in enumerate((
            ("DPI", self._dpi_target_spin),
            ("Sobre", self._dpi_threshold_spin),
            ("JPEG", self._quality_spin),
        )):
            custom.addWidget(_field_label(label), 0, col)
            custom.addWidget(widget, 1, col)
        custom.addWidget(_field_label("Validacion"), 2, 0)
        custom.addWidget(self._validation_combo, 3, 0, 1, 2)
        custom.addWidget(self._gray_check, 3, 2)
        root.addWidget(self._custom_box)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._remove_btn = QPushButton("Eliminar")
        self._remove_btn.setProperty("class", "Ghost")
        self._remove_btn.setFixedHeight(30)
        set_button_icon(self._remove_btn, "trash-2", size=14)
        self._remove_btn.clicked.connect(self._remove_selected)
        actions.addWidget(self._remove_btn)

        self._clear_btn = QPushButton("Limpiar")
        self._clear_btn.setProperty("class", "Ghost")
        self._clear_btn.setFixedHeight(30)
        set_button_icon(self._clear_btn, "eraser", size=14)
        self._clear_btn.clicked.connect(self.clear_rules)
        actions.addWidget(self._clear_btn)
        actions.addStretch(1)
        self._count_lbl = QLabel("")
        self._count_lbl.setProperty("class", "CardHint")
        actions.addWidget(self._count_lbl)
        root.addLayout(actions)

        self._rules_list = QListWidget()
        self._rules_list.setMinimumHeight(96)
        self._rules_list.setMaximumHeight(148)
        self._rules_list.setSpacing(4)
        self._rules_list.currentItemChanged.connect(self._on_rule_selected)
        root.addWidget(self._rules_list)

        self._status_lbl = QLabel("")
        self._status_lbl.setProperty("class", "CardHint")
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)

        self._map_scroll = QScrollArea()
        self._map_scroll.setWidgetResizable(True)
        self._map_scroll.setMinimumHeight(82)
        self._map_scroll.setMaximumHeight(150)
        self._map_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._map_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._map_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._map_host = QWidget()
        self._map_grid = QGridLayout(self._map_host)
        self._map_grid.setContentsMargins(0, 0, 0, 0)
        self._map_grid.setSpacing(4)
        self._map_scroll.setWidget(self._map_host)
        root.addWidget(self._map_scroll)

        self._clear_editor()

    def _on_preset_changed(self) -> None:
        preset = str(self._preset_combo.currentData() or "balanced")
        self._custom_box.setVisible(preset == "custom")

    def _save_rule(self) -> None:
        page_spec = self._pages_edit.text().strip()
        preset = str(self._preset_combo.currentData() or "balanced")
        rule = PageCompressionRule(
            page_spec=page_spec,
            preset=preset,
            id=self._editing_id or "",
            options=self._custom_options() if preset == "custom" else {},
        )
        if not rule.id:
            rule = PageCompressionRule(
                page_spec=rule.page_spec,
                preset=rule.preset,
                options=rule.options,
            )
        next_rules = [
            existing for existing in self._rules
            if existing.id != self._editing_id
        ]
        next_rules.append(rule)
        error = self._validate_rules(next_rules)
        if error:
            self._show_error(error)
            return
        self._rules = next_rules
        self._editing_id = ""
        self._clear_editor()
        self._refresh(emit=True)

    def _cancel_edit(self) -> None:
        self._editing_id = ""
        self._clear_editor()
        self._refresh()

    def _remove_selected(self) -> None:
        item = self._rules_list.currentItem()
        if item is None:
            return
        rule_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._rules = [rule for rule in self._rules if rule.id != rule_id]
        if self._editing_id == rule_id:
            self._editing_id = ""
            self._clear_editor()
        self._refresh(emit=True)

    def _on_rule_selected(self, item: QListWidgetItem | None, _previous=None) -> None:
        if self._updating or item is None:
            return
        rule_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        rule = next((candidate for candidate in self._rules if candidate.id == rule_id), None)
        if rule is None:
            return
        self._editing_id = rule.id
        self._pages_edit.setText(rule.page_spec)
        idx = self._preset_combo.findData(rule.normalized_preset())
        self._preset_combo.setCurrentIndex(max(0, idx))
        if rule.normalized_preset() == "custom":
            self._apply_custom_options(rule.options)
        self._save_btn.setText("Guardar")
        self._save_btn.setToolTip("Guardar cambios de la regla seleccionada")
        self._cancel_edit_btn.setVisible(True)

    def _clear_editor(self) -> None:
        self._pages_edit.clear()
        idx = self._preset_combo.findData("exclude")
        self._preset_combo.setCurrentIndex(max(0, idx))
        self._dpi_target_spin.setValue(150)
        self._dpi_threshold_spin.setValue(180)
        self._quality_spin.setValue(76)
        self._gray_check.setChecked(False)
        validation_idx = self._validation_combo.findData("standard")
        self._validation_combo.setCurrentIndex(max(0, validation_idx))
        self._save_btn.setText("Agregar")
        self._cancel_edit_btn.setVisible(False)
        self._on_preset_changed()

    def _refresh(self, *, emit: bool = False) -> None:
        self._updating = True
        try:
            self._rules_list.clear()
            for rule in self._rules:
                item = QListWidgetItem(self._rule_item_text(rule))
                item.setData(Qt.ItemDataRole.UserRole, rule.id)
                item.setToolTip(self._rule_tooltip(rule))
                item.setSizeHint(QSize(220, 44))
                self._rules_list.addItem(item)
            self._remove_btn.setEnabled(bool(self._rules))
            self._clear_btn.setEnabled(bool(self._rules))
            count = len(self._rules)
            self._count_lbl.setText(f"{count} regla" + ("" if count == 1 else "s"))
            self._refresh_status()
            self._refresh_map()
        finally:
            self._updating = False
        if emit:
            self.rulesChanged.emit()

    def _refresh_status(self) -> None:
        if not self._rules:
            self._status_lbl.setText("Sin reglas: todas las paginas usan el perfil global.")
            self._status_lbl.setStyleSheet("color:#9094A0;")
            return
        if self._page_count <= 0:
            self._status_lbl.setText("Reglas listas; se validaran al cargar o procesar PDFs.")
            self._status_lbl.setStyleSheet("color:#9094A0;")
            return
        error = self.validation_error()
        if error:
            self._show_error(error)
            return
        plan = build_page_compression_plan(
            self._page_count,
            self._global_profile_id,
            self._rules,
        )
        doc = f" · {Path(self._doc_label).name}" if self._doc_label else ""
        self._status_lbl.setText(f"{plan.summary}{doc}")
        self._status_lbl.setStyleSheet("color:#3BD37C;")

    def _refresh_map(self) -> None:
        while self._map_grid.count():
            item = self._map_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self._page_count <= 0:
            label = QLabel("Mapa disponible al cargar un PDF")
            label.setProperty("class", "CardHint")
            self._map_grid.addWidget(label, 0, 0)
            return
        try:
            plan = build_page_compression_plan(
                self._page_count,
                self._global_profile_id,
                self._rules,
            )
        except ValueError:
            return
        columns = 12
        max_tiles = min(self._page_count, 240)
        for index in range(max_tiles):
            effective = plan.rule_for_page(index)
            tile = QLabel(str(index + 1))
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setFixedSize(34, 26)
            tile.setToolTip(f"Pagina {index + 1}: {effective.label}")
            tile.setStyleSheet(
                "QLabel {"
                f"background: {effective.color};"
                "color: #050507;"
                "border: 1px solid rgba(255,255,255,0.20);"
                "border-radius: 5px;"
                "font-size: 10px;"
                "font-weight: 700;"
                "}"
            )
            self._map_grid.addWidget(tile, index // columns, index % columns)
        if self._page_count > max_tiles:
            more = QLabel(f"+{self._page_count - max_tiles} paginas")
            more.setProperty("class", "CardHint")
            more.setWordWrap(True)
            self._map_grid.addWidget(more, (max_tiles // columns) + 1, 0, 1, columns)

    def _validate_rules(self, rules: list[PageCompressionRule]) -> str:
        if self._page_count <= 0:
            if not rules[-1].page_spec.strip():
                return "Escribe un rango de paginas."
            custom_error = _custom_rules_error(rules)
            if custom_error:
                return custom_error
            return ""
        custom_error = _custom_rules_error(rules)
        if custom_error:
            return custom_error
        try:
            build_page_compression_plan(
                self._page_count,
                self._global_profile_id,
                rules,
            )
        except ValueError as exc:
            return str(exc)
        return ""

    def _show_error(self, message: str) -> None:
        self._status_lbl.setText(message)
        self._status_lbl.setStyleSheet("color:#E5484D;")

    def _rule_item_text(self, rule: PageCompressionRule) -> str:
        preset = PAGE_RULE_PRESETS[rule.normalized_preset()]
        suffix = ""
        if self._page_count > 0:
            try:
                pages = compact_page_indexes(parse_page_spec(rule.page_spec, self._page_count))
                suffix = f" · {pages}"
            except Exception:
                suffix = " · revisar"
        return f"{rule.page_spec} · {preset.label}{suffix}"

    def _rule_tooltip(self, rule: PageCompressionRule) -> str:
        preset = PAGE_RULE_PRESETS[rule.normalized_preset()]
        if rule.normalized_preset() != "custom":
            return preset.description
        options = rule.options
        return (
            f"DPI {options.get('dpi_target', 150)} · "
            f"JPEG {options.get('quality', 76)}% · "
            f"{options.get('validation_level', 'standard')}"
        )

    def _custom_options(self) -> dict:
        return {
            "dpi_target": int(self._dpi_target_spin.value()),
            "dpi_threshold": int(self._dpi_threshold_spin.value()),
            "quality": int(self._quality_spin.value()),
            "set_to_gray": self._gray_check.isChecked(),
            "validation_level": str(self._validation_combo.currentData() or "standard"),
        }

    def _apply_custom_options(self, options: dict) -> None:
        self._dpi_target_spin.setValue(int(options.get("dpi_target") or 150))
        self._dpi_threshold_spin.setValue(int(options.get("dpi_threshold") or 180))
        self._quality_spin.setValue(int(options.get("quality") or 76))
        self._gray_check.setChecked(bool(options.get("set_to_gray")))
        idx = self._validation_combo.findData(options.get("validation_level") or "standard")
        self._validation_combo.setCurrentIndex(max(0, idx))


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "CardHint")
    return label


def _make_spin(minimum: int, maximum: int, suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setFixedHeight(32)
    spin.setMinimumWidth(92)
    spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return spin


def _custom_rules_error(rules: list[PageCompressionRule]) -> str:
    for rule in rules:
        try:
            if rule.normalized_preset() != "custom":
                continue
        except ValueError as exc:
            return str(exc)
        options = rule.options
        dpi_target = int(options.get("dpi_target") or 0)
        dpi_threshold = int(options.get("dpi_threshold") or 0)
        if dpi_target >= dpi_threshold:
            page_text = rule.page_spec.strip() or "la regla"
            return (
                f"En {page_text}, el DPI objetivo debe ser menor "
                "que el umbral de procesamiento."
            )
    return ""
