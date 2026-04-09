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

def h(t: str) -> str:
    """Escape HTML special chars."""
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

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

def make_link(furl: str) -> str:
    """Buat hyperlink HTML yang bisa diklik."""
    url = f"https://{furl}" if not furl.startswith("http") else furl
    return f'<a href="{url}">{h(furl)}</a>'

def nav_kb(page: int, total: int, cmd: str):
    if total <= 1: return None
    btns = []
    if page > 1:
        btns.append(InlineKeyboardButton("◀ Prev", callback_data=f"{cmd}:{page-1}"))
    btns.append(InlineKeyboardButton(f"· {page}/{total} ·", callback_data="noop"))
    if page < total:
        btns.append(InlineKeyboardButton("Next ▶", callback_data=f"{cmd}:{page+1}"))
    return InlineKeyboardMarkup([btns])

def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ya, Hapus Semua", callback_data=f"confirm:{action}"),
        InlineKeyboardButton("❌ Batal", callback_data="confirm:cancel"),
    ]])


# ── MESSAGE BUILDERS (HTML) ───────────────────────────────────────────────────

def build_list_msg(domains: list, page: int) -> str:
    sn      = site_name()
    total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
    page    = max(1, min(page, total_p))
    start   = (page - 1) * PER_PAGE
    chunk   = domains[start: start + PER_PAGE]

    aman  = sum(1 for _,_,_,b,_ in domains if b == 0)
    block = sum(1 for _,_,_,b,_ in domains if b == 1)
    belum = sum(1 for _,_,_,b,_ in domains if b is None)

    m  = f"🎯 <b>DATA DOMAIN LIST</b>\n"
    m += f"<code>{'━'*30}</code>\n"
    m += f"Site : <code>{h(sn)}</code>\n"
    m += f"Hal  : <code>{page}/{total_p}</code>\n\n"
    m += f"<code>{'─'*10} RINGKASAN {'─'*10}</code>\n"
    m += f"📊 Total      : <code>{len(domains)}</code>\n"
    m += f"🟢 Aman       : <code>{aman}</code>\n"
    m += f"🔴 Block      : <code>{block}</code>\n"
    m += f"⚪ Belum Cek  : <code>{belum}</code>\n\n"

    for i, (_, dname, furl, blocked, checked) in enumerate(chunk):
        no      = start + i + 1
        display = furl if furl else dname
        m += f"{s_icon(blocked)} <b>{h(t_label(dname))} #{no}</b>\n"
        m += f"├ Link    : {make_link(display)}\n"
        m += f"├ Status  : <code>{s_label(blocked)}</code>\n"
        m += f"└ Checked : <code>{h(checked or '—')}</code>\n\n"
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

    m  = f"🎯 <b>{h(title)}</b>\n"
    m += f"<code>{'━'*30}</code>\n"
    m += f"Site : <code>{h(sn)}</code>\n"
    m += f"Hal  : <code>{page}/{total_p}</code>\n\n"
    m += f"<code>{'─'*10} RINGKASAN {'─'*10}</code>\n"
    m += f"📊 Total      : <code>{len(results)}</code>\n"
    m += f"🟢 Aman       : <code>{aman}</code>\n"
    m += f"🔴 Block      : <code>{block}</code>\n"
    m += f"🕐 Waktu      : <code>{h(now)}</code>\n\n"

    for i, (dname, furl, blocked, reason, checked) in enumerate(chunk):
        no         = start + i + 1
        display    = furl if furl else dname
        reason_txt = f" <code>({h(reason)})</code>" if blocked and reason else ""
        m += f"{s_icon(blocked)} <b>{h(t_label(dname))} #{no}</b>\n"
        m += f"├ Link    : {make_link(display)}\n"
        m += f"├ Status  : <code>{s_label(blocked)}</code>{reason_txt}\n"
        m += f"└ Checked : <code>{h(checked or now)}</code>\n\n"
    return m


def build_alert_msg(changed: list) -> str:
    m  = "⚠️ <b>PERUBAHAN STATUS DOMAIN</b>\n"
    m += f"<code>{'━'*30}</code>\n"
    m += f"Site : <code>{h(site_name())}</code>\n"
    m += f"🕐 <code>{h(now_wib())}</code>\n\n"
    for dname, furl, was, now_b, reason in changed:
        display    = furl if furl else dname
        reason_txt = f" <code>({h(reason)})</code>" if now_b and reason else ""
        m += f"🔄 {make_link(display)}\n"
        m += f"├ Sebelum  : {s_icon(was)} <code>{s_label(was)}</code>\n"
        m += f"└ Sekarang : {s_icon(now_b)} <code>{s_label(now_b)}</code>{reason_txt}\n\n"
    return m


