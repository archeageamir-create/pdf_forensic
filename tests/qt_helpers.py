import time
from PySide6.QtWidgets import QApplication


def wait_for_export(window, timeout=10):
    deadline = time.monotonic() + timeout
    while window.export_worker is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert window.export_worker is None, "Export did not finish"
