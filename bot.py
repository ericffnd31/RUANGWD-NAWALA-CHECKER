#!/usr/bin/env python3
"""Nawala Domain Checker Bot — Final Clean Version"""

import logging
from datetime import datetime

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
from nawala_checker import NawalaChecker, extract_domain, is_ip_address
from config import BOT_TOKEN, DEFAULT_INTERVAL_MINUTES

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

checker       = NawalaChecker()
scheduler     = AsyncIOScheduler()
auto_check_job = None
PER_PAGE      = 10


# ── HELPERS ───────────────────────────────────────────────────────────────────

def esc(t: str) -> str:
    """Escape MarkdownV2."""
    for c in r"_*[]()~`>#+-=|{}.!":
        t = t.replace(c, f"\\{c}")
    return t

def s_icon(blocked) -> str:
    return "⚪" if blocked is None else ("🔴" if blocked else "🟢")

def s_label(blocked) -> str:
    return "BELUM CEK" if blocked is None else ("BLOCK" if blocked else "AMAN")

def t_label(domain_name: str) -> str:
    return "IP ADDR" if is_ip_address(domain_name) else "DOMAIN"

def site_name() -> str:
    return db.get_settings().get("site_name", "Default Site")

def nav_kb(page: int, total: int, cmd: str):
    if total <= 1: return None
    btns = []
    if page > 1:     btns.append(InlineKeyboardButton("◀ Prev", callback_data=f"{cmd}:{page-1}"))
    if page < total: btns.append(InlineKeyboardButton("Next ▶", callback_data=f"{cmd}:{page+1}"))
    return InlineKeyboardMarkup([btns]) if btns else None

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── MESSAGE BUILDERS ──────────────────────────────────────────────────────────

def msg_list(domains: list, page: int) -> str:
    sn = site_name()
    total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
    page    = max(1, min(page, total_p))
    start   = (page - 1) * PER_PAGE
    chunk   = domains[start: start + PER_PAGE]

    aman  = sum(1 for _,_,_,b,_ in domains if b == 0)
    block = sum(1 for _,_,_,b,_ in domains if b == 1)
    belum = sum(1 for _,_,_,b,_ in domains if b is None)

    m  = "🎯 *DATA DOMAIN LIST*\n"
    m += f"`{'━'*30}`\n"
    m += f"Site: `{esc(sn)}`\n"
    m += f"Halaman `{page}/{total_p}`\n\n"
    m += f"`{'─'*10} RINGKASAN {'─'*10}`\n"
    m += f"📊 Total      : `{len(domains)}`\n"
    m += f"🟢 Aman       : `{aman}`\n"
    m += f"🔴 Block      : `{block}`\n"
    m += f"⚪ Belum Cek  : `{belum}`\n\n"

    for i, (_, dname, furl, blocked, checked) in enumerate(chunk):
        no      = start + i + 1
        display = furl if furl else dname
        m += f"{s_icon(blocked)} *{esc(t_label(dname))} \\#{no}*\n"
        m += f"├ Link    : `{esc(display)}`\n"
        m += f"├ Status  : `{s_label(blocked)}`\n"
        m += f"└ Checked : `{esc(checked or '—')}`\n\n"
    return m


def msg_checkall_pages(results: list) -> list:
    """results: [(domain_name, full_url, blocked, checked_at)]"""
    sn      = site_name()
    total   = len(results)
    aman    = sum(1 for _,_,b,_ in results if not b)
    block   = sum(1 for _,_,b,_ in results if b)
    now     = now_str()
    total_p = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    pages   = []

    for pg in range(1, total_p + 1):
        start = (pg - 1) * PER_PAGE
        chunk = results[start: start + PER_PAGE]

        m  = "🎯 *HASIL CEK DOMAIN*\n"
        m += f"`{'━'*30}`\n"
        m += f"Site: `{esc(sn)}`\n"
        m += f"Halaman `{pg}/{total_p}`\n\n"
        m += f"`{'─'*10} RINGKASAN {'─'*10}`\n"
        m += f"📊 Total      : `{total}`\n"
        m += f"🟢 Aman       : `{aman}`\n"
        m += f"🔴 Block      : `{block}`\n"
        m += f"🕐 Waktu      : `{esc(now)}`\n\n"

        for i, (dname, furl, blocked, checked) in enumerate(chunk):
            no      = start + i + 1
            display = furl if furl else dname
            m += f"{s_icon(blocked)} *{esc(t_label(dname))} \\#{no}*\n"
            m += f"├ Link    : `{esc(display)}`\n"
            m += f"├ Status  : `{s_label(blocked)}`\n"
            m += f"└ Checked : `{esc(checked or now)}`\n\n"
        pages.append(m)
    return pages


