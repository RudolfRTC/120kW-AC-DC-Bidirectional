"""Application entry point for the DC/DC Mission Console GUI."""

from __future__ import annotations

import sys
from typing import Optional


def launch(argv: Optional[list] = None) -> int:
    """Create and run the Qt application."""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
    except ImportError:
        print(
            "ERROR: PySide6 is not installed.\n"
            "Install with:  pip install PySide6 pyqtgraph numpy\n"
            "Or:            pip install -e '.[gui]'",
            file=sys.stderr,
        )
        return 1

    try:
        import pyqtgraph  # noqa: F401
    except ImportError:
        print(
            "ERROR: pyqtgraph is not installed.\n"
            "Install with:  pip install pyqtgraph numpy",
            file=sys.stderr,
        )
        return 1

    from dcdc_app.gui.theme import AEROSPACE_QSS
    from dcdc_app.gui.main_window import MainWindow

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(argv or sys.argv)
    app.setApplicationName("DC/DC Mission Console")
    app.setOrganizationName("YSTECH PCS")
    app.setStyleSheet(AEROSPACE_QSS)

    window = MainWindow()
    window.show()

    return app.exec()
