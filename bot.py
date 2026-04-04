#!/usr/bin/env python3
"""Nawala + Trustpositif Domain Checker Bot — Final"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

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

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

checker        = NawalaChecker()
scheduler      = AsyncIOScheduler()
auto_check_job = None
PER_PAGE       = 10
WIB            = ZoneInfo("Asia/Jakarta")


# ── HELPERS ───────────────────────────────────────────────────────────────────

def esc(t: str) -> str:
    for c in r"_*[]()~`>#+-=|{}.!":
        t = t.replace(c, f"\\{c}")
    return t

def now_wib() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

def s_icon(blocked) -> str:
    return "⚪" if blocked is None else ("🔴" if blocked else "🟢")

def s_label(blocked) -> str:
    return "BELUM CEK" if blocked is None else ("BLOCK" if blocked else "AMAN")

def t_label(domain_name: str) -> str:
    return "IP ADDR" if is_ip_address(domain_name) else "DOMAIN"

def site_name() -> str:
    return db.get_settings().get("site_name", "Default Site")

def normalize_url(raw: str) -> str:
    return raw.strip().replace("https://","").replace("http://","").rstrip("/")

def nav_kb(page: int, total: int, cmd: str):
    if total <= 1: return None
    btns = []
    if page > 1:
        btns.append(InlineKeyboardButton("◀ Prev", callback_data=f"{cmd}:{page-1}"))
    btns.append(InlineKeyboardButton(f"· {page}/{total} ·", callback_data="noop"))
    if page < total:
        btns.append(InlineKeyboardButton("Next ▶", callback_data=f"{cmd}:{page+1}"))
    return InlineKeyboardMarkup([btns])


# ── MESSAGE BUILDERS ──────────────────────────────────────────────────────────

def build_list_msg(domains: list, page: int) -> str:
    sn      = site_name()
    total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
    page    = max(1, min(page, total_p))
    start   = (page - 1) * PER_PAGE
    chunk   = domains[start: start + PER_PAGE]

    aman  = sum(1 for _,_,_,b,_ in domains if b == 0)
    block = sum(1 for _,_,_,b,_ in domains if b == 1)
    belum = sum(1 for _,_,_,b,_ in domains if b is None)

    m  = "🎯 *DATA DOMAIN LIST*\n"
    m += f"`{'━'*30}`\n"
    m += f"Site : `{esc(sn)}`\n"
    m += f"Hal  : `{page}/{total_p}`\n\n"
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


def build_report_msg(results: list, page: int, title: str = "HASIL CEK DOMAIN") -> str:
    """results: [(domain_name, full_url, blocked, reason, checked_at)]"""
    sn      = site_name()
    total_p = max(1, (len(results) + PER_PAGE - 1) // PER_PAGE)
    page    = max(1, min(page, total_p))
    start   = (page - 1) * PER_PAGE
    chunk   = results[start: start + PER_PAGE]

    aman  = sum(1 for _,_,b,_,_ in results if not b)
    block = sum(1 for _,_,b,_,_ in results if b)
    now   = now_wib()

    m  = f"🎯 *{esc(title)}*\n"
    m += f"`{'━'*30}`\n"
    m += f"Site : `{esc(sn)}`\n"
    m += f"Hal  : `{page}/{total_p}`\n\n"
    m += f"`{'─'*10} RINGKASAN {'─'*10}`\n"
    m += f"📊 Total      : `{len(results)}`\n"
    m += f"🟢 Aman       : `{aman}`\n"
    m += f"🔴 Block      : `{block}`\n"
    m += f"🕐 Waktu      : `{esc(now)}`\n\n"
    for i, (dname, furl, blocked, reason, checked) in enumerate(chunk):
        no         = start + i + 1
        display    = furl if furl else dname
        reason_txt = f" \\({esc(reason)}\\)" if blocked and reason else ""
        m += f"{s_icon(blocked)} *{esc(t_label(dname))} \\#{no}*\n"
        m += f"├ Link    : `{esc(display)}`\n"
        m += f"├ Status  : `{s_label(blocked)}`{reason_txt}\n"
        m += f"└ Checked : `{esc(checked or now)}`\n\n"
    return m


def build_alert_msg(changed: list) -> str:
    m  = "⚠️ *PERUBAHAN STATUS DOMAIN*\n"
    m += f"`{'━'*30}`\n"
    m += f"Site : `{esc(site_name())}`\n"
    m += f"🕐 `{esc(now_wib())}`\n\n"
    for dname, furl, was, now_b, reason in changed:
        display    = furl if furl else dname
        reason_txt = f" \\({esc(reason)}\\)" if now_b and reason else ""
        m += f"🔄 `{esc(display)}`\n"
        m += f"├ Sebelum  : {s_icon(was)} `{s_label(was)}`\n"
        m += f"└ Sekarang : {s_icon(now_b)} `{s_label(now_b)}`{reason_txt}\n\n"
    return m


# ── CORE: jalankan pengecekan & kirim laporan ─────────────────────────────────

async def do_check_and_report(bot, chat_id: int, title: str, store_key: str, app: Application):
    """
    Fungsi inti: cek semua domain, update DB, kirim laporan + notif perubahan.
    Dipanggil oleh auto check maupun /testcheck.
    """
    domains = db.get_all_domains()
    if not domains:
        logger.info("Tidak ada domain untuk dicek.")
        return

    cache: dict[str, tuple[bool, str]] = {}
    results = []
    changed = []

    for did, dname, furl, prev, _ in domains:
        if dname not in cache:
            cache[dname] = await checker.check_detail(dname)
        blocked, reason = cache[dname]
        db.update_status_by_id(did, blocked)

        p = bool(prev) if prev is not None else None
        if p is not None and p != blocked:
            changed.append((dname, furl, p, blocked, reason))

        results.append((dname, furl, blocked, reason, now_wib()))

    # Simpan hasil untuk navigasi callback
    app.bot_data[store_key] = results

    # Kirim notifikasi perubahan (jika ada)
    if changed:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=build_alert_msg(changed),
                parse_mode="MarkdownV2"
            )
            logger.info(f"Notifikasi perubahan: {len(changed)} domain.")
        except Exception as e:
            logger.error(f"Gagal kirim alert: {e}")

    # Kirim laporan lengkap (1 pesan + navigasi)
    total_p = max(1, (len(results) + PER_PAGE - 1) // PER_PAGE)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=build_report_msg(results, 1, title),
            parse_mode="MarkdownV2",
            reply_markup=nav_kb(1, total_p, store_key.replace("_results", ""))
        )
        logger.info(f"Laporan terkirim: {len(results)} link, {len(changed)} berubah.")
    except Exception as e:
        logger.error(f"Gagal kirim laporan: {e}")


# ── AUTO CHECK ────────────────────────────────────────────────────────────────

async def run_auto_check(application: Application):
    s       = db.get_settings()
    chat_id = s.get("chat_id")

    if not chat_id:
        logger.warning("Auto check: chat_id belum disimpan. Kirim /start ke grup dulu.")
        return
    if not s.get("alerts_active", True):
        logger.info("Auto check: alerts_active = False, skip.")
        return

    logger.info(f"Auto check mulai → chat_id: {chat_id}")
    await do_check_and_report(
        bot=application.bot,
        chat_id=int(chat_id),
        title="LAPORAN AUTO CHECK",
        store_key="autocheck_results",
        app=application
    )


def schedule_check(application: Application, minutes: int):
    global auto_check_job
    if auto_check_job:
        try: auto_check_job.remove()
        except: pass
    auto_check_job = scheduler.add_job(
        run_auto_check,
        trigger=IntervalTrigger(minutes=minutes),
        args=[application],
        id="auto_check",
        replace_existing=True,
    )
    db.save_setting("alerts_active", True)
    nxt = auto_check_job.next_run_time
    logger.info(f"Auto check dijadwalkan setiap {minutes} menit. Berikutnya: {nxt}")


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.save_chat_id(chat_id)
    logger.info(f"/start — chat_id disimpan: {chat_id}")
    await update.message.reply_text(
        "👋 *Selamat datang di Nawala Checker Bot\\!*\n\n"
        "Bot mengecek domain terhadap:\n"
        "🔸 *Nawala* \\(DNS 180\\.131\\.144\\.144\\)\n"
        "🔸 *Trustpositif / Internet Positif*\n\n"
        f"✅ Chat ID grup ini sudah tersimpan: `{chat_id}`\n\n"
        "Ketik /help untuk panduan\\.",
        parse_mode="MarkdownV2"
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] in ("-hh", "--h"):
        await update.message.reply_text(
            "📋 *Daftar Perintah*\n\n"
            "*Domain & IP:*\n"
            "`/domain add <link>` — tambah 1 link/IP\n"
            "`/domain add <l1> <l2> ...` — tambah banyak\n"
            "`/domain delete <link>` — hapus link\n"
            "`/domain list` — daftar semua\n"
            "`/domain interval <menit>` — ubah interval\n"
            "`/domain stop` — hentikan laporan otomatis\n"
            "`/domain setsite <nama>` — set nama site\n\n"
            "*Cek Manual:*\n"
            "`/check <link/IP>` — cek satu\n"
            "`/checkall` — cek semua sekarang\n"
            "`/testcheck` — test kirim laporan ke grup\n\n"
            "*Import File:*\n"
            "Kirim file `.txt` + caption `/domain import`\n\n"
            "`/status` — status bot & debug info\n",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "📖 *Panduan Bot*\n\n"
        "`/domain add mez.ink/ruangwd`\n"
        "`/domain list`\n"
        "`/checkall`\n"
        "`/testcheck` — test laporan otomatis\n\n"
        "Ketik `/help -hh` untuk semua perintah.",
        parse_mode="Markdown"
    )


# ── /domain ───────────────────────────────────────────────────────────────────

async def cmd_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Sub-command diperlukan. Ketik `/help -hh`", parse_mode="Markdown")
        return
    sub = args[0].lower()

    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Contoh:\n`/domain add mez.ink/ruangwd`\n`/domain add link1 link2 link3`",
                parse_mode="Markdown"
            )
            return
        raw_list = args[1:]

        if len(raw_list) == 1:
            furl  = normalize_url(raw_list[0])
            dname = extract_domain(furl)
            if db.url_exists(furl):
                await update.message.reply_text(f"⚠️ Link `{furl}` sudah ada.", parse_mode="Markdown")
                return
            db.add_domain(dname, furl)
            tmp = await update.message.reply_text(
                f"⏳ Menyimpan dan mengecek `{esc(furl)}`\\.\\.\\.", parse_mode="MarkdownV2"
            )
            blocked, reason = await checker.check_detail(dname)
            db.update_status_by_url(furl, blocked)
            reason_txt = f" \\({esc(reason)}\\)" if blocked and reason else ""
            await tmp.edit_text(
                f"✅ *{esc(t_label(dname))} ditambahkan\\!*\n\n"
                f"{s_icon(blocked)} *{esc(t_label(dname))} BARU*\n"
                f"├ Link    : `{esc(furl)}`\n"
                f"├ Status  : `{s_label(blocked)}`{reason_txt}\n"
                f"└ Checked : `{esc(now_wib())}`",
                parse_mode="MarkdownV2"
            )
        else:
            tmp = await update.message.reply_text(
                f"⏳ Menyimpan *{len(raw_list)} link*\\.\\.\\.", parse_mode="MarkdownV2"
            )
            added, skipped, errors = [], [], []
            for raw in raw_list:
                raw = raw.strip()
                if not raw: continue
                furl  = normalize_url(raw)
                dname = extract_domain(furl)
                if not dname: errors.append(raw); continue
                if db.url_exists(furl): skipped.append(furl); continue
                db.add_domain(dname, furl)
                added.append((dname, furl))

            m  = "📥 *HASIL TAMBAH DOMAIN*\n"
            m += f"`{'━'*30}`\n"
            m += f"🕐 `{esc(now_wib())}`\n\n"
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
            m += "\n💡 Gunakan `/checkall` untuk cek status semua\\."
            await tmp.edit_text(m, parse_mode="MarkdownV2")

    elif sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("❌ `/domain delete <link>`", parse_mode="Markdown"); return
        furl = normalize_url(args[1])
        if not db.url_exists(furl):
            await update.message.reply_text(f"❌ `{furl}` tidak ditemukan.", parse_mode="Markdown"); return
        db.delete_domain_by_url(furl)
        await update.message.reply_text(f"🗑️ `{furl}` dihapus.", parse_mode="Markdown")

    elif sub == "list":
        domains = db.get_all_domains()
        if not domains:
            await update.message.reply_text("📭 Belum ada domain.", parse_mode="Markdown"); return
        total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
        await update.message.reply_text(
            build_list_msg(domains, 1), parse_mode="MarkdownV2",
            reply_markup=nav_kb(1, total_p, "list")
        )

    elif sub == "interval":
        if len(args) < 2:
            await update.message.reply_text("❌ `/domain interval <menit>`", parse_mode="Markdown"); return
        try:
            minutes = int(args[1]); assert minutes > 0
        except Exception:
            await update.message.reply_text("❌ Masukkan angka menit yang valid.", parse_mode="Markdown"); return
        db.save_setting("interval_minutes", minutes)
        schedule_check(context.application, minutes)
        job = scheduler.get_job("auto_check")
        nxt = "—"
        if job and job.next_run_time:
            nxt = job.next_run_time.astimezone(WIB).strftime("%Y-%m-%d %H:%M WIB")
        await update.message.reply_text(
            f"⏱️ Interval diubah ke *{minutes} menit*\\.\n"
            f"⏰ Laporan berikutnya: `{esc(nxt)}`",
            parse_mode="MarkdownV2"
        )

    elif sub == "stop":
        db.save_setting("alerts_active", False)
        if auto_check_job:
            try: auto_check_job.pause()
            except: pass
        await update.message.reply_text(
            "🔕 Laporan otomatis *dihentikan*\\.\n"
            "Gunakan `/domain interval <menit>` untuk aktifkan kembali\\.",
            parse_mode="MarkdownV2"
        )

    elif sub == "setsite":
        if len(args) < 2:
            await update.message.reply_text("❌ `/domain setsite <nama>`", parse_mode="Markdown"); return
        sn = " ".join(args[1:])
        db.save_setting("site_name", sn)
        await update.message.reply_text(f"✅ Nama site: `{sn}`", parse_mode="Markdown")

    elif sub == "import":
        await update.message.reply_text(
            "📥 *Cara Import:*\n\n"
            "1\\. Siapkan file `.txt` \\(satu link per baris\\)\n"
            "2\\. Kirim file ke grup\n"
            "3\\. Caption: `/domain import`",
            parse_mode="MarkdownV2"
        )
    else:
        await update.message.reply_text(f"❓ Sub-command `{sub}` tidak dikenal.", parse_mode="Markdown")


# ── /check ────────────────────────────────────────────────────────────────────

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Gunakan: `/check <link/IP>`", parse_mode="Markdown"); return
    furl   = normalize_url(context.args[0])
    dname  = extract_domain(furl)
    metode = "HTTP Request" if is_ip_address(dname) else "DNS Lookup"
    tmp = await update.message.reply_text(f"⏳ Mengecek `{esc(furl)}`\\.\\.\\.", parse_mode="MarkdownV2")
    blocked, reason = await checker.check_detail(dname)
    if db.url_exists(furl):
        db.update_status_by_url(furl, blocked)
    reason_txt = f" \\({esc(reason)}\\)" if blocked and reason else ""
    await tmp.edit_text(
        f"🔍 *HASIL CEK MANUAL*\n"
        f"`{'━'*30}`\n"
        f"{s_icon(blocked)} *{esc(t_label(dname))}*\n"
        f"├ Link    : `{esc(furl)}`\n"
        f"├ Metode  : `{metode}`\n"
        f"├ Status  : `{s_label(blocked)}`{reason_txt}\n"
        f"└ Checked : `{esc(now_wib())}`",
        parse_mode="MarkdownV2"
    )


# ── /checkall ─────────────────────────────────────────────────────────────────

async def cmd_checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domains = db.get_all_domains()
    if not domains:
        await update.message.reply_text("📭 Belum ada domain.", parse_mode="Markdown"); return

    tmp = await update.message.reply_text(
        f"⏳ Mengecek `{len(domains)}` link\\.\\.\\.", parse_mode="MarkdownV2"
    )
    cache: dict[str, tuple[bool, str]] = {}
    results = []
    for did, dname, furl, _, _ in domains:
        if dname not in cache:
            cache[dname] = await checker.check_detail(dname)
        blocked, reason = cache[dname]
        db.update_status_by_id(did, blocked)
        results.append((dname, furl, blocked, reason, now_wib()))

    context.bot_data["checkall_results"] = results
    total_p = max(1, (len(results) + PER_PAGE - 1) // PER_PAGE)
    await tmp.edit_text(
        build_report_msg(results, 1, "HASIL CEK DOMAIN"),
        parse_mode="MarkdownV2",
        reply_markup=nav_kb(1, total_p, "checkall")
    )


# ── /testcheck — trigger auto check manual ────────────────────────────────────

async def cmd_testcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger auto check sekarang untuk test — kirim laporan ke grup."""
    s       = db.get_settings()
    chat_id = s.get("chat_id")

    await update.message.reply_text(
        f"🔧 *DEBUG INFO*\n"
        f"`{'━'*30}`\n"
        f"Chat ID tersimpan : `{chat_id or 'BELUM ADA'}`\n"
        f"Chat ID grup ini  : `{update.effective_chat.id}`\n"
        f"Alerts active     : `{s.get('alerts_active', True)}`\n"
        f"Total domain DB   : `{db.get_domain_count()}`\n\n"
        f"⏳ Mengirim laporan ke grup\\.\\.\\.",
        parse_mode="MarkdownV2"
    )

    # Paksa gunakan chat_id grup saat ini
    target_chat = update.effective_chat.id
    # Update chat_id ke grup ini
    db.save_chat_id(target_chat)

    if db.get_domain_count() == 0:
        await update.message.reply_text(
            "❌ Tidak ada domain di database\\.\n"
            "Import dulu dengan kirim file `.txt` \\+ caption `/domain import`",
            parse_mode="MarkdownV2"
        )
        return

    await do_check_and_report(
        bot=context.bot,
        chat_id=target_chat,
        title="TEST LAPORAN AUTO CHECK",
        store_key="autocheck_results",
        app=context.application
    )
    await update.message.reply_text("✅ Laporan berhasil dikirim\\!", parse_mode="MarkdownV2")


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s   = db.get_settings()
    job = scheduler.get_job("auto_check")
    nxt = "—"
    if job and job.next_run_time:
        nxt = job.next_run_time.astimezone(WIB).strftime("%Y-%m-%d %H:%M WIB")
    al       = "✅ Aktif" if s.get("alerts_active", True) else "🔕 Nonaktif"
    chat_id  = s.get("chat_id") or "❌ BELUM ADA — kirim /start ke grup"
    job_st   = "✅ Berjalan" if (job and job.next_run_time) else "❌ Tidak aktif"

    await update.message.reply_text(
        f"🤖 *STATUS BOT*\n"
        f"`{'━'*30}`\n"
        f"📋 Total link         : `{db.get_domain_count()}`\n"
        f"🌐 Site               : `{esc(s.get('site_name','—'))}`\n"
        f"⏱️  Interval            : `{s.get('interval_minutes', DEFAULT_INTERVAL_MINUTES)} menit`\n"
        f"🔔 Laporan otomatis   : {al}\n"
        f"⚙️  Scheduler          : {job_st}\n"
        f"⏰ Laporan berikutnya  : `{esc(nxt)}`\n"
        f"💬 Chat ID tersimpan  : `{esc(str(chat_id))}`\n\n"
        f"🛡️ Cakupan:\n"
        f"  • Nawala \\(DNS 180\\.131\\.144\\.144\\)\n"
        f"  • Trustpositif / Internet Positif\n\n"
        f"💡 Ketik `/testcheck` untuk test kirim laporan sekarang",
        parse_mode="MarkdownV2"
    )


