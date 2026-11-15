"""Qt application bootstrap: theme, direction (RTL for Persian), main window."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app import i18n
from app.ui import theme


def run_app(controller) -> int:
    lang = controller.repo.get_setting("language", "fa")
    i18n.set_lang(lang)

    app = QApplication(sys.argv)
    app.setApplicationName("Trading Copier")
    app.setStyleSheet(theme.QSS)
    if i18n.LANG == "fa":
        app.setLayoutDirection(Qt.RightToLeft)

    from app.ui.main_window import MainWindow
    win = MainWindow(controller)
    win.show()

    # controller keeps running while the window is open
    ret = app.exec()
    return ret