# ── CORE CHECK & REPORT ───────────────────────────────────────────────────────

async def do_check_and_report(bot, chat_id: int, title: str, store_key: str, app: Application):
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

    app.bot_data[store_key] = results

    if changed:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=build_alert_msg(changed),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Gagal kirim alert: {e}")

    total_p = max(1, (len(results) + PER_PAGE - 1) // PER_PAGE)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=build_report_msg(results, 1, title),
            parse_mode="HTML",
            reply_markup=nav_kb(1, total_p, store_key.replace("_results",""))
        )
        logger.info(f"Laporan terkirim: {len(results)} link, {len(changed)} berubah.")
    except Exception as e:
        logger.error(f"Gagal kirim laporan: {e}")


# ── AUTO CHECK ────────────────────────────────────────────────────────────────

async def run_auto_check(application: Application):
    s       = db.get_settings()
    chat_id = s.get("chat_id")
    if not chat_id:
        logger.warning("Auto check: chat_id belum ada. Kirim /start ke grup dulu.")
        return
    if not s.get("alerts_active", True):
        logger.info("Auto check: dinonaktifkan.")
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
    logger.info(f"Auto check dijadwalkan setiap {minutes} menit.")


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db.save_chat_id(chat_id)
    logger.info(f"/start — chat_id: {chat_id}")
    await update.message.reply_text(
        f"👋 <b>Selamat datang di Nawala Checker Bot!</b>\n\n"
        f"Bot mengecek domain terhadap:\n"
        f"🔸 <b>Nawala</b> (DNS 180.131.144.144)\n"
        f"🔸 <b>Trustpositif / Internet Positif</b>\n\n"
        f"✅ Chat ID tersimpan: <code>{chat_id}</code>\n\n"
        f"Ketik /help untuk panduan.",
        parse_mode="HTML"
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] in ("-hh", "--h"):
        await update.message.reply_text(
            "📋 <b>Daftar Perintah</b>\n\n"
            "<b>Domain &amp; IP:</b>\n"
            "<code>/domain add &lt;link&gt;</code> — tambah 1 link/IP\n"
            "<code>/domain add &lt;l1&gt; &lt;l2&gt; ...</code> — tambah banyak\n"
            "<code>/domain delete &lt;link&gt;</code> — hapus 1 link\n"
            "<code>/domain deleteall</code> — hapus SEMUA link\n"
            "<code>/domain list</code> — daftar semua\n"
            "<code>/domain interval &lt;menit&gt;</code> — ubah interval\n"
            "<code>/domain stop</code> — hentikan laporan otomatis\n"
            "<code>/domain setsite &lt;nama&gt;</code> — set nama site\n\n"
            "<b>Cek Manual:</b>\n"
            "<code>/check &lt;link/IP&gt;</code> — cek satu\n"
            "<code>/checkall</code> — cek semua sekarang\n"
            "<code>/testcheck</code> — test kirim laporan ke grup\n\n"
            "<b>Import File:</b>\n"
            "Kirim file <code>.txt</code> + caption <code>/domain import</code>\n\n"
            "<code>/status</code> — status bot\n",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text(
        "📖 <b>Panduan Bot</b>\n\n"
        "<code>/domain add mez.ink/ruangwd</code>\n"
        "<code>/domain deleteall</code> — hapus semua\n"
        "<code>/domain list</code>\n"
        "<code>/checkall</code>\n"
        "<code>/testcheck</code>\n\n"
        "Ketik <code>/help -hh</code> untuk semua perintah.",
        parse_mode="HTML"
    )


# ── /domain ───────────────────────────────────────────────────────────────────

async def cmd_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Sub-command diperlukan. Ketik <code>/help -hh</code>", parse_mode="HTML")
        return
    sub = args[0].lower()

    # ── add ──
    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Contoh:\n<code>/domain add mez.ink/ruangwd</code>\n"
                "<code>/domain add link1 link2 link3</code>",
                parse_mode="HTML"
            )
            return
        raw_list = args[1:]

        if len(raw_list) == 1:
            furl  = normalize_url(raw_list[0])
            dname = extract_domain(furl)
            if db.url_exists(furl):
                await update.message.reply_text(f"⚠️ Link <code>{h(furl)}</code> sudah ada.", parse_mode="HTML")
                return
            db.add_domain(dname, furl)
            tmp = await update.message.reply_text(
                f"⏳ Menyimpan dan mengecek <code>{h(furl)}</code>...", parse_mode="HTML"
            )
            blocked, reason = await checker.check_detail(dname)
            db.update_status_by_url(furl, blocked)
            reason_txt = f" <code>({h(reason)})</code>" if blocked and reason else ""
            await tmp.edit_text(
                f"✅ <b>{h(t_label(dname))} ditambahkan!</b>\n\n"
                f"{s_icon(blocked)} <b>{h(t_label(dname))} BARU</b>\n"
                f"├ Link    : {make_link(furl)}\n"
                f"├ Status  : <code>{s_label(blocked)}</code>{reason_txt}\n"
                f"└ Checked : <code>{h(now_wib())}</code>",
                parse_mode="HTML"
            )
        else:
            tmp = await update.message.reply_text(
                f"⏳ Menyimpan <b>{len(raw_list)} link</b>...", parse_mode="HTML"
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

            m  = "📥 <b>HASIL TAMBAH DOMAIN</b>\n"
            m += f"<code>{'━'*30}</code>\n"
            m += f"🕐 <code>{h(now_wib())}</code>\n\n"
            m += f"✅ Ditambahkan : <code>{len(added)}</code>\n"
            m += f"⏭️  Sudah ada   : <code>{len(skipped)}</code>\n"
            m += f"❌ Error       : <code>{len(errors)}</code>\n"
            m += f"📋 Total DB    : <code>{db.get_domain_count()}</code>\n\n"
            if added:
                m += "<b>Berhasil disimpan:</b>\n"
                for dname, furl in added[:20]:
                    icon = "🖥️" if is_ip_address(dname) else "🌐"
                    m += f"{icon} {make_link(furl)}\n"
                if len(added) > 20:
                    m += f"<i>... dan {len(added)-20} lainnya</i>\n"
            m += "\n💡 Gunakan <code>/checkall</code> untuk cek status semua."
            await tmp.edit_text(m, parse_mode="HTML")

    # ── delete ──
    elif sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("❌ <code>/domain delete &lt;link&gt;</code>", parse_mode="HTML"); return
        furl = normalize_url(args[1])
        if not db.url_exists(furl):
            await update.message.reply_text(f"❌ <code>{h(furl)}</code> tidak ditemukan.", parse_mode="HTML"); return
        db.delete_domain_by_url(furl)
        await update.message.reply_text(f"🗑️ <code>{h(furl)}</code> dihapus.", parse_mode="HTML")

    # ── deleteall ──
    elif sub == "deleteall":
        total = db.get_domain_count()
        if total == 0:
            await update.message.reply_text("📭 Tidak ada domain yang perlu dihapus.", parse_mode="HTML"); return
        await update.message.reply_text(
            f"⚠️ <b>KONFIRMASI HAPUS SEMUA</b>\n\n"
            f"Anda akan menghapus <b>{total} link</b> dari database.\n"
            f"Tindakan ini <b>tidak bisa dibatalkan</b>.\n\n"
            f"Yakin ingin melanjutkan?",
            parse_mode="HTML",
            reply_markup=confirm_kb("deleteall")
        )

    # ── list ──
    elif sub == "list":
        domains = db.get_all_domains()
        if not domains:
            await update.message.reply_text("📭 Belum ada domain.", parse_mode="HTML"); return
        total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
        await update.message.reply_text(
            build_list_msg(domains, 1), parse_mode="HTML",
            reply_markup=nav_kb(1, total_p, "list")
        )

    # ── interval ──
    elif sub == "interval":
        if len(args) < 2:
            await update.message.reply_text("❌ <code>/domain interval &lt;menit&gt;</code>", parse_mode="HTML"); return
        try:
            minutes = int(args[1]); assert minutes > 0
        except Exception:
            await update.message.reply_text("❌ Masukkan angka menit yang valid.", parse_mode="HTML"); return
        db.save_setting("interval_minutes", minutes)
        schedule_check(context.application, minutes)
        job = scheduler.get_job("auto_check")
        nxt = "—"
        if job and job.next_run_time:
            nxt = job.next_run_time.astimezone(WIB).strftime("%Y-%m-%d %H:%M WIB")
        await update.message.reply_text(
            f"⏱️ Interval diubah ke <b>{minutes} menit</b>.\n"
            f"⏰ Laporan berikutnya: <code>{h(nxt)}</code>",
            parse_mode="HTML"
        )

    # ── stop ──
    elif sub == "stop":
        db.save_setting("alerts_active", False)
        if auto_check_job:
            try: auto_check_job.pause()
            except: pass
        await update.message.reply_text(
            "🔕 Laporan otomatis <b>dihentikan</b>.\n"
            "Gunakan <code>/domain interval &lt;menit&gt;</code> untuk aktifkan kembali.",
            parse_mode="HTML"
        )

    # ── setsite ──
    elif sub == "setsite":
        if len(args) < 2:
            await update.message.reply_text("❌ <code>/domain setsite &lt;nama&gt;</code>", parse_mode="HTML"); return
        sn = " ".join(args[1:])
        db.save_setting("site_name", sn)
        await update.message.reply_text(f"✅ Nama site: <code>{h(sn)}</code>", parse_mode="HTML")

    # ── import ──
    elif sub == "import":
        await update.message.reply_text(
            "📥 <b>Cara Import:</b>\n\n"
            "1. Siapkan file <code>.txt</code> (satu link per baris)\n"
            "2. Kirim file ke grup\n"
            "3. Caption: <code>/domain import</code>",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(f"❓ Sub-command <code>{h(sub)}</code> tidak dikenal.", parse_mode="HTML")


# ── /check ────────────────────────────────────────────────────────────────────

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Gunakan: <code>/check &lt;link/IP&gt;</code>", parse_mode="HTML"); return
    furl   = normalize_url(context.args[0])
    dname  = extract_domain(furl)
    metode = "HTTP Request" if is_ip_address(dname) else "DNS Lookup"
    tmp = await update.message.reply_text(f"⏳ Mengecek <code>{h(furl)}</code>...", parse_mode="HTML")
    blocked, reason = await checker.check_detail(dname)
    if db.url_exists(furl):
        db.update_status_by_url(furl, blocked)
    reason_txt = f" <code>({h(reason)})</code>" if blocked and reason else ""
    await tmp.edit_text(
        f"🔍 <b>HASIL CEK MANUAL</b>\n"
        f"<code>{'━'*30}</code>\n"
        f"{s_icon(blocked)} <b>{h(t_label(dname))}</b>\n"
        f"├ Link    : {make_link(furl)}\n"
        f"├ Metode  : <code>{metode}</code>\n"
        f"├ Status  : <code>{s_label(blocked)}</code>{reason_txt}\n"
        f"└ Checked : <code>{h(now_wib())}</code>",
        parse_mode="HTML"
    )


# ── /checkall ─────────────────────────────────────────────────────────────────

async def cmd_checkall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    domains = db.get_all_domains()
    if not domains:
        await update.message.reply_text("📭 Belum ada domain.", parse_mode="HTML"); return
    tmp = await update.message.reply_text(
        f"⏳ Mengecek <code>{len(domains)}</code> link...", parse_mode="HTML"
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
        parse_mode="HTML",
        reply_markup=nav_kb(1, total_p, "checkall")
    )


# ── /testcheck ────────────────────────────────────────────────────────────────

async def cmd_testcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s       = db.get_settings()
    chat_id = update.effective_chat.id
    db.save_chat_id(chat_id)

    await update.message.reply_text(
        f"🔧 <b>DEBUG INFO</b>\n"
        f"<code>{'━'*30}</code>\n"
        f"Chat ID tersimpan : <code>{s.get('chat_id') or 'BELUM ADA'}</code>\n"
        f"Chat ID grup ini  : <code>{chat_id}</code>\n"
        f"Alerts active     : <code>{s.get('alerts_active', True)}</code>\n"
        f"Total domain DB   : <code>{db.get_domain_count()}</code>\n\n"
        f"⏳ Mengirim laporan ke grup...",
        parse_mode="HTML"
    )
    if db.get_domain_count() == 0:
        await update.message.reply_text(
            "❌ Tidak ada domain di database.\n"
            "Import dulu dengan kirim file <code>.txt</code> + caption <code>/domain import</code>",
            parse_mode="HTML"
        ); return

    await do_check_and_report(
        bot=context.bot,
        chat_id=chat_id,
        title="TEST LAPORAN AUTO CHECK",
        store_key="autocheck_results",
        app=context.application
    )
    await update.message.reply_text("✅ Laporan berhasil dikirim!", parse_mode="HTML")


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s   = db.get_settings()
    job = scheduler.get_job("auto_check")
    nxt = "—"
    if job and job.next_run_time:
        nxt = job.next_run_time.astimezone(WIB).strftime("%Y-%m-%d %H:%M WIB")
    al     = "✅ Aktif" if s.get("alerts_active", True) else "🔕 Nonaktif"
    job_st = "✅ Berjalan" if (job and job.next_run_time) else "❌ Tidak aktif"
    cid    = s.get("chat_id") or "❌ BELUM ADA — kirim /start ke grup"
    await update.message.reply_text(
        f"🤖 <b>STATUS BOT</b>\n"
        f"<code>{'━'*30}</code>\n"
        f"📋 Total link          : <code>{db.get_domain_count()}</code>\n"
        f"🌐 Site                : <code>{h(s.get('site_name','—'))}</code>\n"
        f"⏱️  Interval             : <code>{s.get('interval_minutes', DEFAULT_INTERVAL_MINUTES)} menit</code>\n"
        f"🔔 Laporan otomatis    : {al}\n"
        f"⚙️  Scheduler           : {job_st}\n"
        f"⏰ Laporan berikutnya   : <code>{h(nxt)}</code>\n"
        f"💬 Chat ID tersimpan   : <code>{h(str(cid))}</code>\n\n"
        f"🛡️ Cakupan:\n"
        f"  • Nawala (DNS 180.131.144.144)\n"
        f"  • Trustpositif / Internet Positif\n\n"
        f"💡 Ketik <code>/testcheck</code> untuk test kirim laporan sekarang",
        parse_mode="HTML"
    )


# ── Import file .txt ──────────────────────────────────────────────────────────

async def cmd_domain_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document if update.message else None
    if not doc:
        await update.message.reply_text(
            "📥 Kirim file <code>.txt</code> dengan caption <code>/domain import</code>",
            parse_mode="HTML"
        ); return
    if not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ Hanya file <code>.txt</code>.", parse_mode="HTML"); return

    tmp = await update.message.reply_text("⏳ Membaca file...", parse_mode="HTML")
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

    m  = "📥 <b>HASIL IMPORT</b>\n"
    m += f"<code>{'━'*30}</code>\n"
    m += f"🕐 <code>{h(now_wib())}</code>\n\n"
    m += f"✅ Ditambahkan : <code>{len(added)}</code>\n"
    m += f"⏭️  Sudah ada   : <code>{len(skipped)}</code>\n"
    m += f"❌ Error       : <code>{len(errors)}</code>\n"
    m += f"📋 Total DB    : <code>{db.get_domain_count()}</code>\n\n"
    if added:
        m += "<b>Berhasil disimpan:</b>\n"
        for dname, furl in added[:20]:
            icon = "🖥️" if is_ip_address(dname) else "🌐"
            m += f"{icon} {make_link(furl)}\n"
        if len(added) > 20:
            m += f"<i>... dan {len(added)-20} lainnya</i>\n"
    m += "\n💡 Gunakan <code>/checkall</code> atau <code>/testcheck</code> untuk verifikasi."
    await tmp.edit_text(m, parse_mode="HTML")


# ── CALLBACK: navigasi + konfirmasi ──────────────────────────────────────────

async def cb_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    # ── Konfirmasi deleteall ──
    if data.startswith("confirm:"):
        action = data.split(":", 1)[1]
        if action == "cancel":
            await query.edit_message_text("❌ Hapus semua dibatalkan.", parse_mode="HTML")
            return
        if action == "deleteall":
            total = db.get_domain_count()
            db.delete_all_domains()
            await query.edit_message_text(
                f"🗑️ <b>Semua domain berhasil dihapus!</b>\n\n"
                f"Total dihapus : <code>{total}</code> link\n"
                f"Waktu         : <code>{h(now_wib())}</code>",
                parse_mode="HTML"
            )
            return

    # ── Navigasi halaman ──
    try:
        cmd, page_s = data.split(":")
        page = int(page_s)
    except Exception:
        return

    if cmd == "list":
        domains = db.get_all_domains()
        if not domains: return
        total_p = max(1, (len(domains) + PER_PAGE - 1) // PER_PAGE)
        await query.edit_message_text(
            build_list_msg(domains, page), parse_mode="HTML",
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
            build_report_msg(results, page, title), parse_mode="HTML",
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
        logger.info(f"Auto check aktif setiap {s.get('interval_minutes')} menit.")
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