# ── Import file .txt ──────────────────────────────────────────────────────────

async def cmd_domain_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document if update.message else None
    if not doc:
        await update.message.reply_text("📥 Kirim file `.txt` dengan caption `/domain import`", parse_mode="Markdown"); return
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Hanya file `.txt`.", parse_mode="Markdown"); return

    tmp = await update.message.reply_text("⏳ Membaca file\\.\\.\\.", parse_mode="MarkdownV2")
    tg_file   = await context.bot.get_file(doc.file_id)
    raw_bytes = await tg_file.download_as_bytearray()
    content   = raw_bytes.decode("utf-8", errors="ignore")

    added, skipped, errors = [], [], []
    for line in content.splitlines():
        url = line.strip().replace("\r","")
        if not url or url.startswith("#"): continue
        furl  = normalize_url(url)
        dname = extract_domain(furl)
        if not dname: errors.append(url); continue
        if db.url_exists(furl): skipped.append(furl); continue
        db.add_domain(dname, furl)
        added.append((dname, furl))

    m  = "📥 *HASIL IMPORT*\n"
    m += f"`{'━'*30}`\n"
    m += f"🕐 `{esc(now_wib())}`\n\n"
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
    m += "\n💡 Gunakan `/checkall` atau `/testcheck` untuk verifikasi\\."
    await tmp.edit_text(m, parse_mode="MarkdownV2")