def msg_alert(changed: list) -> str:
    sn = site_name()
    m  = "⚠️ *PERUBAHAN STATUS DOMAIN*\n"
    m += f"`{'━'*30}`\n"
    m += f"Site: `{esc(sn)}`\n"
    m += f"🕐 `{esc(now_str())}`\n\n"
    for dname, furl, was, now_b in changed:
        display = furl if furl else dname
        m += f"🔄 `{esc(display)}`\n"
        m += f"├ Sebelum  : {s_icon(was)} `{s_label(was)}`\n"
        m += f"└ Sekarang : {s_icon(now_b)} `{s_label(now_b)}`\n\n"
    return m


# ── AUTO CHECK ────────────────────────────────────────────────────────────────

async def run_auto_check(application: Application):
    domains = db.get_all_domains()
    if not domains: return

    s       = db.get_settings()
    chat_id = s.get("chat_id")
    if not chat_id or not s.get("alerts_active", True): return

    changed = []
    for did, dname, furl, prev, _ in domains:
        blocked = await checker.check(dname)
        db.update_status_by_id(did, blocked)
        p = bool(prev) if prev is not None else None
        if p is not None and p != blocked:
            changed.append((dname, furl, p, blocked))

    if changed:
        try:
            await application.bot.send_message(
                chat_id=chat_id, text=msg_alert(changed), parse_mode="MarkdownV2"
            )
        except Exception as e:
            logger.error(f"Alert error: {e}")
    logger.info(f"Auto check selesai — {len(changed)} berubah.")


def schedule_check(application: Application, minutes: int):
    global auto_check_job
    if auto_check_job:
        try: auto_check_job.remove()
        except: pass
    auto_check_job = scheduler.add_job(
        run_auto_check,
        trigger=IntervalTrigger(minutes=minutes),
        args=[application], id="auto_check", replace_existing=True,
    )
    db.save_setting("alerts_active", True)
    logger.info(f"Auto check setiap {minutes} menit.")


# ── COMMAND: /start ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.save_chat_id(update.effective_chat.id)
    await update.message.reply_text(
        "👋 *Selamat datang di Nawala Domain Checker Bot\\!*\n\n"
        "Ketik /help untuk panduan penggunaan\\.",
        parse_mode="MarkdownV2"
    )


# ── COMMAND: /help ────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] in ("-hh", "--h"):
        await update.message.reply_text(
            "📋 *Daftar Perintah*\n\n"
            "*Domain & IP:*\n"
            "`/domain add <link>` — tambah 1 link/IP\n"
            "`/domain add <l1> <l2> ...` — tambah banyak sekaligus\n"
            "`/domain delete <domain/IP>` — hapus\n"
            "`/domain update <lama> <baru>` — ubah\n"
            "`/domain list` — daftar semua\n"
            "`/domain interval <menit>` — ubah interval\n"
            "`/domain stop` — hentikan alert\n"
            "`/domain setsite <nama>` — set nama site\n\n"
            "*Cek Manual:*\n"
            "`/check <link/IP>` — cek satu\n"
            "`/checkall` — cek semua\n\n"
            "*Import File:*\n"
            "Kirim file `.txt` + caption `/domain import`\n\n"
            "*Lainnya:*\n"
            "`/status` — status bot\n"
            "`/start` — daftarkan chat grup\n",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "📖 *Panduan Bot*\n\n"
        "`command [arguments] [options]`\n\n"
        "*Options:*\n"
        "• `-h, --help` — bantuan\n"
        "• `-hh, --h` — semua perintah\n\n"
        "*Contoh:*\n"
        "`/domain add mez.ink/ruangwd`\n"
        "`/domain add 146.190.92.3`\n"
        "`/domain list`\n"
        "`/check 146.190.92.3`\n\n"
        "Ketik `/help -hh` untuk daftar lengkap.",
        parse_mode="Markdown"
    )


# ── COMMAND: /domain ──────────────────────────────────────────────────────────

