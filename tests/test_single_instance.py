"""Проверка единственного экземпляра и освобождения блокировки на Windows"""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tray import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_second_instance_activates_first_and_does_not_acquire_lock(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("tray.data_directory", return_value=Path(folder)),
            patch("tray.getpass.getuser", return_value=uuid.uuid4().hex),
        ):
            activations = []
            first = SingleInstance(lambda: activations.append(True))
            second = SingleInstance(lambda: None)
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                QTest.qWait(30)
                self.assertEqual(activations, [True])
                second.close()
                self.assertTrue(first.lock.isLocked())
                first.close()
                self.assertTrue(second.acquire())
            finally:
                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
