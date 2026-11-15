"""Dark premium theme (QSS) + palette constants."""
from __future__ import annotations

# palette
BG = "#0b0f14"          # near-black
PANEL = "#111820"       # panel background
PANEL2 = "#151d27"      # alt panel
BORDER = "#1f2a36"
TEXT = "#d6e1ec"
TEXT_DIM = "#7a8a99"
GREEN = "#39d353"       # phosphor-ish green
GREEN_DIM = "#1a7f37"
RED = "#f85149"
YELLOW = "#d29922"
GRAY = "#39414d"
ACCENT = "#2ea043"

QSS = f"""
* {{
    background-color: {PANEL};
    color: {TEXT};
    font-family: "Segoe UI", "Vazirmatn", "Tahoma";
    font-size: 12px;
}}
QMainWindow, QWidget#root {{ background-color: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 15px; font-weight: 700; }}
QLabel#chip {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px 12px;
}}
QLabel#chipGreen {{ background-color: rgba(57,211,83,0.12);
    border: 1px solid {GREEN_DIM}; color: {GREEN}; border-radius: 10px;
    padding: 4px 12px; }}
QLabel#chipRed {{ background-color: rgba(248,81,73,0.12);
    border: 1px solid {RED}; color: {RED}; border-radius: 10px;
    padding: 4px 12px; }}
QLabel#chipYellow {{ background-color: rgba(210,153,34,0.12);
    border: 1px solid {YELLOW}; color: {YELLOW}; border-radius: 10px;
    padding: 4px 12px; }}

QFrame#card {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#cardMaster {{
    background-color: {PANEL};
    border: 1px solid {GREEN_DIM};
    border-radius: 10px;
}}

QPushButton {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {GRAY}; }}
QPushButton#danger {{
    background-color: rgba(248,81,73,0.15);
    border: 1px solid {RED};
    color: {RED};
    font-weight: 600;
}}
QPushButton#primary {{
    background-color: rgba(46,160,67,0.18);
    border: 1px solid {ACCENT};
    color: {GREEN};
    font-weight: 600;
}}
QPushButton#flat {{ border: none; background: transparent; color: {TEXT_DIM}; }}
QPushButton#flat:hover {{ color: {TEXT}; }}

QTableWidget {{
    background-color: {PANEL};
    alternate-background-color: {PANEL2};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: #1c2a3a;
}}
QHeaderView::section {{
    background-color: {PANEL2};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
}}
QTableWidget::item {{ padding: 3px 6px; }}

QListWidget {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QListWidget::item {{ padding: 3px 8px; border-bottom: 1px solid {BORDER}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {PANEL2};
    border: 1px solid {BORDER};
    selection-background-color: #1c2a3a;
}}
QCheckBox {{ background: transparent; spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER}; border-radius: 4px;
    background: {BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding: 8px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; padding: 0 6px; color: {TEXT_DIM}; }}

QScrollBar:vertical {{
    background: {BG}; width: 9px; border: none;
}}
QScrollBar::handle:vertical {{
    background: {GRAY}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 9px; border: none; }}
QScrollBar::handle:horizontal {{
    background: {GRAY}; border-radius: 4px; min-width: 30px;
}}

QDialog {{ background-color: {PANEL}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; }}
QTabBar::tab {{
    background: {PANEL2}; padding: 6px 16px;
    border-top-right-radius: 6px; border-top-left-radius: 6px;
}}
QTabBar::tab:selected {{ color: {GREEN}; border-bottom: 2px solid {ACCENT}; }}
"""


def pl_color(v: float) -> str:
    if v > 0:
        return GREEN
    if v < 0:
        return RED
    return TEXT_DIM