async def cmd_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Sub-command diperlukan. Ketik `/help -hh`", parse_mode="Markdown")
        return

    sub = args[0].lower()

    # ── add ──
    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Contoh:\n`/domain add mez.ink/ruangwd`\n`/domain add link1 link2 link3`",
                parse_mode="Markdown"
            )
            return

        raw_list = args[1:]

        # ─ Single entry → detail ─
        if len(raw_list) == 1:
            furl    = raw_list[0].strip().replace("https://","").replace("http://","").rstrip("/")
            dname   = extract_domain(furl)
            tl      = t_label(dname)

            if db.domain_exists(dname):
                await update.message.reply_text(f"⚠️ `{dname}` sudah ada di daftar.", parse_mode="Markdown")
                return

            db.add_domain(dname, furl)
            tmp = await update.message.reply_text(
                f"⏳ Menyimpan dan mengecek `{esc(furl)}`\\.\\.\\.", parse_mode="MarkdownV2"
            )

            blocked = await checker.check(dname)
            db.update_status_by_name(dname, blocked)

            await tmp.edit_text(
                f"✅ *{esc(tl)} berhasil ditambahkan\\!*\n\n"
                f"{s_icon(blocked)} *{esc(tl)} BARU*\n"
                f"├ Link    : `{esc(furl)}`\n"
                f"├ Status  : `{s_label(blocked)}`\n"
                f"└ Checked : `{esc(now_str())}`",
                parse_mode="MarkdownV2"
            )

        # ─ Multiple entries → ringkasan ─
        else:
            tmp = await update.message.reply_text(
                f"⏳ Menyimpan *{len(raw_list)} link*\\.\\.\\.", parse_mode="MarkdownV2"
            )
            added, skipped, errors = [], [], []

            for raw in raw_list:
                raw = raw.strip()
                if not raw: continue
                furl  = raw.replace("https://","").replace("http://","").rstrip("/")
                dname = extract_domain(furl)
                if not dname:
                    errors.append(raw); continue
                if db.domain_exists(dname):
                    skipped.append(furl); continue
                db.add_domain(dname, furl)
                added.append((dname, furl))

            m  = "📥 *HASIL TAMBAH DOMAIN*\n"
            m += f"`{'━'*30}`\n"
            m += f"🕐 `{esc(now_str())}`\n\n"
            m += f"✅ Ditambahkan : `{len(added)}`\n"
            m += f"⏭️  Sudah ada   : `{len(skipped)}`\n"
            m += f"❌ Error       : `{len(errors)}`\n"
            m += f"📋 Total DB    : `{db.get_domain_count()}`\n\n"
            if added:
                m += "*Berhasil disimpan:*\n"
                for dname, furl in added[:20]:
                    icon = "🖥️" if is_ip_address(dname) else "🌐"
                    m += f"{icon} `{esc(furl)}`\n"
                if len(added) > 20:
                    m += f"_\\.\\.\\. dan {len(added)-20} lainnya_\n"
            m += "\n💡 Gunakan `/checkall` untuk cek semua\\."
            await tmp.edit_text(m, parse_mode="MarkdownV2")

    # ── delete ──
    elif sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("❌ `/domain delete <domain/IP>`", parse_mode="Markdown")
            return
        dname = extract_domain(args[1].strip())
        if not db.domain_exists(dname):
            await update.message.reply_text(f"❌ `{dname}` tidak ditemukan.", parse_mode="Markdown")
            return
        db.delete_domain(dname)
        await update.message.reply_text(f"🗑️ `{dname}` berhasil dihapus.", parse_mode="Markdown")

    # ── update ──
    elif sub == "update":
        if len(args) < 3:
            await update.message.reply_text("❌ `/domain update <lama> <baru>`", parse_mode="Markdown")
            return
        old_d = extract_domain(args[1].strip())
        new_u = args[2].strip().replace("https://","").replace("http://","").rstrip("/")
        new_d = extract_domain(new_u)
        if not db.domain_exists(old_d):
            await update.message.reply_text(f"❌ `{old_d}` tidak ditemukan.", parse_mode="Markdown")
            return
        if db.domain_exists(new_d):
            await update.message.reply_text(f"⚠️ `{new_d}` sudah ada.", parse_mode="Markdown")
            return
        db.update_domain_name(old_d, new_d, new_u)
        await update.message.reply_text(f"✏️ `{old_d}` → `{new_d}`", parse_mode="Markdown")

    # ── list ──
    elif sub == "list":
        domains = db.get_all_domains()
        if not domains:
            await update.message.reply_text("📭 Belum ada domain. Gunakan `/domain add <link>`", parse_mode="Markdown")
            return
        total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
        await update.message.reply_text(
            msg_list(domains, 1),
            parse_mode="MarkdownV2",
            reply_markup=nav_kb(1, total_p, "list")
        )

    # ── interval ──
    elif sub == "interval":
        if len(args) < 2:
            await update.message.reply_text("❌ `/domain interval <menit>`", parse_mode="Markdown")
            return
        try:
            minutes = int(args[1])
            assert minutes > 0
        except Exception:
            await update.message.reply_text("❌ Masukkan angka menit yang valid.", parse_mode="Markdown")
            return
        db.save_setting("interval_minutes", minutes)
        schedule_check(context.application, minutes)
        await update.message.reply_text(
            f"⏱️ Interval diubah ke *{minutes} menit*\\. Auto check aktif\\!",
            parse_mode="MarkdownV2"
        )

    # ── stop ──
    elif sub == "stop":
        db.save_setting("alerts_active", False)
        if auto_check_job:
            try: auto_check_job.pause()
            except: pass
        await update.message.reply_text(
            "🔕 Alert *dihentikan*\\.\n"
            "Gunakan `/domain interval <menit>` untuk aktifkan kembali\\.",
            parse_mode="MarkdownV2"
        )

    # ── setsite ──
    elif sub == "setsite":
        if len(args) < 2:
            await update.message.reply_text("❌ `/domain setsite <nama>`", parse_mode="Markdown")
            return
        sn = " ".join(args[1:])
        db.save_setting("site_name", sn)
        await update.message.reply_text(f"✅ Nama site: `{sn}`", parse_mode="Markdown")

    # ── import (teks biasa) ──
    elif sub == "import":
        await update.message.reply_text(
            "📥 *Cara Import:*\n\n"
            "1\\. Siapkan file `.txt` \\(satu link per baris\\)\n"
            "2\\. Kirim file ke grup ini\n"
            "3\\. Di caption ketik: `/domain import`",
            parse_mode="MarkdownV2"
        )

    else:
        await update.message.reply_text(f"❓ Sub-command `{sub}` tidak dikenal\\.", parse_mode="MarkdownV2")


