import os

# Token bot Telegram dari @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "MASUKKAN_TOKEN_BOT_DISINI")

# Interval default pengecekan otomatis (dalam menit)
DEFAULT_INTERVAL_MINUTES = int(os.getenv("DEFAULT_INTERVAL", "30"))

# Judul default bot (tampil di header laporan)
BOT_TITLE = os.getenv("BOT_TITLE", "RUANGWD NAWALA CHECKER")
