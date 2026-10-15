"""Компактное окно регулировки интенсивности около системного трея"""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from config import SLIDER_DEBOUNCE_MS


def popup_position(tray_rect, available, size, anchor):
    """Выбирает сторону панели задач и ограничивает координаты рабочей областью"""
    width, height = size.width(), size.height()
    x = anchor.x() - width // 2
    y = anchor.y() - height - 8
    if tray_rect.isValid() and anchor.x() < available.left():
        x, y = available.left() + 8, anchor.y() - height // 2
    elif tray_rect.isValid() and anchor.x() > available.right():
        x, y = available.right() - width - 7, anchor.y() - height // 2
    elif anchor.y() < available.center().y():
        y = (tray_rect.bottom() if tray_rect.isValid() else anchor.y()) + 8
    inset_x = min(8, max(0, (available.width() - width) // 2))
    inset_y = min(8, max(0, (available.height() - height) // 2))
    x = max(available.left() + inset_x, min(x, available.right() + 1 - width - inset_x))
    y = max(available.top() + inset_y, min(y, available.bottom() + 1 - height - inset_y))
    return QPoint(x, y)


class StrengthSlider(QSlider):
    """Ползунок с шагом колёсика 2%, независимым от настроек прокрутки Windows"""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._wheel_delta = 0

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        self._wheel_delta += delta
        steps = int(self._wheel_delta / 120)
        self._wheel_delta -= steps * 120
        if steps:
            self.setValue(self.value() + steps * 2)
        event.accept()

    def hideEvent(self, event):
        self._wheel_delta = 0
        super().hideEvent(event)


class NightLightIndicator(QWidget):
    """Луна/солнце показывают состояние, но не переключают ночной свет"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.color = self.palette().color(QPalette.ColorRole.WindowText)
        self.set_state(None)

    def set_state(self, active):
        self.active = active
        if active is None:
            description = "Состояние ночного света неизвестно"
        elif active:
            description = "Ночной свет включён"
        else:
            description = "Ночной свет выключен. Интенсивность сохранится для следующего включения."
        self.setToolTip(description)
        self.setAccessibleName(description)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 24, self.height() / 24)
        pen = QPen(
            self.color,
            1.8,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        if self.active is True:
            moon = QPainterPath(QPointF(10.5, 2.5))
            moon.cubicTo(2, 4, 0.5, 15, 7.5, 19.5)
            moon.cubicTo(12, 22.5, 18.5, 21, 21, 16)
            moon.cubicTo(12, 18, 7, 10, 10.5, 2.5)
            painter.drawPath(moon)
        elif self.active is False:
            painter.drawEllipse(QRectF(8, 8, 8, 8))
            for x1, y1, x2, y2 in (
                (12, 2, 12, 5),
                (12, 19, 12, 22),
                (2, 12, 5, 12),
                (19, 12, 22, 12),
                (5, 5, 7, 7),
                (17, 17, 19, 19),
                (5, 19, 7, 17),
                (17, 7, 19, 5),
            ):
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        else:
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawEllipse(QRectF(5, 5, 14, 14))
        painter.end()


class NightLightPopup(QWidget):
    """Всплывающее окно без отдельной кнопки на панели задач"""

    def __init__(self, client, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.client = client
        self._generation = 0
        self._changing = False
        self._last_error = None
        self._confirmed_generation = None
        self._has_value = False
        self._tray_rect = QRect()
        self._anchor = None
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedWidth(300)
        self._build_ui()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SLIDER_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._send_slider_value)
        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.setInterval(100)
        self._dismiss.timeout.connect(self._hide_if_inactive)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self._apply_theme)
        client.status_ready.connect(self._on_status_ready)
        client.operation_error.connect(self._on_error)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 22)
        layout.setSpacing(13)
        header = QHBoxLayout()
        header.setSpacing(9)
        self.indicator = NightLightIndicator(self)
        title = QLabel("Ночной свет")
        title.setObjectName("title")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("value")
        header.addWidget(self.indicator)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.value_label)
        layout.addLayout(header)
        self.slider = StrengthSlider(self)
        self.slider.setRange(0, 100)
        self.slider.setMinimumHeight(26)
        self.slider.setAccessibleName("Интенсивность ночного света")
        self.slider.setSingleStep(1)
        self.slider.setPageStep(10)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)
        self.status = QLabel("Чтение системной настройки…")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        self.retry = QPushButton("Повторить чтение")
        self.retry.clicked.connect(self.refresh)
        self.retry.hide()
        layout.addWidget(self.retry)

    def open_near(self, tray_rect):
        """Показывает окно над/рядом с треем, не выходя за рабочую область экрана"""
        self._apply_theme()
        self._dismiss.stop()
        self._tray_rect = QRect(tray_rect)
        self._anchor = tray_rect.center() if tray_rect.isValid() else QCursor.pos()
        self.refresh()
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self.activateWindow()

    def _reposition(self):
        if self._anchor is None:
            return
        screen = QApplication.screenAt(self._anchor) or self.screen()
        available = screen.availableGeometry()
        self.move(popup_position(self._tray_rect, available, self.size(), self._anchor))

    def refresh(self):
        if self._debounce.isActive():
            self._debounce.stop()
            self._send_slider_value()
        self._generation += 1
        self._changing = False
        self._last_error = None
        self.slider.setEnabled(False)
        self.retry.hide()
        self.indicator.set_state(None)
        self.value_label.setText("…")
        self.value_label.setToolTip("Ожидается чтение фактического значения Windows.")
        self.status.setText("Чтение системной настройки…")
        self.status.hide()
        self.adjustSize()
        self._reposition()
        self.client.read_strength(self._generation)

    def _on_slider_changed(self, value):
        self.value_label.setText("{}%".format(value))
        if self._changing:
            return
        self._has_value = True
        self._generation += 1
        self._last_error = None
        self.retry.hide()
        self.value_label.setToolTip("Выбранное значение; ожидается подтверждение Windows.")
        self.status.setText("Применение…")
        self.status.hide()
        self.adjustSize()
        self._reposition()
        self._debounce.start()

    def _send_slider_value(self):
        self.client.set_strength(self.slider.value(), self._generation)

    def _on_status_ready(self, generation, value, active):
        # Ответы на старые чтения не имеют права двигать ползунок пользователя
        if generation < self._generation:
            return
        self._generation = generation
        self._confirmed_generation = generation
        self._has_value = True
        self._changing = True
        blocker = QSignalBlocker(self.slider)
        self.slider.setValue(value)
        del blocker
        self._changing = False
        self.slider.setEnabled(True)
        self.retry.hide()
        self.value_label.setText("{}%".format(value))
        self.value_label.setToolTip("Фактическая интенсивность Windows.")
        self.indicator.set_state(active)
        if self._last_error and self._last_error[0] == generation:
            self.status.setText(self._last_error[1])
            self.status.show()
        else:
            self.status.clear()
            self.status.hide()
        self.adjustSize()
        self._reposition()

    def _on_error(self, generation, message):
        if generation < self._generation:
            return
        self._last_error = (generation, message)
        if self._confirmed_generation == generation:
            # Например, Windows подтвердила другой процент: он уже показан и достоверен
            self.status.setText(message)
        else:
            self.slider.setEnabled(False)
            self.value_label.setText(
                "{}% ?".format(self.slider.value()) if self._has_value else "—"
            )
            self.value_label.setToolTip(
                "Последнее известное или выбранное значение. Значение Windows не подтверждено."
            )
            self.indicator.set_state(None)
            self.status.setText("Значение не подтверждено.\n" + message)
            self.retry.show()
        self.status.show()
        self.adjustSize()
        self._reposition()

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            # Даём событию клика по трею закрыть окно до автоматического скрытия
            self._dismiss.start()
        return super().event(event)

    def _hide_if_inactive(self):
        if not self.isActiveWindow():
            self.hide()

    def hideEvent(self, event):
        self._dismiss.stop()
        self.flush_changes()
        super().hideEvent(event)

    def flush_changes(self):
        """Передаёт последнее движение ползунка немедленно, не ожидая debounce"""
        if self._debounce.isActive():
            self._debounce.stop()
            self._send_slider_value()

    def stop(self):
        """Отменяет отложенные действия при завершении приложения"""
        self._debounce.stop()
        self._dismiss.stop()
        self.hide()

    def _apply_theme(self, _scheme=None):
        app = QApplication.instance()
        scheme = app.styleHints().colorScheme()
        dark = scheme == Qt.ColorScheme.Dark or (
            scheme == Qt.ColorScheme.Unknown
            and app.palette().color(QPalette.ColorRole.Window).lightness() < 128
        )
        background = "#202020" if dark else "#f7f7f7"
        text = "#f4f4f4" if dark else "#202020"
        muted = "#b8b8b8" if dark else "#666666"
        groove = "#101010" if dark else "#e2e2e2"
        self.indicator.color = QColor(text)
        self.indicator.update()
        self.setStyleSheet(
            """
            NightLightPopup { background: %s; border: 1px solid %s; border-radius: 12px; }
            QLabel { color: %s; font-family: 'Segoe UI'; }
            QLabel#title { font-size: 15px; font-weight: 600; }
            QLabel#value { font-size: 15px; font-weight: 600; }
            QLabel#status { color: %s; font-size: 11px; }
            QPushButton { color: %s; background: %s; border: 1px solid #858585;
                          border-radius: 5px; padding: 5px; font-family: 'Segoe UI'; }
            QSlider::groove:horizontal { height: 20px; background: %s; border-radius: 10px; }
            QSlider::sub-page:horizontal { background: %s; border-radius: 10px; }
            QSlider::handle:horizontal { background: #ffffff; width: 18px; margin: 0; border-radius: 10px; border: 1px solid #858585; }
        """
            % (
                background,
                "#3a3a3a" if dark else "#d6d6d6",
                text,
                muted,
                text,
                "#333333" if dark else "#ffffff",
                groove,
                groove,
            )
        )