# ── COMMAND: /check ───────────────────────────────────────────────────────────

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Gunakan: `/check <link/IP>`", parse_mode="Markdown")
        return

    raw   = context.args[0].strip().replace("https://","").replace("http://","").rstrip("/")
    dname = extract_domain(raw)
    tl    = t_label(dname)
    metode = "HTTP Request" if is_ip_address(dname) else "DNS Lookup"

    tmp = await update.message.reply_text(
        f"⏳ Mengecek `{esc(raw)}`\\.\\.\\.", parse_mode="MarkdownV2"
    )
    blocked = await checker.check(dname)

    if db.domain_exists(dname):
        db.update_status_by_name(dname, blocked)

    await tmp.edit_text(
        f"🔍 *HASIL CEK MANUAL*\n"
        f"`{'━'*30}`\n"
        f"{s_icon(blocked)} *{esc(tl)}*\n"
        f"├ Link    : `{esc(raw)}`\n"
        f"├ Metode  : `{metode}`\n"
        f"├ Status  : `{s_label(blocked)}`\n"
        f"└ Checked : `{esc(now_str())}`",
        parse_mode="MarkdownV2"
    )


# ── COMMAND: /checkall ────────────────────────────────────────────────────────

async def cmd_checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domains = db.get_all_domains()
    if not domains:
        await update.message.reply_text("📭 Belum ada domain.", parse_mode="Markdown")
        return

    tmp = await update.message.reply_text(
        f"⏳ Mengecek `{len(domains)}` domain \\& IP\\.\\.\\.", parse_mode="MarkdownV2"
    )
    results = []
    for did, dname, furl, _, _ in domains:
        blocked = await checker.check(dname)
        db.update_status_by_id(did, blocked)
        results.append((dname, furl, blocked, now_str()))

    pages   = msg_checkall_pages(results)
    total_p = len(pages)
    await tmp.edit_text(
        pages[0], parse_mode="MarkdownV2", reply_markup=nav_kb(1, total_p, "checkall")
    )
    for i, pt in enumerate(pages[1:], 2):
        await update.message.reply_text(
            pt, parse_mode="MarkdownV2", reply_markup=nav_kb(i, total_p, "checkall")
        )


