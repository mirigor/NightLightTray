"""Проверка ползунка и защиты от запоздавшего чтения"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from popup import NightLightPopup, StrengthSlider, popup_position


class FakeClient(QObject):
    """Клиент без вызовов Night Light"""

    status_ready = Signal(int, int, bool)
    operation_error = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.reads = []
        self.writes = []

    def read_strength(self, generation):
        self.reads.append(generation)

    def set_strength(self, value, generation):
        self.writes.append((value, generation))


class PopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def send_wheel(self, slider, delta, modifiers=Qt.KeyboardModifier.NoModifier):
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(slider, event)

    def test_wheel_step_is_two_regardless_of_system_scroll_lines(self):
        slider = StrengthSlider()
        slider.setRange(0, 100)
        slider.setValue(50)
        hints = self.app.styleHints()
        original = hints.wheelScrollLines()
        try:
            for lines in (1, 3, 10):
                hints.setWheelScrollLines(lines)
                self.send_wheel(slider, 120)
                self.assertEqual(slider.value(), 52)
                self.send_wheel(slider, -120)
                self.assertEqual(slider.value(), 50)
        finally:
            hints.setWheelScrollLines(original)

    def test_wheel_accumulates_partial_steps_and_clamps_to_range(self):
        slider = StrengthSlider()
        slider.setRange(0, 100)
        slider.setValue(50)
        self.send_wheel(slider, 60)
        self.assertEqual(slider.value(), 50)
        self.send_wheel(slider, 60)
        self.assertEqual(slider.value(), 52)
        self.send_wheel(slider, -240)
        self.assertEqual(slider.value(), 48)
        slider.setValue(99)
        self.send_wheel(slider, 120)
        self.assertEqual(slider.value(), 100)
        slider.setValue(1)
        self.send_wheel(slider, -120)
        self.assertEqual(slider.value(), 0)

    def test_wheel_modifiers_keep_two_percent_and_keyboard_keeps_one(self):
        slider = StrengthSlider()
        slider.setRange(0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(10)
        slider.setValue(50)
        self.send_wheel(slider, 120, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(slider.value(), 52)
        self.send_wheel(slider, -120, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(slider.value(), 50)
        QTest.keyClick(slider, Qt.Key.Key_Right)
        self.assertEqual(slider.value(), 51)

    def test_last_slider_value_wins_over_old_read(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        self.assertEqual(client.reads, [1])
        popup.slider.setValue(20)
        popup.slider.setValue(80)
        client.status_ready.emit(1, 10, False)
        self.assertEqual(popup.slider.value(), 80)
        QTest.qWait(260)
        self.assertEqual(client.writes, [(80, 3)])
        client.status_ready.emit(3, 80, True)
        self.assertEqual(popup.value_label.text(), "80%")

    def test_readback_after_error_keeps_message_and_actual_value(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.operation_error.emit(1, "Ошибка записи")
        client.status_ready.emit(1, 56, True)
        self.assertEqual(popup.slider.value(), 56)
        self.assertEqual(popup.status.text(), "Ошибка записи")

    def test_slider_is_disabled_until_real_read_and_on_read_error(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        self.assertFalse(popup.slider.isEnabled())
        popup.refresh()
        client.status_ready.emit(1, 68, True)
        self.assertTrue(popup.slider.isEnabled())
        popup.refresh()
        client.operation_error.emit(2, "Ошибка чтения")
        self.assertFalse(popup.slider.isEnabled())
        self.assertEqual(popup.slider.value(), 68)

    def test_state_is_shown_without_switching_night_light(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.status_ready.emit(1, 68, False)
        self.assertIs(popup.indicator.active, False)
        self.assertIn("Ночной свет выключен", popup.indicator.toolTip())
        self.assertTrue(popup.slider.isEnabled())
        self.assertEqual(popup.value_label.text(), "68%")
        popup.refresh()
        client.status_ready.emit(2, 68, True)
        self.assertIs(popup.indicator.active, True)
        self.assertEqual(popup.indicator.toolTip(), "Ночной свет включён")
        self.assertTrue(popup.status.isHidden())
        self.assertEqual(client.writes, [])

    def test_indicator_is_not_a_switch_and_normal_popup_stays_compact(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.status_ready.emit(1, 68, True)
        height = popup.height()
        QTest.mouseClick(popup.indicator, Qt.MouseButton.LeftButton)
        self.assertIs(popup.indicator.active, True)
        self.assertEqual(client.writes, [])
        self.assertEqual(popup.indicator.accessibleName(), "Ночной свет включён")
        self.assertTrue(popup.status.isHidden())
        popup.refresh()
        client.status_ready.emit(2, 68, False)
        self.assertEqual(popup.height(), height)
        self.assertTrue(popup.status.isHidden())
        self.assertLessEqual(height, 110)
        self.assertEqual(popup.layout().contentsMargins().bottom(), 22)
        self.assertFalse(
            any(label.text() == "Интенсивность" for label in popup.findChildren(QLabel))
        )

    def test_loading_keeps_size_and_slider_position_until_actual_read(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.open_near(QRect(1800, 1040, 24, 24))
        self.addCleanup(popup.stop)
        size = popup.size()
        position = popup.pos()
        slider_rect = popup.slider.geometry()
        self.assertTrue(popup.status.isHidden())
        self.assertEqual(popup.value_label.text(), "…")
        self.assertFalse(popup.slider.isEnabled())
        client.status_ready.emit(1, 68, True)
        self.assertEqual(popup.size(), size)
        self.assertEqual(popup.pos(), position)
        self.assertEqual(popup.slider.geometry(), slider_rect)
        popup.refresh()
        self.assertEqual(popup.size(), size)
        self.assertEqual(popup.slider.geometry(), slider_rect)
        self.assertEqual(popup.value_label.text(), "…")
        client.status_ready.emit(2, 56, False)
        self.assertEqual(popup.size(), size)
        self.assertEqual(popup.pos(), position)

    def test_error_is_visible_and_retry_returns_to_compact_loading(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.open_near(QRect(1800, 1040, 24, 24))
        self.addCleanup(popup.stop)
        compact = popup.size()
        client.operation_error.emit(1, "Ошибка чтения")
        self.assertFalse(popup.status.isHidden())
        self.assertFalse(popup.retry.isHidden())
        self.assertGreater(popup.height(), compact.height())
        popup.retry.click()
        self.assertTrue(popup.status.isHidden())
        self.assertTrue(popup.retry.isHidden())
        self.assertEqual(popup.size(), compact)
        self.assertEqual(popup.value_label.text(), "…")
        client.status_ready.emit(2, 68, True)
        self.assertEqual(popup.size(), compact)

    def test_failed_verification_is_marked_and_retry_only_reads(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.status_ready.emit(1, 56, True)
        popup.slider.setValue(68)
        popup.flush_changes()
        client.operation_error.emit(2, "Команда не ответила вовремя.")
        self.assertEqual(popup.value_label.text(), "68% ?")
        self.assertIn("Значение не подтверждено", popup.status.text())
        self.assertIn("вовремя", popup.status.text())
        self.assertIsNone(popup.indicator.active)
        self.assertEqual(popup.indicator.toolTip(), "Состояние ночного света неизвестно")
        self.assertFalse(popup.slider.isEnabled())
        self.assertFalse(popup.retry.isHidden())
        popup.retry.click()
        self.assertEqual(client.reads, [1, 3])
        self.assertEqual(client.writes, [(68, 2)])
        self.assertTrue(popup.retry.isHidden())
        client.status_ready.emit(3, 56, False)
        self.assertEqual(popup.value_label.text(), "56%")
        self.assertTrue(popup.slider.isEnabled())
        self.assertNotIn("не подтверждено", popup.status.text())
        self.assertIs(popup.indicator.active, False)

    def test_initial_read_failure_does_not_fabricate_zero_percent(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.operation_error.emit(1, "Ошибка чтения")
        self.assertEqual(popup.value_label.text(), "—")
        self.assertIn("Значение не подтверждено", popup.status.text())
        self.assertFalse(popup.retry.isHidden())

    def test_confirmed_mismatch_keeps_real_percentage_and_state(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.status_ready.emit(1, 56, False)
        client.operation_error.emit(1, "Windows вернула 56% вместо выбранных 68%.")
        self.assertEqual(popup.value_label.text(), "56%")
        self.assertNotIn("не подтверждено", popup.status.text())
        self.assertIs(popup.indicator.active, False)
        self.assertFalse(popup.status.isHidden())
        self.assertTrue(popup.slider.isEnabled())
        self.assertTrue(popup.retry.isHidden())

    def test_old_state_and_error_cannot_override_retry_result(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.operation_error.emit(1, "Ошибка чтения")
        popup.retry.click()
        client.status_ready.emit(2, 68, False)
        client.status_ready.emit(1, 56, True)
        client.operation_error.emit(1, "Старая ошибка")
        self.assertEqual(popup.value_label.text(), "68%")
        self.assertIs(popup.indicator.active, False)
        self.assertTrue(popup.retry.isHidden())

    def test_old_startup_error_does_not_overwrite_new_read(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.refresh()
        client.operation_error.emit(0, "Старая ошибка")
        self.assertEqual(popup.status.text(), "Чтение системной настройки…")

    def test_closing_popup_flushes_latest_slider_value_once(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.show()
        popup.slider.setValue(56)
        popup.slider.setValue(68)
        popup.hide()
        self.assertEqual(client.writes, [(68, 2)])
        QTest.qWait(190)
        self.assertEqual(len(client.writes), 1)
        popup.stop()

    def test_deactivation_does_not_hide_before_tray_click_is_processed(self):
        client = FakeClient()
        popup = NightLightPopup(client)
        popup.show()
        QApplication.sendEvent(popup, QEvent(QEvent.Type.WindowDeactivate))
        self.assertTrue(popup.isVisible())
        self.assertTrue(popup._dismiss.isActive())
        popup.hide()
        self.assertFalse(popup._dismiss.isActive())
        popup.open_near(QRect(1800, 1040, 24, 24))
        QTest.qWait(120)
        self.assertTrue(popup.isVisible())
        popup.stop()

    def test_popup_fits_all_taskbar_edges_and_negative_monitor_coordinates(self):
        size = QSize(300, 160)
        for available, tray in (
            (QRect(0, 0, 1920, 1040), QRect(1870, 1040, 24, 24)),
            (QRect(0, 40, 1920, 1040), QRect(1870, 8, 24, 24)),
            (QRect(40, 0, 1880, 1080), QRect(8, 1030, 24, 24)),
            (QRect(0, 0, 1880, 1080), QRect(1880, 1030, 24, 24)),
            (QRect(-1920, 0, 1920, 1040), QRect(-50, 1040, 24, 24)),
        ):
            with self.subTest(tray=tray):
                position = popup_position(tray, available, size, tray.center())
                self.assertTrue(available.contains(QRect(position, size)))


if __name__ == "__main__":
    unittest.main()
