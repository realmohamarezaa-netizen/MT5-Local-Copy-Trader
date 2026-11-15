"""UI translations: FA (default) / EN. Language switch requires app restart."""
from __future__ import annotations

LANG = "fa"

_STRINGS = {
    # ---- general ----
    "app_title": {"fa": "Trading Copier — کپی معاملات MT5", "en": "Trading Copier — MT5 Copy Trading"},
    "fa": {"fa": "فارسی", "en": "Persian"},
    "en": {"fa": "انگلیسی", "en": "English"},
    "language": {"fa": "زبان", "en": "Language"},
    "restart_required": {"fa": "برای اعمال زبان، برنامه را دوباره اجرا کنید.",
                         "en": "Restart the app to apply the language."},

    # ---- engine states ----
    "engine_stopped": {"fa": "موتور کپی: متوقف", "en": "Copy Engine: STOPPED"},
    "engine_running": {"fa": "موتور کپی: در حال اجرا", "en": "Copy Engine: RUNNING"},
    "engine_paused": {"fa": "موتور کپی: متوقف موقت", "en": "Copy Engine: PAUSED"},
    "engine_emergency": {"fa": "موتور کپی: توقف اضطراری!", "en": "Copy Engine: EMERGENCY STOP!"},

    # ---- top controls ----
    "start_copying": {"fa": "شروع کپی", "en": "START COPYING"},
    "pause_copying": {"fa": "توقف موقت", "en": "PAUSE"},
    "resume_copying": {"fa": "ادامه", "en": "RESUME"},
    "stop_copying": {"fa": "توقف", "en": "STOP"},
    "emergency_stop": {"fa": "توقف اضطراری", "en": "EMERGENCY STOP"},
    "close_copied": {"fa": "بستن معاملات کپی‌شده", "en": "CLOSE COPIED POSITIONS"},
    "confirm_close_copied": {
        "fa": "همه معاملات متعلق به موتور کپی در حساب‌های استیو بسته شوند؟\nمعاملات دستی دست‌نخورده باقی می‌مانند.",
        "en": "Close ALL copy-engine positions on slave accounts?\nManual trades will not be touched."},
    "confirm_start_sync": {
        "fa": "همگام‌سازی معاملات باز فعلی مستر با استیوها انجام شود؟\n(اگر لغو شود فقط معاملات جدید کپی می‌شوند)",
        "en": "Sync currently open MASTER positions to slaves?\n(Cancel = copy only new trades)"},

    # ---- status chips ----
    "master_connected": {"fa": "مستر متصل", "en": "MASTER CONNECTED"},
    "master_disconnected": {"fa": "مستر قطع", "en": "MASTER DISCONNECTED"},
    "accounts": {"fa": "حساب‌ها", "en": "Accounts"},
    "connected": {"fa": "متصل", "en": "Connected"},
    "active_slaves": {"fa": "استیو فعال", "en": "Active Slaves"},
    "master_positions": {"fa": "معاملات باز مستر", "en": "Master Open Positions"},
    "copied": {"fa": "کپی‌شده", "en": "Copied"},
    "failed": {"fa": "ناموفق", "en": "Failed"},
    "avg_latency": {"fa": "میانگین تأخیر کپی", "en": "Avg Copy Latency"},
    "p95_latency": {"fa": "صدک ۹۵ تأخیر", "en": "P95 Latency"},
    "last_update": {"fa": "آخرین به‌روزرسانی", "en": "Last Update"},
    "no_data": {"fa": "—", "en": "—"},

    # ---- master card ----
    "master": {"fa": "مستر", "en": "MASTER"},
    "slave": {"fa": "استیو", "en": "SLAVE"},
    "unassigned": {"fa": "بدون نقش", "en": "UNASSIGNED"},
    "balance": {"fa": "بالانس", "en": "Balance"},
    "equity": {"fa": "اکوییتی", "en": "Equity"},
    "free_margin": {"fa": "مارجین آزاد", "en": "Free Margin"},
    "used_margin": {"fa": "مارجین مصرفی", "en": "Used Margin"},
    "margin_level": {"fa": "سطح مارجین", "en": "Margin Level"},
    "floating_pl": {"fa": "سود/زیان شناور", "en": "Floating P/L"},
    "leverage": {"fa": "لوریج", "en": "Leverage"},
    "open_positions": {"fa": "پوزیشن باز", "en": "Open Positions"},
    "algo_trading": {"fa": "AutoTrading", "en": "AutoTrading"},
    "broker": {"fa": "بروکر/سرور", "en": "Broker/Server"},

    # ---- slave table ----
    "slaves": {"fa": "استیوها", "en": "SLAVES"},
    "col_name": {"fa": "نام", "en": "Name"},
    "col_login": {"fa": "لاگین", "en": "Login"},
    "col_server": {"fa": "سرور", "en": "Server"},
    "col_balance": {"fa": "بالانس", "en": "Balance"},
    "col_equity": {"fa": "اکوییتی", "en": "Equity"},
    "col_free_margin": {"fa": "مارجین آزاد", "en": "Free Margin"},
    "col_margin": {"fa": "مارجین", "en": "Margin"},
    "col_margin_level": {"fa": "سطح مارجین", "en": "Margin Level"},
    "col_pl": {"fa": "سود/زیان", "en": "P/L"},
    "col_currency": {"fa": "ارز", "en": "Currency"},
    "col_positions": {"fa": "پوزیشن", "en": "Positions"},
    "col_connection": {"fa": "اتصال", "en": "Connection"},
    "col_copy": {"fa": "کپی", "en": "Copy"},
    "col_copied_count": {"fa": "کپی‌شده", "en": "Copied"},
    "col_errors": {"fa": "خطاها", "en": "Errors"},
    "col_updated": {"fa": "به‌روزرسانی", "en": "Updated"},
    "col_latency": {"fa": "تأخیر", "en": "Latency"},
    "col_actions": {"fa": "عملیات", "en": "Actions"},
    "enable": {"fa": "فعال", "en": "Enable"},
    "disable": {"fa": "غیرفعال", "en": "Disable"},
    "settings": {"fa": "تنظیمات", "en": "Settings"},
    "reconnect": {"fa": "اتصال مجدد", "en": "Reconnect"},
    "set_master": {"fa": "تبدیل به مستر", "en": "Set as Master"},
    "set_slave": {"fa": "تبدیل به استیو", "en": "Set as Slave"},
    "remove": {"fa": "حذف", "en": "Remove"},
    "confirm_set_master": {
        "fa": "کپی متوقف و این حساب به‌عنوان MASTER تنظیم شود؟",
        "en": "Stop copying and set this account as MASTER?"},
    "confirm_remove_terminal": {
        "fa": "این ترمینال از برنامه حذف شود؟",
        "en": "Remove this terminal from the app?"},

    # ---- positions table ----
    "live_positions": {"fa": "معاملات باز (همه حساب‌ها)", "en": "Live Positions (All Accounts)"},
    "col_account": {"fa": "حساب", "en": "Account"},
    "col_role": {"fa": "نقش", "en": "Role"},
    "col_symbol": {"fa": "نماد", "en": "Symbol"},
    "col_ticket": {"fa": "شناسه", "en": "Position ID"},
    "col_type": {"fa": "نوع", "en": "Type"},
    "col_volume": {"fa": "حجم", "en": "Volume"},
    "col_open_price": {"fa": "قیمت ورود", "en": "Open Price"},
    "col_current_price": {"fa": "قیمت فعلی", "en": "Current Price"},
    "col_sl": {"fa": "SL", "en": "SL"},
    "col_tp": {"fa": "TP", "en": "TP"},
    "col_profit": {"fa": "سود/زیان", "en": "Floating P/L"},
    "col_swap": {"fa": "سواپ", "en": "Swap"},
    "col_copy_status": {"fa": "وضعیت کپی", "en": "Copy Status"},
    "col_master_ref": {"fa": "مستر مرجع", "en": "Master Ref"},
    "filter_account": {"fa": "فیلتر حساب:", "en": "Filter account:"},
    "all": {"fa": "همه", "en": "All"},
    "copied_status": {"fa": "کپی‌شده", "en": "COPIED"},
    "manual_status": {"fa": "دستی", "en": "MANUAL"},

    # ---- activity ----
    "live_activity": {"fa": "رویدادهای زنده کپی", "en": "Live Copy Activity"},
    "alerts": {"fa": "هشدارها", "en": "Alerts"},
    "dismiss_alerts": {"fa": "پاک کردن هشدارها", "en": "Dismiss Alerts"},

    # ---- dialogs ----
    "add_terminal": {"fa": "افزودن ترمینال MT5", "en": "Add MT5 Terminal"},
    "terminal_name": {"fa": "نام اختصاصی", "en": "Custom Name"},
    "terminal_path": {"fa": "مسیر terminal64.exe", "en": "terminal64.exe Path"},
    "login": {"fa": "شماره لاگین", "en": "Login"},
    "server": {"fa": "سرور", "en": "Server"},
    "password_optional": {"fa": "رمز (اختیاری — بدون ذخیره‌سازی از Session ترمینال استفاده می‌شود)",
                          "en": "Password (optional — terminal session used if empty)"},
    "browse": {"fa": "انتخاب فایل…", "en": "Browse…"},
    "scan_terminals": {"fa": "جست‌وجوی ترمینال‌های نصب‌شده", "en": "Scan installed terminals"},
    "save": {"fa": "ذخیره", "en": "Save"},
    "cancel": {"fa": "انصراف", "en": "Cancel"},
    "slave_settings": {"fa": "تنظیمات استیو", "en": "Slave Settings"},
    "grp_copy": {"fa": "کپی", "en": "Copy"},
    "grp_volume": {"fa": "حجم", "en": "Volume"},
    "grp_sltp": {"fa": "حد ضرر / حد سود", "en": "SL / TP"},
    "grp_risk": {"fa": "ریسک", "en": "Risk"},
    "grp_symbols": {"fa": "نمادها", "en": "Symbols"},
    "copy_enabled": {"fa": "کپی فعال", "en": "Copy enabled"},
    "lot_mode": {"fa": "روش حجم", "en": "Lot mode"},
    "lot_multiplier": {"fa": "ضریب حجم", "en": "Lot multiplier"},
    "fixed_lot": {"fa": "حجم ثابت", "en": "Fixed lot"},
    "balance_ratio": {"fa": "نسبت بالانس", "en": "Balance ratio"},
    "equity_ratio": {"fa": "نسبت اکوییتی", "en": "Equity ratio"},
    "max_lot": {"fa": "حداکثر حجم هر معامله", "en": "Max lot per trade"},
    "max_positions": {"fa": "حداکثر تعداد پوزیشن", "en": "Max positions"},
    "max_total_volume": {"fa": "حداکثر حجم کل باز", "en": "Max total open volume"},
    "max_slippage": {"fa": "حداکثر لغزش (پوینت)", "en": "Max slippage (points)"},
    "max_spread": {"fa": "حداکثر اسپرد (پوینت)", "en": "Max spread (points)"},
    "min_free_margin": {"fa": "حداقل مارجین آزاد", "en": "Min free margin"},
    "min_margin_level": {"fa": "حداقل سطح مارجین %", "en": "Min margin level %"},
    "stop_if_equity_below": {"fa": "توقف کپی اگر اکوییتی کمتر از", "en": "Stop copy if equity below"},
    "copy_sl": {"fa": "کپی SL", "en": "Copy SL"},
    "copy_tp": {"fa": "کپی TP", "en": "Copy TP"},
    "sltp_mode": {"fa": "روش انتقال SL/TP", "en": "SL/TP transfer mode"},
    "sltp_absolute": {"fa": "سطح قیمت مطلق", "en": "Absolute price level"},
    "sltp_distance": {"fa": "فاصله از قیمت ورود", "en": "Distance from entry"},
    "allow_stops_adjust": {"fa": "اجازه اصلاح SL/TP برای حد مجاز بروکر",
                           "en": "Allow SL/TP adjust to broker stop level"},
    "copy_partial": {"fa": "کپی بستن بخشی", "en": "Copy partial close"},
    "copy_pending": {"fa": "کپی سفارش‌های معلق", "en": "Copy pending orders"},
    "pending_price_mode": {"fa": "روش قیمت سفارش معلق", "en": "Pending price mode"},
    "allowed_symbols": {"fa": "نمادهای مجاز (با کاما، خالی = همه)", "en": "Allowed symbols (comma sep, empty = all)"},
    "allowed_directions": {"fa": "جهت‌های مجاز", "en": "Allowed directions"},
    "auto_reconnect": {"fa": "اتصال مجدد خودکار", "en": "Auto reconnect"},
    "symbol_mapping": {"fa": "نگاشت نمادها", "en": "Symbol Mapping"},
    "map_master_symbol": {"fa": "نماد مستر", "en": "Master symbol"},
    "map_slave_symbol": {"fa": "نماد استیو", "en": "Slave symbol"},
    "map_status": {"fa": "وضعیت", "en": "Status"},
    "map_note": {"fa": "توضیح", "en": "Note"},
    "map_add": {"fa": "افزودن/ویرایش نگاشت", "en": "Add / Edit mapping"},
    "app_settings": {"fa": "تنظیمات برنامه", "en": "App Settings"},
    "poll_master_ms": {"fa": "بازه پولینگ مستر (ms)", "en": "Master poll interval (ms)"},
    "poll_slave_ms": {"fa": "بازه پولینگ استیو (ms)", "en": "Slave poll interval (ms)"},
    "deal_window_sec": {"fa": "پنجره تاریخچه deals (ثانیه)", "en": "History deals window (s)"},
    "precheck_margin": {"fa": "بررسی مارجین قبل از ارسال (order_check)",
                        "en": "Margin pre-check before sending (order_check)"},
    "export_logs": {"fa": "خروجی لاگ (CSV)", "en": "Export logs (CSV)"},
    "add": {"fa": "افزودن", "en": "Add"},
    "view_positions": {"fa": "پوزیشن‌ها", "en": "Positions"},
    "ok": {"fa": "تأیید", "en": "OK"},
    "error": {"fa": "خطا", "en": "Error"},
    "connected_on": {"fa": "متصل", "en": "CONNECTED"},
    "connected_off": {"fa": "قطع", "en": "OFFLINE"},
    "copy_on": {"fa": "فعال", "en": "ON"},
    "copy_off": {"fa": "خاموش", "en": "OFF"},
    "blocked_warn": {"fa": "مسدود (تغییر حساب)", "en": "BLOCKED (account changed)"},
}


def tr(key: str) -> str:
    item = _STRINGS.get(key)
    if not item:
        return key
    return item.get(LANG) or item["en"] or key


def set_lang(lang: str) -> None:
    global LANG
    LANG = "fa" if lang == "fa" else "en"
