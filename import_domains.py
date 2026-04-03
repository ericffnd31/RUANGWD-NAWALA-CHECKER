#!/usr/bin/env python3
"""
Script import domain massal ke database Nawala Bot.
Jalankan SEBELUM atau SAAT bot sedang tidak aktif.

Cara pakai:
  python import_domains.py links.txt
  python import_domains.py links.txt --check   (langsung cek DNS juga)
"""

import sys
import os
import asyncio
import argparse
from datetime import datetime

# Pastikan path benar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from nawala_checker import NawalaChecker, extract_domain


def parse_links(filepath: str) -> list[tuple[str, str]]:
    """
    Baca file dan kembalikan list (domain_name, full_url).
    Lewati baris kosong dan komentar (#).
    """
    results = []
    seen_domains = set()

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            url = line.strip().replace("\r", "")
            if not url or url.startswith("#"):
                continue

            full_url = url.replace("https://", "").replace("http://", "").rstrip("/")
            domain_name = extract_domain(full_url)

            if not domain_name:
                continue

            if domain_name in seen_domains:
                print(f"  [SKIP DUPLIKAT] {full_url}")
                continue

            seen_domains.add(domain_name)
            results.append((domain_name, full_url))

    return results


async def run_import(filepath: str, do_check: bool):
    db = Database()
    db.init_db()
    checker = NawalaChecker() if do_check else None

    entries = parse_links(filepath)
    print(f"\n📋 Total link ditemukan : {len(entries)}")
    print("=" * 50)

    added = 0
    skipped = 0
    checked_blocked = 0
    checked_safe = 0

    for domain_name, full_url in entries:
        if db.domain_exists(domain_name):
            print(f"  ⚠️  SKIP (sudah ada) : {full_url}")
            skipped += 1
            continue

        db.add_domain(domain_name, full_url)
        added += 1

        if do_check and checker:
            blocked = await checker.check(domain_name)
            db.update_domain_status_by_name(domain_name, blocked)
            icon = "🔴" if blocked else "🟢"
            status = "BLOCK" if blocked else "AMAN"
            if blocked:
                checked_blocked += 1
            else:
                checked_safe += 1
            print(f"  {icon} {status:6s} : {full_url}")
        else:
            print(f"  ✅ DITAMBAHKAN : {full_url}")

    print("=" * 50)
    print(f"✅ Ditambahkan : {added}")
    print(f"⏭️  Dilewati    : {skipped}")
    if do_check:
        print(f"🟢 Aman        : {checked_safe}")
        print(f"🔴 Diblokir    : {checked_blocked}")
    print(f"\n🎉 Import selesai! Total domain di DB: {db.get_domain_count()}")


def main():
    parser = argparse.ArgumentParser(description="Import domain massal ke Nawala Bot DB")
    parser.add_argument("file", help="Path file txt berisi daftar link/domain")
    parser.add_argument("--check", action="store_true", help="Langsung cek DNS Nawala setelah import")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"❌ File tidak ditemukan: {args.file}")
        sys.exit(1)

    print(f"📂 Membaca file: {args.file}")
    if args.check:
        print("🔍 Mode: Import + Cek DNS Nawala")
    else:
        print("📥 Mode: Import saja (tanpa cek DNS)")

    asyncio.run(run_import(args.file, args.check))


if __name__ == "__main__":
    main()
