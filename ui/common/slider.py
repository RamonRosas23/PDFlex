"""SliderWithValue — slider + spinbox sincronizados horizontalmente."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QDoubleSpinBox


class SliderWithValue(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        value: float,
        step: float = 0.1,
        suffix: str = "",
        decimals: int = 1,
    ):
        super().__init__()
        self._min = minimum
        self._max = maximum
        self._step = step

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(round(minimum / step)))
        self.slider.setMaximum(int(round(maximum / step)))
        self.slider.setValue(int(round(value / step)))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.setMinimumHeight(28)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setValue(value)
        if suffix:
            self.spin.setSuffix(f" {suffix}")
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin.setFixedWidth(150 if suffix else 112)
        self.spin.valueChanged.connect(self._on_spin)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

    def _on_slider(self, v: int) -> None:
        val = v * self._step
        self.spin.blockSignals(True)
        self.spin.setValue(val)
        self.spin.blockSignals(False)
        self.valueChanged.emit(val)

    def _on_spin(self, v: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v / self._step)))
        self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v: float) -> None:
        """Actualiza el valor programáticamente (emite valueChanged)."""
        self.spin.setValue(max(self._min, min(self._max, v)))
