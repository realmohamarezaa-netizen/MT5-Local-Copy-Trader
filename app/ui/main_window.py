"""Main dashboard window: minimal, dark, fast. UI never blocks: a QTimer
pulls precomputed state from StateStore every 200ms."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QGridLayout,
    QFrame, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import i18n
from app.ui import theme
from app.ui.dialogs import (AppSettingsDialog, AddTerminalDialog,
                            SlaveSettingsDialog, SymbolMapDialog)


def _fmt(v, digits=2):
    if v is None:
        return i18n.tr("no_data")
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


class MainWindow(QMainWindow):
    REFRESH_MS = 200

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle(i18n.tr("app_title"))
        self.resize(1280, 800)
        self.setMinimumSize(1000, 640)
        self._positions_filter_tid: Optional[str] = None

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        layout.addLayout(self._build_top_bar())
        layout.addLayout(self._build_control_bar())
        layout.addWidget(self._build_alerts())
        layout.addWidget(self._build_master_card())
        layout.addWidget(self._build_slave_section(), stretch=5)
        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(self._build_positions_section())
        bottom.addWidget(self._build_activity_section())
        bottom.setSizes([820, 420])
        layout.addWidget(bottom, stretch=6)

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _chip(self, text: str, kind: str = "chip") -> QLabel:
        lbl = QLabel(text, objectName=kind)
        return lbl

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        title = QLabel("Trading Copier", objectName="title")
        bar.addWidget(title)
        bar.addSpacing(12)
        self.chip_engine = self._chip("")
        bar.addWidget(self.chip_engine)
        self.chip_master = self._chip("")
        bar.addWidget(self.chip_master)
        bar.addSpacing(8)
        self.lbl_lang = QLabel(i18n.tr("language") + ":")
        self.combo_lang = QComboBox()
        self.combo_lang.addItem("فارسی", "fa")
        self.combo_lang.addItem("English", "en")
        self.combo_lang.setCurrentIndex(0 if i18n.LANG == "fa" else 1)
        self.combo_lang.currentIndexChanged.connect(self._on_lang_change)
        bar.addWidget(self.lbl_lang)
        bar.addWidget(self.combo_lang)
        btn_settings = QPushButton(i18n.tr("app_settings"), objectName="flat")
        btn_settings.clicked.connect(self._open_app_settings)
        bar.addWidget(btn_settings)
        btn_logs = QPushButton(i18n.tr("export_logs"), objectName="flat")
        btn_logs.clicked.connect(self._export_logs)
        bar.addWidget(btn_logs)
        bar.addStretch(1)
        self.chip_stats = self._chip("")
        bar.addWidget(self.chip_stats)
        return bar

    def _build_control_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.btn_start = QPushButton(i18n.tr("start_copying"), objectName="primary")
        self.btn_start.clicked.connect(self._on_start)
        bar.addWidget(self.btn_start)
        self.btn_pause = QPushButton(i18n.tr("pause_copying"))
        self.btn_pause.clicked.connect(self.controller.pause_copying)
        bar.addWidget(self.btn_pause)
        self.btn_resume = QPushButton(i18n.tr("resume_copying"))
        self.btn_resume.clicked.connect(self.controller.resume_copying)
        bar.addWidget(self.btn_resume)
        self.btn_stop = QPushButton(i18n.tr("stop_copying"))
        self.btn_stop.clicked.connect(self.controller.stop_copying)
        bar.addWidget(self.btn_stop)
        self.btn_emergency = QPushButton(i18n.tr("emergency_stop"), objectName="danger")
        self.btn_emergency.clicked.connect(self._on_emergency)
        bar.addWidget(self.btn_emergency)
        self.btn_close_copied = QPushButton(i18n.tr("close_copied"))
        self.btn_close_copied.clicked.connect(self._on_close_copied)
        bar.addWidget(self.btn_close_copied)
        btn_add = QPushButton("+ " + i18n.tr("add_terminal"))
        btn_add.clicked.connect(self._on_add_terminal)
        bar.addWidget(btn_add)
        bar.addStretch(1)
        return bar

    def _build_alerts(self) -> QFrame:
        frame = QFrame(objectName="card")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 6, 10, 6)
        self.lbl_alerts = QLabel("")
        self.lbl_alerts.setStyleSheet(f"color: {theme.RED}; background: transparent;")
        self.lbl_alerts.setWordWrap(True)
        lay.addWidget(self.lbl_alerts, 1)
        btn = QPushButton(i18n.tr("dismiss_alerts"), objectName="flat")
        btn.clicked.connect(self._clear_alerts)
        lay.addWidget(btn)
        frame.setVisible(False)
        self.alerts_frame = frame
        return frame

    def _build_master_card(self) -> QFrame:
        frame = QFrame(objectName="cardMaster")
        grid = QGridLayout(frame)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)

        self.lbl_master_title = QLabel(i18n.tr("master"), objectName="title")
        self.lbl_master_title.setStyleSheet(f"color: {theme.GREEN};")
        grid.addWidget(self.lbl_master_title, 0, 0)
        self.lbl_master_name = QLabel("—")
        self.lbl_master_name.setStyleSheet("font-size: 14px; font-weight: 600;")
        grid.addWidget(self.lbl_master_name, 0, 1)
        self.lbl_master_conn = QLabel("")
        grid.addWidget(self.lbl_master_conn, 0, 2)
        grid.setColumnStretch(3, 1)

        self.master_fields = {}
        keys = ["login", "broker", "balance", "equity", "free_margin",
                "used_margin", "margin_level", "floating_pl", "leverage",
                "open_positions", "algo_trading"]
        for i, key in enumerate(keys):
            box = QVBoxLayout()
            cap = QLabel(i18n.tr(key))
            cap.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            val = QLabel("—")
            val.setStyleSheet("font-size: 13px; font-weight: 600;")
            box.addWidget(cap)
            box.addWidget(val)
            widget = QWidget()
            widget.setLayout(box)
            widget.setStyleSheet("background: transparent;")
            grid.addWidget(widget, 1 + i // 6, i % 6)
            self.master_fields[key] = val
        self.master_frame = frame
        return frame

    def _build_slave_section(self) -> QFrame:
        frame = QFrame(objectName="card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        self.lbl_slaves_title = QLabel(i18n.tr("slaves"), objectName="title")
        lay.addWidget(self.lbl_slaves_title)
        cols = ["col_name", "col_login", "col_server", "col_balance",
                "col_equity", "col_free_margin", "col_margin",
                "col_margin_level", "col_pl", "col_currency", "col_positions",
                "col_connection", "col_copy", "col_errors", "col_updated",
                "col_latency", "col_actions"]
        self.tbl_slaves = QTableWidget(0, len(cols))
        self.tbl_slaves.setHorizontalHeaderLabels([i18n.tr(c) for c in cols])
        self.tbl_slaves.verticalHeader().setVisible(False)
        self.tbl_slaves.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_slaves.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_slaves.setAlternatingRowColors(True)
        header = self.tbl_slaves.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_slaves.setMinimumHeight(180)
        lay.addWidget(self.tbl_slaves)
        self._slave_cols = cols
        return frame

    def _build_positions_section(self) -> QFrame:
        frame = QFrame(objectName="card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        self.lbl_positions_title = QLabel(i18n.tr("live_positions"),
                                          objectName="title")
        head.addWidget(self.lbl_positions_title)
        head.addStretch(1)
        self.lbl_filter = QLabel(i18n.tr("filter_account"))
        self.combo_filter = QComboBox()
        self.combo_filter.currentIndexChanged.connect(self._on_filter_change)
        head.addWidget(self.lbl_filter)
        head.addWidget(self.combo_filter)
        lay.addLayout(head)

        cols = ["col_account", "col_role", "col_symbol", "col_ticket",
                "col_type", "col_volume", "col_open_price",
                "col_current_price", "col_sl", "col_tp", "col_profit",
                "col_swap", "col_copy_status", "col_master_ref"]
        self.tbl_positions = QTableWidget(0, len(cols))
        self.tbl_positions.setHorizontalHeaderLabels([i18n.tr(c) for c in cols])
        self.tbl_positions.verticalHeader().setVisible(False)
        self.tbl_positions.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_positions.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_positions.setAlternatingRowColors(True)
        self.tbl_positions.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.tbl_positions.setMaximumHeight(260)
        lay.addWidget(self.tbl_positions)
        self._positions_cols = cols
        return frame

    def _build_activity_section(self) -> QFrame:
        frame = QFrame(objectName="card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        self.lbl_activity_title = QLabel(i18n.tr("live_activity"),
                                         objectName="title")
        lay.addWidget(self.lbl_activity_title)
        self.list_activity = QListWidget()
        lay.addWidget(self.list_activity)
        return frame

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        state = self.controller.store.get()
        activity = self.controller.store.get_activity()
        engine = state["engine_state"]
        stats = state["stats"]

        self._set_engine_ui(engine)
        # chips
        master = state["master"]
        if master and master.get("connected"):
            self.chip_master.setText(i18n.tr("master_connected"))
            self.chip_master.setObjectName("chipGreen")
        else:
            self.chip_master.setText(i18n.tr("master_disconnected"))
            self.chip_master.setObjectName("chipRed")
        self.chip_master.setStyleSheet(
            f"QLabel#chipGreen {{ background-color: rgba(57,211,83,0.12);"
            f" border: 1px solid {theme.GREEN_DIM}; color: {theme.GREEN};"
            f" border-radius: 10px; padding: 4px 12px; }}"
            f"QLabel#chipRed {{ background-color: rgba(248,81,73,0.12);"
            f" border: 1px solid {theme.RED}; color: {theme.RED};"
            f" border-radius: 10px; padding: 4px 12px; }}")
        lat = _fmt(stats.get("avg_copy_ms"), 1)
        p95 = _fmt(stats.get("p95_copy_ms"), 1)
        self.chip_stats.setText(
            f"{i18n.tr('accounts')} {stats['accounts_total']}"
            f" · {i18n.tr('connected')} {stats['accounts_connected']}"
            f" · {i18n.tr('active_slaves')} {stats['slaves_active']}"
            f" · {i18n.tr('copied')} {stats['copied_total']}"
            f" · {i18n.tr('failed')} {stats['failed_total']}"
            f" · {i18n.tr('avg_latency')} {lat}ms"
            f" · {i18n.tr('p95_latency')} {p95}ms")

        # alerts
        alerts = state.get("alerts") or []
        self.alerts_frame.setVisible(bool(alerts))
        if alerts:
            self.lbl_alerts.setText("  |  ".join(alerts[-3:]))

        # master card
        self._refresh_master(master)

        # slaves table
        self._refresh_slaves(state["slaves"])

        # positions table
        self._refresh_filter_options(state)
        self._refresh_positions()

        # activity list
        self._refresh_activity(activity)

    def _set_engine_ui(self, engine: str) -> None:
        text = {
            "RUNNING": i18n.tr("engine_running"),
            "PAUSED": i18n.tr("engine_paused"),
            "STOPPED": i18n.tr("engine_stopped"),
            "EMERGENCY": i18n.tr("engine_emergency"),
        }.get(engine, engine)
        self.chip_engine.setText(text)
        kind = {"RUNNING": "chipGreen", "PAUSED": "chipYellow",
                "STOPPED": "chip", "EMERGENCY": "chipRed"}.get(engine, "chip")
        self.chip_engine.setObjectName(kind)
        self.chip_engine.setStyleSheet(
            f"QLabel#chipGreen {{ color: {theme.GREEN}; }}"
            f"QLabel#chipYellow {{ color: {theme.YELLOW}; }}"
            f"QLabel#chipRed {{ color: {theme.RED}; }}"
            f"QLabel#chip {{ color: {theme.TEXT}; }}")
        is_master_set = self.controller.repo.get_master() is not None
        self.btn_start.setEnabled(is_master_set and engine in
                                  ("STOPPED", "EMERGENCY"))
        self.btn_pause.setEnabled(engine == "RUNNING")
        self.btn_resume.setEnabled(engine == "PAUSED")
        self.btn_stop.setEnabled(engine in ("RUNNING", "PAUSED"))
        self.btn_emergency.setEnabled(engine != "EMERGENCY")

    def _refresh_master(self, master) -> None:
        if not master:
            self.lbl_master_name.setText(i18n.tr("no_data"))
            self.lbl_master_conn.setText(i18n.tr("connected_off"))
            for val in self.master_fields.values():
                val.setText(i18n.tr("no_data"))
            return
        snap = master.get("snapshot") or {}
        self.lbl_master_name.setText(
            f"{master.get('name')}  ·  {master.get('login')}  ·  "
            f"{snap.get('account_name', '')}")
        self.lbl_master_conn.setText(
            i18n.tr("connected_on") if master.get("connected")
            else i18n.tr("connected_off"))
        self.lbl_master_conn.setStyleSheet(
            f"color: {theme.GREEN if master.get('connected') else theme.RED};")
        f = self.master_fields
        f["login"].setText(str(snap.get("login") or master.get("login") or "—"))
        f["broker"].setText(
            f"{snap.get('server') or master.get('server') or '—'}"
            f"  ({snap.get('currency') or '—'})")
        f["balance"].setText(_fmt(snap.get("balance")))
        f["equity"].setText(_fmt(snap.get("equity")))
        f["free_margin"].setText(_fmt(snap.get("margin_free")))
        f["used_margin"].setText(_fmt(snap.get("margin")))
        ml = snap.get("margin_level")
        f["margin_level"].setText(
            _fmt(ml, 1) + "%" if ml not in (None, 0) else i18n.tr("no_data"))
        pl = snap.get("profit")
        f["floating_pl"].setText(_fmt(pl))
        f["floating_pl"].setStyleSheet(
            f"color: {theme.pl_color(float(pl or 0))};")
        f["leverage"].setText(f"1:{snap.get('leverage') or '—'}")
        f["open_positions"].setText(str(len(snap.get("positions", []))))
        f["algo_trading"].setText(
            "ON" if snap.get("terminal_trade_allowed") else "OFF")
        f["algo_trading"].setStyleSheet(
            f"color: {theme.GREEN if snap.get('terminal_trade_allowed') else theme.RED};")

    def _refresh_slaves(self, slaves: list) -> None:
        tbl = self.tbl_slaves
        tbl.setRowCount(len(slaves))
        for r, s in enumerate(slaves):
            snap = s.get("snapshot") or {}
            vals = [
                s.get("name"), s.get("login"), s.get("server"),
                _fmt(snap.get("balance")), _fmt(snap.get("equity")),
                _fmt(snap.get("margin_free")), _fmt(snap.get("margin")),
                (_fmt(snap.get("margin_level"), 1) if snap.get("margin_level")
                 else i18n.tr("no_data")),
                _fmt(snap.get("profit")), snap.get("currency") or "—",
                str(len(snap.get("positions", []))),
                (i18n.tr("connected_on") if s.get("connected")
                 else (s.get("status") or i18n.tr("connected_off"))),
                (i18n.tr("copy_on") if s.get("copy_enabled")
                 else i18n.tr("copy_off")),
                "—",
                f"{max(0, int((s.get('snapshot_age_ms') or 0) / 1000))}s",
                f"{s.get('worker_latency_ms') or 0:.0f}ms",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                tbl.setItem(r, c, item)
            # error count cell (from last_error presence)
            err_item = QTableWidgetItem("1" if s.get("last_error") else "0")
            err_item.setForeground(
                theme.RED if s.get("last_error") else theme.TEXT_DIM)
            tbl.setItem(r, self._slave_cols.index("col_errors"), err_item)

            # actions cell
            cell = QWidget()
            hl = QHBoxLayout(cell)
            hl.setContentsMargins(2, 0, 2, 0)
            hl.setSpacing(4)
            btn_toggle = QPushButton(
                i18n.tr("disable") if s.get("copy_enabled")
                else i18n.tr("enable"), objectName="flat")
            tid = s["terminal_id"]
            enabled = s.get("copy_enabled")
            btn_toggle.clicked.connect(
                lambda _=False, t=tid, e=enabled:
                self.controller.update_slave_settings(t, copy_enabled=0 if e else 1))
            hl.addWidget(btn_toggle)
            btn_cfg = QPushButton(i18n.tr("settings"), objectName="flat")
            btn_cfg.clicked.connect(lambda _=False, t=tid: self._open_slave_settings(t))
            hl.addWidget(btn_cfg)
            btn_map = QPushButton(i18n.tr("symbol_mapping"), objectName="flat")
            btn_map.clicked.connect(lambda _=False, t=tid: self._open_symbol_map(t))
            hl.addWidget(btn_map)
            btn_master = QPushButton(i18n.tr("set_master"), objectName="flat")
            btn_master.clicked.connect(lambda _=False, t=tid: self._on_set_master(t))
            hl.addWidget(btn_master)
            btn_del = QPushButton(i18n.tr("remove"), objectName="flat")
            btn_del.setStyleSheet(f"color: {theme.RED};")
            btn_del.clicked.connect(lambda _=False, t=tid: self._on_remove_terminal(t))
            hl.addWidget(btn_del)
            hl.addStretch(1)
            tbl.setCellWidget(r, self._slave_cols.index("col_actions"), cell)

            if s.get("blocked"):
                for c in range(tbl.columnCount()):
                    it = tbl.item(r, c)
                    if it:
                        it.setForeground(theme.YELLOW)

    def _refresh_filter_options(self, state) -> None:
        accounts = []
        for s in state.get("slaves") or []:
            accounts.append((s["terminal_id"], s.get("name")))
        if state.get("master"):
            accounts.append((state["master"]["terminal_id"],
                             state["master"].get("name")))
        current = self._positions_filter_tid
        self.combo_filter.blockSignals(True)
        self.combo_filter.clear()
        self.combo_filter.addItem(i18n.tr("all"), None)
        for tid, name in accounts:
            self.combo_filter.addItem(name or tid, tid)
        idx = self.combo_filter.findData(current)
        self.combo_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_filter.blockSignals(False)

    def _refresh_positions(self) -> None:
        rows = self.controller.get_positions_view()
        if self._positions_filter_tid:
            rows = [r for r in rows if r["terminal_id"] == self._positions_filter_tid]
        tbl = self.tbl_positions
        tbl.setRowCount(len(rows))
        for r, p in enumerate(rows):
            vals = [
                p.get("account"), p.get("role"), p.get("symbol"),
                str(p.get("ticket")), p.get("type"),
                _fmt(p.get("volume"), 2), _fmt(p.get("price_open"), 5),
                _fmt(p.get("price_current"), 5),
                _fmt(p.get("sl"), 5) if p.get("sl") else "—",
                _fmt(p.get("tp"), 5) if p.get("tp") else "—",
                _fmt(p.get("profit")), _fmt(p.get("swap")),
                i18n.tr("copied_status") if p.get("is_copied")
                else i18n.tr("manual_status"),
                str(p.get("master_position_ref") or "—"),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if self._positions_cols[c] == "col_profit":
                    item.setForeground(theme.pl_color(float(p.get("profit") or 0)))
                if self._positions_cols[c] == "col_copy_status":
                    item.setForeground(
                        theme.GREEN if p.get("is_copied") else theme.TEXT_DIM)
                tbl.setItem(r, c, item)

    def _refresh_activity(self, activity: list) -> None:
        self.list_activity.clear()
        for ts_ms, level, text in activity[:80]:
            t = time.strftime("%H:%M:%S", time.localtime(ts_ms / 1000))
            item = QListWidgetItem(f"{t}  {text}")
            color = {"info": theme.TEXT_DIM, "warn": theme.YELLOW,
                     "error": theme.RED}.get(level, theme.TEXT_DIM)
            item.setForeground(color)
            self.list_activity.addItem(item)

    # ------------------------------------------------------------------
    # slots
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        sync = QMessageBox.question(
            self, i18n.tr("start_copying"), i18n.tr("confirm_start_sync")) == \
            QMessageBox.Yes
        try:
            self.controller.start_copying(sync_existing=sync)
        except ValueError as exc:
            QMessageBox.warning(self, i18n.tr("error"), str(exc))

    def _on_emergency(self) -> None:
        self.controller.emergency_stop()
        QMessageBox.warning(self, i18n.tr("emergency_stop"),
                            i18n.tr("engine_emergency"))

    def _on_close_copied(self) -> None:
        if QMessageBox.question(self, i18n.tr("close_copied"),
                                i18n.tr("confirm_close_copied")) == QMessageBox.Yes:
            self.controller.close_all_copied_positions()

    def _on_add_terminal(self) -> None:
        dlg = AddTerminalDialog(self)
        if dlg.exec():
            data = dlg.result_data
            if data:
                self.controller.add_terminal(
                    data["name"], data["path"], data.get("login"),
                    data.get("server"), data.get("password"))

    def _on_set_master(self, tid: str) -> None:
        if QMessageBox.question(self, i18n.tr("set_master"),
                                i18n.tr("confirm_set_master")) == QMessageBox.Yes:
            self.controller.set_master(tid)

    def _on_remove_terminal(self, tid: str) -> None:
        if QMessageBox.question(self, i18n.tr("remove"),
                                i18n.tr("confirm_remove_terminal")) == \
                QMessageBox.Yes:
            self.controller.delete_terminal(tid)

    def _on_filter_change(self, idx: int) -> None:
        tid = self.combo_filter.itemData(idx)
        self._positions_filter_tid = tid
        self._refresh_positions()

    def _open_slave_settings(self, tid: str) -> None:
        SlaveSettingsDialog(self, self.controller, tid).exec()

    def _open_symbol_map(self, tid: str) -> None:
        SymbolMapDialog(self, self.controller, tid).exec()

    def _open_app_settings(self) -> None:
        AppSettingsDialog(self, self.controller).exec()

    def _clear_alerts(self) -> None:
        with self.controller.store._lock:
            self.controller.store.data["alerts"].clear()
        self.alerts_frame.setVisible(False)

    def _on_lang_change(self, idx: int) -> None:
        lang = self.combo_lang.itemData(idx)
        self.controller.set_global_setting("language", lang)
        QMessageBox.information(self, i18n.tr("language"),
                                i18n.tr("restart_required"))

    def _export_logs(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("export_logs"), "tradingcopier-log.csv",
            "CSV (*.csv);;JSON (*.json)")
        if not path:
            return
        import csv
        import json as _json
        rows = self.controller.store.get_activity(1000)
        try:
            if path.endswith(".json"):
                with open(path, "w", encoding="utf-8") as fh:
                    _json.dump([{"ts_ms": t, "level": lv, "text": x}
                                for t, lv, x in rows], fh, ensure_ascii=False,
                               indent=2)
            else:
                with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                    w = csv.writer(fh)
                    w.writerow(["timestamp", "level", "event"])
                    for t, lv, x in rows:
                        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S",
                                                  time.localtime(t / 1000)),
                                    lv, x])
        except OSError as exc:
            QMessageBox.warning(self, i18n.tr("error"), str(exc))

    def closeEvent(self, event) -> None:
        self.controller.shutdown()
        super().closeEvent(event)