# ── CALLBACK navigasi ─────────────────────────────────────────────────────────

async def cb_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "noop": return
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
            build_list_msg(domains, page), parse_mode="MarkdownV2",
            reply_markup=nav_kb(page, total_p, "list")
        )
    elif cmd in ("checkall", "autocheck"):
        key     = f"{cmd}_results"
        results = context.bot_data.get(key)
        if not results:
            domains = db.get_all_domains()
            results = [(d[1], d[2], bool(d[3]) if d[3] is not None else False,
                        "", d[4] or "—") for d in domains]
        total_p = max(1, (len(results) + PER_PAGE - 1) // PER_PAGE)
        if not (1 <= page <= total_p): return
        title = "LAPORAN AUTO CHECK" if cmd == "autocheck" else "HASIL CEK DOMAIN"
        await query.edit_message_text(
            build_report_msg(results, page, title), parse_mode="MarkdownV2",
            reply_markup=nav_kb(page, total_p, cmd)
        )


async def err_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}", exc_info=context.error)


# ── MAIN ──────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start",     "Mulai & daftarkan chat grup"),
        BotCommand("help",      "Panduan penggunaan"),
        BotCommand("domain",    "Kelola domain & IP"),
        BotCommand("check",     "Cek satu link/IP"),
        BotCommand("checkall",  "Cek semua domain & IP"),
        BotCommand("testcheck", "Test kirim laporan ke grup"),
        BotCommand("status",    "Status bot & debug info"),
    ])
    s = db.get_settings()
    if not scheduler.running:
        scheduler.start()
    if s.get("alerts_active", True) and s.get("chat_id"):
        schedule_check(application, s.get("interval_minutes", DEFAULT_INTERVAL_MINUTES))
        logger.info(f"Auto check aktif setiap {s.get('interval_minutes', DEFAULT_INTERVAL_MINUTES)} menit.")
    else:
        logger.warning("Auto check TIDAK aktif — chat_id belum ada atau alerts dimatikan.")
    logger.info("Bot siap.")


def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("domain",    cmd_domain))
    app.add_handler(CommandHandler("check",     cmd_check))
    app.add_handler(CommandHandler("checkall",  cmd_checkall))
    app.add_handler(CommandHandler("testcheck", cmd_testcheck))
    app.add_handler(CommandHandler("status",    cmd_status))
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
