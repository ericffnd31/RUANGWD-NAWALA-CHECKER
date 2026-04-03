#!/usr/bin/env python3
"""Nawala Domain Checker Bot"""

import logging
from datetime import datetime
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import Database
from nawala_checker import NawalaChecker, extract_domain
from config import BOT_TOKEN, DEFAULT_INTERVAL_MINUTES

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

db = Database()
checker = NawalaChecker()
scheduler = AsyncIOScheduler()
auto_check_job = None
DOMAINS_PER_PAGE = 10


# ── FORMAT HELPER ──────────────────────────────────────────────────────────────

def status_icon(blocked) -> str:
    if blocked is None: return "⚪"
    return "🔴" if blocked else "🟢"

def status_label(blocked) -> str:
    if blocked is None: return "BELUM CEK"
    return "BLOCK" if blocked else "AMAN"

def esc(text: str) -> str:
    """Escape MarkdownV2 special chars."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def get_site_name() -> str:
    return db.get_settings().get("site_name", "Default Site")

def page_keyboard(page: int, total: int, cmd: str):
    if total <= 1: return None
    btns = []
    if page > 1:  btns.append(InlineKeyboardButton("◀ Prev", callback_data=f"{cmd}:{page-1}"))
    if page < total: btns.append(InlineKeyboardButton("Next ▶", callback_data=f"{cmd}:{page+1}"))
    return InlineKeyboardMarkup([btns]) if btns else None

def build_list_page(domains: list, page: int, site_name: str) -> str:
    """
    domains: list of (id, domain_name, full_url, is_blocked, checked_at)
    """
    total_pages = max(1, (len(domains) + DOMAINS_PER_PAGE - 1) // DOMAINS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * DOMAINS_PER_PAGE
    chunk = domains[start: start + DOMAINS_PER_PAGE]

    total = len(domains)
    aman  = sum(1 for _,_,_,b,_ in domains if b == 0)
    block = sum(1 for _,_,_,b,_ in domains if b == 1)
    belum = sum(1 for _,_,_,b,_ in domains if b is None)

    msg  = f"🎯 *DATA DOMAIN LIST*\n"
    msg += f"`{'━'*30}`\n"
    msg += f"Site: `{esc(site_name)}`\n"
    msg += f"Halaman `{page}/{total_pages}`\n\n"
    msg += f"`{'─'*10} RINGKASAN {'─'*10}`\n"
    msg += f"📊 Total      : `{total}`\n"
    msg += f"🟢 Aman       : `{aman}`\n"
    msg += f"🔴 Block      : `{block}`\n"
    msg += f"⚪ Belum Cek  : `{belum}`\n\n"

    for i, (_, domain_name, full_url, blocked, checked) in enumerate(chunk):
        no = start + i + 1
        display = full_url if full_url else domain_name
        msg += f"{status_icon(blocked)} *DOMAIN \\#{no}*\n"
        msg += f"├ Link    : `{esc(display)}`\n"
        msg += f"├ Domain  : `{esc(domain_name)}`\n"
        msg += f"├ Status  : `{status_label(blocked)}`\n"
        msg += f"└ Checked : `{esc(checked or '—')}`\n\n"

    return msg

def build_checkall_pages(results: list, site_name: str) -> list:
    """results: [(domain_name, full_url, blocked, checked_at)]"""
    total = len(results)
    aman  = sum(1 for _,_,b,_ in results if not b)
    block = sum(1 for _,_,b,_ in results if b)
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_pages = max(1, (total + DOMAINS_PER_PAGE - 1) // DOMAINS_PER_PAGE)
    pages = []

    for page in range(1, total_pages + 1):
        start = (page - 1) * DOMAINS_PER_PAGE
        chunk = results[start: start + DOMAINS_PER_PAGE]

        msg  = f"🎯 *HASIL CEK DOMAIN*\n"
        msg += f"`{'━'*30}`\n"
        msg += f"Site: `{esc(site_name)}`\n"
        msg += f"Halaman `{page}/{total_pages}`\n\n"
        msg += f"`{'─'*10} RINGKASAN {'─'*10}`\n"
        msg += f"📊 Total      : `{total}`\n"
        msg += f"🟢 Aman       : `{aman}`\n"
        msg += f"🔴 Block      : `{block}`\n"
        msg += f"🕐 Waktu      : `{esc(now)}`\n\n"

        for i, (domain_name, full_url, blocked, checked) in enumerate(chunk):
            no = start + i + 1
            display = full_url if full_url else domain_name
            msg += f"{status_icon(blocked)} *DOMAIN \\#{no}*\n"
            msg += f"├ Link    : `{esc(display)}`\n"
            msg += f"├ Domain  : `{esc(domain_name)}`\n"
            msg += f"├ Status  : `{status_label(blocked)}`\n"
            msg += f"└ Checked : `{esc(checked or now)}`\n\n"

        pages.append(msg)

    return pages

def build_change_alert(changed: list, site_name: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg  = f"⚠️ *PERUBAHAN STATUS DOMAIN*\n"
    msg += f"`{'━'*30}`\n"
    msg += f"Site: `{esc(site_name)}`\n"
    msg += f"🕐 `{esc(now)}`\n\n"
    for name, full_url, was, now_b in changed:
        display = full_url if full_url else name
        msg += f"🔄 `{esc(display)}`\n"
        msg += f"├ Sebelum  : {status_icon(was)} `{status_label(was)}`\n"
        msg += f"└ Sekarang : {status_icon(now_b)} `{status_label(now_b)}`\n\n"
    return msg


# ── AUTO CHECK ────────────────────────────────────────────────────────────────

async def run_auto_check(application: Application):
    domains = db.get_all_domains()
    if not domains: return

    settings = db.get_settings()
    chat_id = settings.get("chat_id")
    if not chat_id or not settings.get("alerts_active", True): return

    changed = []
    for did, dname, full_url, prev_blocked, _ in domains:
        blocked = await checker.check(dname)
        db.update_domain_status(did, blocked)
        prev = bool(prev_blocked) if prev_blocked is not None else None
        if prev is not None and prev != blocked:
            changed.append((dname, full_url, prev, blocked))

    if changed:
        msg = build_change_alert(changed, get_site_name())
        try:
            await application.bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Gagal kirim notifikasi: {e}")

    logger.info(f"[AUTO CHECK] Selesai. {len(changed)} domain berubah status.")

def schedule_auto_check(application: Application, interval_minutes: int):
    global auto_check_job
    if auto_check_job:
        try: auto_check_job.remove()
        except: pass
    auto_check_job = scheduler.add_job(
        run_auto_check,
        trigger=IntervalTrigger(minutes=interval_minutes),
        args=[application], id="auto_check", replace_existing=True,
    )
    db.save_setting("alerts_active", True)
    logger.info(f"Auto check setiap {interval_minutes} menit.")


# ── COMMANDS ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.save_chat_id(update.effective_chat.id)
    await update.message.reply_text(
        "👋 *Selamat datang di Nawala Domain Checker Bot\\!*\n\n"
        "Ketik /help untuk panduan penggunaan\\.",
        parse_mode="MarkdownV2"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0] in ["-hh", "--h"]:
        await update.message.reply_text(
            "📋 *Daftar Perintah yang Tersedia*\n\n"
            "*🔹 Domain:*\n"
            "`/domain add <link>` — Tambah link/domain\n"
            "  _Contoh: /domain add mez\\.ink/ruangwd_\n\n"
            "`/domain delete <domain>` — Hapus domain\n"
            "`/domain update <lama> <baru>` — Ubah domain\n"
            "`/domain list` — Tampilkan daftar domain\n"
            "`/domain interval <menit>` — Atur interval\n"
            "`/domain stop` — Hentikan semua alert\n"
            "`/domain setsite <nama>` — Set nama site\n\n"
            "*🔹 Manual:*\n"
            "`/check <link>` — Cek satu link/domain\n"
            "`/checkall` — Cek semua domain\n\n"
            "*🔹 Lainnya:*\n"
            "`/status` — Status bot\n"
            "`/start` — Daftarkan chat\n",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Cara pakai:* `command [arguments] [options]`\n\n"
        "*Options:*\n"
        "• `-h, --help` Display help for the command\n"
        "• `-hh, --h` Daftar Perintah yang tersedia\n\n"
        "*Contoh Cepat:*\n"
        "`/domain add mez.ink/ruangwd`\n"
        "`/domain add heylink.me/RUANGWD`\n"
        "`/domain list`\n"
        "`/check mez.ink/ruangwd`\n\n"
        "Ketik `/help -hh` untuk daftar perintah lengkap.",
        parse_mode="Markdown"
    )

async def cmd_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Sub-command diperlukan. Lihat `/help -hh`", parse_mode="Markdown")
        return

    sub = args[0].lower()

    # ── ADD ──
    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Gunakan: `/domain add <link>`\nContoh: `/domain add mez.ink/ruangwd`",
                parse_mode="Markdown"
            )
            return

        full_url = args[1].strip().replace("https://", "").replace("http://", "").rstrip("/")
        domain_name = extract_domain(full_url)

        if db.domain_exists(domain_name):
            await update.message.reply_text(f"⚠️ Domain `{domain_name}` sudah ada.", parse_mode="Markdown")
            return

        db.add_domain(domain_name, full_url)
        tmp = await update.message.reply_text(f"⏳ Mengecek `{esc(full_url)}`\\.\\.\\.", parse_mode="MarkdownV2")
        blocked = await checker.check(domain_name)
        db.update_domain_status_by_name(domain_name, blocked)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        await tmp.edit_text(
            f"✅ *Domain ditambahkan\\!*\n\n"
            f"{status_icon(blocked)} *DOMAIN BARU*\n"
            f"├ Link    : `{esc(full_url)}`\n"
            f"├ Domain  : `{esc(domain_name)}`\n"
            f"├ Status  : `{status_label(blocked)}`\n"
            f"└ Checked : `{esc(now)}`",
            parse_mode="MarkdownV2"
        )

    # ── DELETE ──
    elif sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("❌ Gunakan: `/domain delete <domain>`", parse_mode="Markdown")
            return
        raw = args[1].strip()
        domain_name = extract_domain(raw)
        if not db.domain_exists(domain_name):
            await update.message.reply_text(f"❌ Domain `{domain_name}` tidak ditemukan.", parse_mode="Markdown")
            return
        db.delete_domain(domain_name)
        await update.message.reply_text(f"🗑️ Domain `{domain_name}` dihapus.", parse_mode="Markdown")

    # ── UPDATE ──
    elif sub == "update":
        if len(args) < 3:
            await update.message.reply_text("❌ Gunakan: `/domain update <link_lama> <link_baru>`", parse_mode="Markdown")
            return
        old_url = args[1].strip()
        new_url = args[2].strip().replace("https://","").replace("http://","").rstrip("/")
        old_domain = extract_domain(old_url)
        new_domain = extract_domain(new_url)
        if not db.domain_exists(old_domain):
            await update.message.reply_text(f"❌ `{old_domain}` tidak ditemukan.", parse_mode="Markdown")
            return
        if db.domain_exists(new_domain):
            await update.message.reply_text(f"⚠️ `{new_domain}` sudah ada.", parse_mode="Markdown")
            return
        db.update_domain_name(old_domain, new_domain, new_url)
        await update.message.reply_text(f"✏️ `{old_url}` → `{new_url}`", parse_mode="Markdown")

    # ── LIST ──
    elif sub == "list":
        domains = db.get_all_domains()
        if not domains:
            await update.message.reply_text("📭 Belum ada domain. Gunakan `/domain add <link>`", parse_mode="Markdown")
            return
        site = get_site_name()
        total_pages = max(1, (len(domains) + DOMAINS_PER_PAGE - 1) // DOMAINS_PER_PAGE)
        text = build_list_page(domains, 1, site)
        kb = page_keyboard(1, total_pages, "list")
        await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=kb)

    # ── INTERVAL ──
    elif sub == "interval":
        if len(args) < 2:
            await update.message.reply_text("❌ Gunakan: `/domain interval <menit>`", parse_mode="Markdown")
            return
        try:
            minutes = int(args[1])
            assert minutes > 0
        except:
            await update.message.reply_text("❌ Masukkan angka menit yang valid.", parse_mode="Markdown")
            return
        db.save_setting("interval_minutes", minutes)
        schedule_auto_check(context.application, minutes)
        await update.message.reply_text(
            f"⏱️ Interval diubah ke *{minutes} menit*\\. Auto check aktif\\!",
            parse_mode="MarkdownV2"
        )

    # ── STOP ──
    elif sub == "stop":
        db.save_setting("alerts_active", False)
        if auto_check_job:
            try: auto_check_job.pause()
            except: pass
        await update.message.reply_text(
            "🔕 Semua alert *dihentikan*\\.\n"
            "Gunakan `/domain interval <menit>` untuk aktifkan kembali\\.",
            parse_mode="MarkdownV2"
        )

    # ── SETSITE ──
    elif sub == "setsite":
        if len(args) < 2:
            await update.message.reply_text("❌ Gunakan: `/domain setsite <nama>`", parse_mode="Markdown")
            return
        site = " ".join(args[1:])
        db.save_setting("site_name", site)
        await update.message.reply_text(f"✅ Nama site: `{site}`", parse_mode="Markdown")

    else:
        await update.message.reply_text(f"❓ Sub-command `{sub}` tidak dikenal.", parse_mode="Markdown")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Gunakan: `/check <link>`\nContoh: `/check mez.ink/ruangwd`",
            parse_mode="Markdown"
        )
        return
    full_url = context.args[0].strip().replace("https://","").replace("http://","").rstrip("/")
    domain_name = extract_domain(full_url)

    tmp = await update.message.reply_text(f"⏳ Mengecek `{esc(full_url)}`\\.\\.\\.", parse_mode="MarkdownV2")
    blocked = await checker.check(domain_name)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if db.domain_exists(domain_name):
        db.update_domain_status_by_name(domain_name, blocked)

    await tmp.edit_text(
        f"🔍 *HASIL CEK MANUAL*\n"
        f"`{'━'*30}`\n"
        f"{status_icon(blocked)} *DOMAIN*\n"
        f"├ Link    : `{esc(full_url)}`\n"
        f"├ Domain  : `{esc(domain_name)}`\n"
        f"├ Status  : `{status_label(blocked)}`\n"
        f"└ Checked : `{esc(now)}`",
        parse_mode="MarkdownV2"
    )


async def cmd_checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domains = db.get_all_domains()
    if not domains:
        await update.message.reply_text("📭 Belum ada domain. Gunakan `/domain add <link>`", parse_mode="Markdown")
        return
    tmp = await update.message.reply_text(f"⏳ Mengecek {len(domains)} domain\\.\\.\\.", parse_mode="MarkdownV2")
    results = []
    for did, dname, full_url, _, _ in domains:
        blocked = await checker.check(dname)
        db.update_domain_status(did, blocked)
        results.append((dname, full_url, blocked, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    site = get_site_name()
    pages = build_checkall_pages(results, site)
    total_pages = len(pages)
    kb = page_keyboard(1, total_pages, "checkall")
    await tmp.edit_text(pages[0], parse_mode="MarkdownV2", reply_markup=kb)
    for i, pt in enumerate(pages[1:], 2):
        kb = page_keyboard(i, total_pages, "checkall")
        await update.message.reply_text(pt, parse_mode="MarkdownV2", reply_markup=kb)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.get_settings()
    job = scheduler.get_job("auto_check")
    next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job and job.next_run_time else "—"
    alert_str = "✅ Aktif" if s.get("alerts_active", True) else "🔕 Nonaktif"
    await update.message.reply_text(
        f"🤖 *STATUS BOT NAWALA CHECKER*\n"
        f"`{'━'*30}`\n"
        f"📋 Domain     : `{db.get_domain_count()}`\n"
        f"🌐 Site name  : `{esc(s.get('site_name','—'))}`\n"
        f"⏱️  Interval   : `{s.get('interval_minutes', DEFAULT_INTERVAL_MINUTES)} menit`\n"
        f"🔔 Alert      : {alert_str}\n"
        f"⏰ Cek berikutnya : `{esc(next_run)}`",
        parse_mode="MarkdownV2"
    )


# ── CALLBACK PAGINATION ───────────────────────────────────────────────────────

async def cb_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 2: return
    cmd, page_str = parts
    try: page = int(page_str)
    except: return

    site = get_site_name()

    if cmd == "list":
        domains = db.get_all_domains()
        if not domains: return
        total_pages = max(1, (len(domains) + DOMAINS_PER_PAGE - 1) // DOMAINS_PER_PAGE)
        text = build_list_page(domains, page, site)
        kb = page_keyboard(page, total_pages, "list")
        await query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=kb)

    elif cmd == "checkall":
        domains = db.get_all_domains()
        results = [(d[1], d[2], bool(d[3]) if d[3] is not None else False, d[4] or "—") for d in domains]
        pages = build_checkall_pages(results, site)
        if not (1 <= page <= len(pages)): return
        kb = page_keyboard(page, len(pages), "checkall")
        await query.edit_message_text(pages[page-1], parse_mode="MarkdownV2", reply_markup=kb)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}", exc_info=context.error)


# ── MAIN ──────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start",    "Mulai bot"),
        BotCommand("help",     "Panduan penggunaan"),
        BotCommand("domain",   "Kelola domain"),
        BotCommand("check",    "Cek satu link manual"),
        BotCommand("checkall", "Cek semua domain sekarang"),
        BotCommand("status",   "Status bot & pengaturan"),
    ])
    s = db.get_settings()
    if not scheduler.running: scheduler.start()
    if s.get("alerts_active", True):
        schedule_auto_check(application, s.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("domain",   cmd_domain))
    app.add_handler(CommandHandler("check",    cmd_check))
    app.add_handler(CommandHandler("checkall", cmd_checkall))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CallbackQueryHandler(cb_pagination))
    app.add_handler(MessageHandler(filters.Document.TXT & filters.CaptionRegex(r"^/domain import"), cmd_domain_import))
    app.add_error_handler(error_handler)
    logger.info("🚀 Bot Nawala Checker dimulai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()


# ── IMPORT FILE HANDLER ───────────────────────────────────────────────────────
# Tambahkan ini di bawah semua handler yang ada

async def cmd_domain_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler untuk import domain dari file .txt yang dikirim ke chat.
    Cara pakai: kirim file .txt ke grup, caption: /domain import
    """
    from nawala_checker import extract_domain

    # Cek apakah ada file yang dikirim bersama command
    msg = update.message
    doc = msg.document if msg else None

    if not doc:
        await update.message.reply_text(
            "📥 *Cara Import Domain dari File:*\n\n"
            "1\\. Siapkan file `.txt` berisi daftar link, satu per baris\n"
            "2\\. Kirim file tersebut ke grup ini\n"
            "3\\. Di kolom *caption*, ketik: `/domain import`\n\n"
            "Contoh isi file:\n"
            "`ruangwd88\\.com`\n"
            "`mez\\.ink/ruangwd`\n"
            "`heylink\\.me/RUANGWD`",
            parse_mode="MarkdownV2"
        )
        return

    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("❌ Hanya file `.txt` yang didukung.", parse_mode="Markdown")
        return

    tmp = await update.message.reply_text("⏳ Membaca file dan mengimport domain\\.\\.\\.", parse_mode="MarkdownV2")

    # Download file
    file = await doc.get_file()
    content_bytes = await file.download_as_bytearray()
    content = content_bytes.decode("utf-8", errors="ignore")

    # Parse
    added = []
    skipped = []
    errors = []

    for line in content.splitlines():
        url = line.strip().replace("\r", "")
        if not url or url.startswith("#"):
            continue
        full_url = url.replace("https://", "").replace("http://", "").rstrip("/")
        domain_name = extract_domain(full_url)
        if not domain_name:
            errors.append(url)
            continue
        if db.domain_exists(domain_name):
            skipped.append(full_url)
            continue
        db.add_domain(domain_name, full_url)
        added.append((domain_name, full_url))

    total = db.get_domain_count()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report  = f"📥 *HASIL IMPORT DOMAIN*\n"
    report += f"`{'━'*30}`\n"
    report += f"🕐 `{esc(now)}`\n\n"
    report += f"✅ Ditambahkan : `{len(added)}`\n"
    report += f"⏭️  Sudah ada   : `{len(skipped)}`\n"
    report += f"❌ Error       : `{len(errors)}`\n"
    report += f"📋 Total DB    : `{total}`\n\n"

    if added:
        report += f"*Domain baru ditambahkan:*\n"
        for _, full_url in added[:20]:  # tampilkan maks 20
            report += f"• `{esc(full_url)}`\n"
        if len(added) > 20:
            report += f"_\\.\\.\\. dan {len(added)-20} lainnya_\n"

    report += f"\n💡 Gunakan `/checkall` untuk langsung cek semua domain\\."

    await tmp.edit_text(report, parse_mode="MarkdownV2")