# ── COMMAND: /status ──────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s   = db.get_settings()
    job = scheduler.get_job("auto_check")
    nxt = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job and job.next_run_time else "—"
    al  = "✅ Aktif" if s.get("alerts_active", True) else "🔕 Nonaktif"

    await update.message.reply_text(
        f"🤖 *STATUS BOT*\n"
        f"`{'━'*30}`\n"
        f"📋 Domain\\+IP : `{db.get_domain_count()}`\n"
        f"🌐 Site       : `{esc(s.get('site_name','—'))}`\n"
        f"⏱️  Interval   : `{s.get('interval_minutes', DEFAULT_INTERVAL_MINUTES)} menit`\n"
        f"🔔 Alert      : {al}\n"
        f"⏰ Cek berikutnya : `{esc(nxt)}`",
        parse_mode="MarkdownV2"
    )


# ── HANDLER: file .txt + caption /domain import ───────────────────────────────

async def cmd_domain_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document if update.message else None
    if not doc:
        await update.message.reply_text("📥 Kirim file `.txt` dengan caption `/domain import`", parse_mode="Markdown")
        return
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Hanya file `.txt` yang didukung.", parse_mode="Markdown")
        return

    tmp = await update.message.reply_text("⏳ Membaca file\\.\\.\\.", parse_mode="MarkdownV2")

    tg_file = await context.bot.get_file(doc.file_id)
    raw_bytes = await tg_file.download_as_bytearray()
    content   = raw_bytes.decode("utf-8", errors="ignore")

    added, skipped, errors = [], [], []

    for line in content.splitlines():
        url = line.strip().replace("\r", "")
        if not url or url.startswith("#"): continue
        furl  = url.replace("https://","").replace("http://","").rstrip("/")
        dname = extract_domain(furl)
        if not dname:
            errors.append(url); continue
        if db.domain_exists(dname):
            skipped.append(furl); continue
        db.add_domain(dname, furl)
        added.append((dname, furl))

    m  = "📥 *HASIL IMPORT*\n"
    m += f"`{'━'*30}`\n"
    m += f"🕐 `{esc(now_str())}`\n\n"
    m += f"✅ Ditambahkan : `{len(added)}`\n"
    m += f"⏭️  Sudah ada   : `{len(skipped)}`\n"
    m += f"❌ Error       : `{len(errors)}`\n"
    m += f"📋 Total DB    : `{db.get_domain_count()}`\n\n"
    if added:
        m += "*Berhasil disimpan:*\n"
        for dname, furl in added[:20]:
            icon = "🖥️" if is_ip_address(dname) else "🌐"
            m += f"{icon} `{esc(furl)}`\n"
        if len(added) > 20:
            m += f"_\\.\\.\\. dan {len(added)-20} lainnya_\n"
    m += "\n💡 Gunakan `/checkall` untuk cek semua\\."
    await tmp.edit_text(m, parse_mode="MarkdownV2")


# ── CALLBACK: navigasi halaman ────────────────────────────────────────────────

async def cb_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        cmd, page_s = query.data.split(":")
        page = int(page_s)
    except Exception:
        return

    if cmd == "list":
        domains = db.get_all_domains()
        if not domains: return
        total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
        await query.edit_message_text(
            msg_list(domains, page),
            parse_mode="MarkdownV2",
            reply_markup=nav_kb(page, total_p, "list")
        )

    elif cmd == "checkall":
        domains = db.get_all_domains()
        results = [
            (d[1], d[2], bool(d[3]) if d[3] is not None else False, d[4] or "—")
            for d in domains
        ]
        pages   = msg_checkall_pages(results)
        if not (1 <= page <= len(pages)): return
        await query.edit_message_text(
            pages[page - 1],
            parse_mode="MarkdownV2",
            reply_markup=nav_kb(page, len(pages), "checkall")
        )


async def err_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}", exc_info=context.error)


# ── MAIN ──────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start",    "Mulai & daftarkan chat"),
        BotCommand("help",     "Panduan penggunaan"),
        BotCommand("domain",   "Kelola domain & IP"),
        BotCommand("check",    "Cek satu link/IP"),
        BotCommand("checkall", "Cek semua domain & IP"),
        BotCommand("status",   "Status bot"),
    ])
    s = db.get_settings()
    if not scheduler.running:
        scheduler.start()
    if s.get("alerts_active", True):
        schedule_check(application, s.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
    logger.info("Bot siap.")


def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("domain",   cmd_domain))
    app.add_handler(CommandHandler("check",    cmd_check))
    app.add_handler(CommandHandler("checkall", cmd_checkall))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CallbackQueryHandler(cb_nav))
    app.add_handler(MessageHandler(
        filters.Document.TXT & filters.CaptionRegex(r"^/domain import"),
        cmd_domain_import
    ))
    app.add_error_handler(err_handler)

    logger.info("🚀 Bot Nawala Checker dimulai...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
