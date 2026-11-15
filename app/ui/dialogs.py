"""Dialogs: add terminal, slave settings, symbol mapping, app settings."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from app import i18n
from app.core import constants as C


def scan_installed_terminals() -> list[str]:
    """Search common Windows install paths for terminal64.exe."""
    found: list[str] = []
    roots = []
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        roots = [pf, pf86]
    else:
        roots = ["/tmp"]  # dev environments
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                candidate = os.path.join(root, entry, "terminal64.exe")
                if os.path.isfile(candidate):
                    found.append(candidate)
        except OSError:
            continue
    return sorted(set(found))


class AddTerminalDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("add_terminal"))
        self.setMinimumWidth(560)
        self.result_data: Optional[dict] = None

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit()
        form.addRow(i18n.tr("terminal_name"), self.ed_name)

        path_row = QHBoxLayout()
        self.ed_path = QLineEdit()
        btn_browse = QPushButton(i18n.tr("browse"))
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self.ed_path, 1)
        path_row.addWidget(btn_browse)
        form.addRow(i18n.tr("terminal_path"), path_row)

        self.ed_login = QLineEdit()
        form.addRow(i18n.tr("login"), self.ed_login)
        self.ed_server = QLineEdit()
        form.addRow(i18n.tr("server"), self.ed_server)
        self.ed_password = QLineEdit()
        self.ed_password.setEchoMode(QLineEdit.Password)
        form.addRow(i18n.tr("password_optional"), self.ed_password)
        lay.addLayout(form)

        btn_scan = QPushButton(i18n.tr("scan_terminals"))
        btn_scan.clicked.connect(self._scan)
        lay.addWidget(btn_scan)
        self.list_found = QListWidget()
        self.list_found.itemDoubleClicked.connect(self._pick_found)
        lay.addWidget(self.list_found, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("terminal_path"), "", "terminal64.exe (terminal64.exe)")
        if path:
            self.ed_path.setText(path)
            if not self.ed_name.text():
                self.ed_name.setText(os.path.basename(os.path.dirname(path)))

    def _scan(self) -> None:
        self.list_found.clear()
        for path in scan_installed_terminals():
            QListWidgetItem(path, self.list_found)

    def _pick_found(self, item: QListWidgetItem) -> None:
        self.ed_path.setText(item.text())
        if not self.ed_name.text():
            self.ed_name.setText(os.path.basename(os.path.dirname(item.text())))

    def _accept(self) -> None:
        path = self.ed_path.text().strip()
        if not path or not os.path.isfile(path):
            self.ed_path.setFocus()
            return
        login = None
        if self.ed_login.text().strip():
            try:
                login = int(self.ed_login.text().strip())
            except ValueError:
                self.ed_login.setFocus()
                return
        self.result_data = {
            "name": self.ed_name.text().strip() or os.path.basename(
                os.path.dirname(path)),
            "path": path,
            "login": login,
            "server": self.ed_server.text().strip() or None,
            "password": self.ed_password.text() or None,
        }
        self.accept()


class SlaveSettingsDialog(QDialog):
    def __init__(self, parent, controller, terminal_id: str):
        super().__init__(parent)
        self.controller = controller
        self.terminal_id = terminal_id
        s = controller.repo.get_slave_settings(terminal_id)
        self.setWindowTitle(f"{i18n.tr('slave_settings')} — "
                            f"{controller.runtimes[terminal_id].row.get('name')}")

        lay = QVBoxLayout(self)
        grid = QGridLayout()
        col = 0

        # ---- copy ----
        box_copy = QGroupBox(i18n.tr("grp_copy"))
        f1 = QFormLayout(box_copy)
        self.cb_enabled = QCheckBox(i18n.tr("copy_enabled"))
        self.cb_enabled.setChecked(bool(s.get("copy_enabled")))
        f1.addRow(self.cb_enabled)
        self.cb_partial = QCheckBox(i18n.tr("copy_partial"))
        self.cb_partial.setChecked(bool(s.get("copy_partial_close")))
        f1.addRow(self.cb_partial)
        self.cb_pending = QCheckBox(i18n.tr("copy_pending"))
        self.cb_pending.setChecked(bool(s.get("copy_pending")))
        f1.addRow(self.cb_pending)
        self.cb_reconnect = QCheckBox(i18n.tr("auto_reconnect"))
        self.cb_reconnect.setChecked(bool(s.get("auto_reconnect")))
        f1.addRow(self.cb_reconnect)
        grid.addWidget(box_copy, 0, col); col += 1

        # ---- volume ----
        box_vol = QGroupBox(i18n.tr("grp_volume"))
        f2 = QFormLayout(box_vol)
        self.cmb_lot_mode = QComboBox()
        for mode, label in [
            (C.LotMode.SAME.value, "Same Lot"),
            (C.LotMode.MULTIPLIER.value, "Lot Multiplier"),
            (C.LotMode.FIXED.value, "Fixed Lot"),
            (C.LotMode.BALANCE_RATIO.value, "Balance Ratio"),
            (C.LotMode.EQUITY_RATIO.value, "Equity Ratio"),
        ]:
            self.cmb_lot_mode.addItem(label, mode)
        self.cmb_lot_mode.setCurrentIndex(
            max(0, self.cmb_lot_mode.findData(s.get("lot_mode"))))
        f2.addRow(i18n.tr("lot_mode"), self.cmb_lot_mode)
        self.sp_multiplier = QDoubleSpinBox()
        self.sp_multiplier.setRange(0.01, 100.0)
        self.sp_multiplier.setSingleStep(0.1)
        self.sp_multiplier.setValue(float(s.get("lot_multiplier") or 1.0))
        f2.addRow(i18n.tr("lot_multiplier"), self.sp_multiplier)
        self.sp_fixed = QDoubleSpinBox()
        self.sp_fixed.setRange(0.01, 1000.0)
        self.sp_fixed.setDecimals(2)
        self.sp_fixed.setValue(float(s.get("fixed_lot") or 0.01))
        f2.addRow(i18n.tr("fixed_lot"), self.sp_fixed)
        self.sp_balance_ratio = QDoubleSpinBox()
        self.sp_balance_ratio.setRange(0.01, 100.0)
        self.sp_balance_ratio.setValue(float(s.get("balance_ratio") or 1.0))
        f2.addRow(i18n.tr("balance_ratio"), self.sp_balance_ratio)
        self.sp_equity_ratio = QDoubleSpinBox()
        self.sp_equity_ratio.setRange(0.01, 100.0)
        self.sp_equity_ratio.setValue(float(s.get("equity_ratio") or 1.0))
        f2.addRow(i18n.tr("equity_ratio"), self.sp_equity_ratio)
        self.sp_max_lot = QDoubleSpinBox()
        self.sp_max_lot.setRange(0.0, 1000.0)
        self.sp_max_lot.setSpecialValueText("—")
        if s.get("max_lot"):
            self.sp_max_lot.setValue(float(s["max_lot"]))
        f2.addRow(i18n.tr("max_lot"), self.sp_max_lot)
        grid.addWidget(box_vol, 0, col); col += 1

        # ---- risk ----
        box_risk = QGroupBox(i18n.tr("grp_risk"))
        f3 = QFormLayout(box_risk)
        self.sp_max_positions = QSpinBox()
        self.sp_max_positions.setRange(0, 1000)
        self.sp_max_positions.setSpecialValueText("—")
        if s.get("max_positions"):
            self.sp_max_positions.setValue(int(s["max_positions"]))
        f3.addRow(i18n.tr("max_positions"), self.sp_max_positions)
        self.sp_slippage = QSpinBox()
        self.sp_slippage.setRange(1, 1000)
        self.sp_slippage.setValue(int(s.get("max_slippage_points") or 50))
        f3.addRow(i18n.tr("max_slippage"), self.sp_slippage)
        self.sp_spread = QSpinBox()
        self.sp_spread.setRange(0, 10000)
        self.sp_spread.setSpecialValueText("—")
        if s.get("max_spread_points"):
            self.sp_spread.setValue(int(s["max_spread_points"]))
        f3.addRow(i18n.tr("max_spread"), self.sp_spread)
        self.sp_min_free_margin = QDoubleSpinBox()
        self.sp_min_free_margin.setRange(0.0, 10_000_000)
        self.sp_min_free_margin.setDecimals(2)
        self.sp_min_free_margin.setSpecialValueText("—")
        if s.get("min_free_margin"):
            self.sp_min_free_margin.setValue(float(s["min_free_margin"]))
        f3.addRow(i18n.tr("min_free_margin"), self.sp_min_free_margin)
        self.sp_min_margin_level = QDoubleSpinBox()
        self.sp_min_margin_level.setRange(0.0, 10000)
        self.sp_min_margin_level.setSpecialValueText("—")
        if s.get("min_margin_level"):
            self.sp_min_margin_level.setValue(float(s["min_margin_level"]))
        f3.addRow(i18n.tr("min_margin_level"), self.sp_min_margin_level)
        self.sp_equity_stop = QDoubleSpinBox()
        self.sp_equity_stop.setRange(0.0, 100_000_000)
        self.sp_equity_stop.setSpecialValueText("—")
        if s.get("stop_if_equity_below"):
            self.sp_equity_stop.setValue(float(s["stop_if_equity_below"]))
        f3.addRow(i18n.tr("stop_if_equity_below"), self.sp_equity_stop)
        grid.addWidget(box_risk, 0, col); col += 1

        # ---- SLTP ----
        box_sltp = QGroupBox(i18n.tr("grp_sltp"))
        f4 = QFormLayout(box_sltp)
        self.cb_copy_sl = QCheckBox(i18n.tr("copy_sl"))
        self.cb_copy_sl.setChecked(bool(s.get("copy_sl")))
        f4.addRow(self.cb_copy_sl)
        self.cb_copy_tp = QCheckBox(i18n.tr("copy_tp"))
        self.cb_copy_tp.setChecked(bool(s.get("copy_tp")))
        f4.addRow(self.cb_copy_tp)
        self.cmb_sltp_mode = QComboBox()
        self.cmb_sltp_mode.addItem(i18n.tr("sltp_absolute"), C.SlTpMode.ABSOLUTE.value)
        self.cmb_sltp_mode.addItem(i18n.tr("sltp_distance"), C.SlTpMode.DISTANCE.value)
        self.cmb_sltp_mode.setCurrentIndex(max(
            0, self.cmb_sltp_mode.findData(s.get("sltp_mode"))))
        f4.addRow(i18n.tr("sltp_mode"), self.cmb_sltp_mode)
        self.cb_stops_adjust = QCheckBox(i18n.tr("allow_stops_adjust"))
        self.cb_stops_adjust.setChecked(bool(s.get("allow_stops_adjust")))
        f4.addRow(self.cb_stops_adjust)
        self.cmb_pending_price = QComboBox()
        self.cmb_pending_price.addItem(i18n.tr("sltp_absolute"),
                                       C.PendingPriceMode.ABSOLUTE.value)
        self.cmb_pending_price.addItem(i18n.tr("sltp_distance"),
                                       C.PendingPriceMode.DISTANCE.value)
        self.cmb_pending_price.setCurrentIndex(max(
            0, self.cmb_pending_price.findData(s.get("pending_price_mode"))))
        f4.addRow(i18n.tr("pending_price_mode"), self.cmb_pending_price)
        grid.addWidget(box_sltp, 1, 0)

        # ---- symbols ----
        box_sym = QGroupBox(i18n.tr("grp_symbols"))
        f5 = QFormLayout(box_sym)
        self.ed_allowed_symbols = QLineEdit(s.get("allowed_symbols") or "")
        f5.addRow(i18n.tr("allowed_symbols"), self.ed_allowed_symbols)
        self.ed_directions = QLineEdit(s.get("allowed_directions") or "BUY,SELL")
        f5.addRow(i18n.tr("allowed_directions"), self.ed_directions)
        grid.addWidget(box_sym, 1, 1, 1, col - 1)

        lay.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self) -> None:
        self.controller.update_slave_settings(
            self.terminal_id,
            copy_enabled=int(self.cb_enabled.isChecked()),
            copy_partial_close=int(self.cb_partial.isChecked()),
            copy_pending=int(self.cb_pending.isChecked()),
            auto_reconnect=int(self.cb_reconnect.isChecked()),
            lot_mode=self.cmb_lot_mode.currentData(),
            lot_multiplier=self.sp_multiplier.value(),
            fixed_lot=self.sp_fixed.value(),
            balance_ratio=self.sp_balance_ratio.value(),
            equity_ratio=self.sp_equity_ratio.value(),
            max_lot=(self.sp_max_lot.value() or None),
            max_positions=(self.sp_max_positions.value() or None),
            max_slippage_points=self.sp_slippage.value(),
            max_spread_points=(self.sp_spread.value() or None),
            min_free_margin=(self.sp_min_free_margin.value() or None),
            min_margin_level=(self.sp_min_margin_level.value() or None),
            stop_if_equity_below=(self.sp_equity_stop.value() or None),
            copy_sl=int(self.cb_copy_sl.isChecked()),
            copy_tp=int(self.cb_copy_tp.isChecked()),
            sltp_mode=self.cmb_sltp_mode.currentData(),
            allow_stops_adjust=int(self.cb_stops_adjust.isChecked()),
            pending_price_mode=self.cmb_pending_price.currentData(),
            allowed_symbols=self.ed_allowed_symbols.text().strip(),
            allowed_directions=self.ed_directions.text().strip() or "BUY,SELL",
        )
        self.accept()


class SymbolMapDialog(QDialog):
    def __init__(self, parent, controller, terminal_id: str):
        super().__init__(parent)
        self.controller = controller
        self.terminal_id = terminal_id
        self.setWindowTitle(f"{i18n.tr('symbol_mapping')} — "
                            f"{controller.runtimes[terminal_id].row.get('name')}")
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels([
            i18n.tr("map_master_symbol"), i18n.tr("map_slave_symbol"),
            i18n.tr("map_status"), i18n.tr("map_note")])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        lay.addWidget(self.tbl, 1)

        row = QHBoxLayout()
        self.ed_master = QLineEdit()
        self.ed_master.setPlaceholderText(i18n.tr("map_master_symbol"))
        self.ed_slave = QLineEdit()
        self.ed_slave.setPlaceholderText(i18n.tr("map_slave_symbol"))
        btn_add = QPushButton(i18n.tr("map_add"))
        btn_add.clicked.connect(self._add_mapping)
        row.addWidget(self.ed_master, 1)
        row.addWidget(self.ed_slave, 1)
        row.addWidget(btn_add)
        lay.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.reject)
        lay.addWidget(buttons)
        self._reload()

    def _reload(self) -> None:
        maps = self.controller.list_symbol_maps(self.terminal_id)
        self.tbl.setRowCount(len(maps))
        for r, m in enumerate(maps):
            for c, v in enumerate([m["master_symbol"], m["slave_symbol"] or "—",
                                   m["status"], m["note"] or ""]):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.tbl.setItem(r, c, item)

    def _add_mapping(self) -> None:
        master = self.ed_master.text().strip()
        slave = self.ed_slave.text().strip()
        if not master:
            return
        rt = self.controller.runtimes[self.terminal_id]
        if slave and rt.symbols and slave not in rt.symbols:
            ret = QMessageBox.question(
                self, i18n.tr("error"),
                f"'{slave}' not in this account's symbol list. Save anyway?")
            if ret != QMessageBox.Yes:
                return
        self.controller.set_symbol_map(self.terminal_id, master,
                                       slave or None, verified=bool(slave))
        self.ed_master.clear()
        self.ed_slave.clear()
        self._reload()


class AppSettingsDialog(QDialog):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(i18n.tr("app_settings"))
        form = QFormLayout(self)
        self.sp_master = QSpinBox()
        self.sp_master.setRange(25, 1000)
        self.sp_master.setValue(controller.repo.get_setting_int(
            "poll_ms_master", 50))
        form.addRow(i18n.tr("poll_master_ms"), self.sp_master)
        self.sp_slave = QSpinBox()
        self.sp_slave.setRange(100, 5000)
        self.sp_slave.setValue(controller.repo.get_setting_int(
            "poll_ms_slave", 250))
        form.addRow(i18n.tr("poll_slave_ms"), self.sp_slave)
        self.sp_window = QSpinBox()
        self.sp_window.setRange(60, 7200)
        self.sp_window.setValue(controller.repo.get_setting_int(
            "deal_window_sec", 600))
        form.addRow(i18n.tr("deal_window_sec"), self.sp_window)
        self.cb_precheck = QCheckBox(i18n.tr("precheck_margin"))
        self.cb_precheck.setChecked(bool(controller.repo.get_setting_int(
            "precheck_margin", 1)))
        form.addRow(self.cb_precheck)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        self.controller.set_global_setting(
            "poll_ms_master", str(self.sp_master.value()))
        self.controller.set_global_setting(
            "poll_ms_slave", str(self.sp_slave.value()))
        self.controller.set_global_setting(
            "deal_window_sec", str(self.sp_window.value()))
        self.controller.set_global_setting(
            "precheck_margin", "1" if self.cb_precheck.isChecked() else "0")
        self.accept()
