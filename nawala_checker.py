"""
Nawala + Trustpositif Checker
- Domain : DNS via Nawala (180.131.144.144) + DNS via Trustpositif (8.8.8.8 redirect check)
- IP     : HTTP request, deteksi halaman blokir
"""

import re
import logging
import urllib.request

logger = logging.getLogger(__name__)

# ── Nawala ────────────────────────────────────────────────────────────────────
NAWALA_DNS      = ["180.131.144.144", "180.131.145.254"]
NAWALA_BLOCK_IP = {"180.131.144.144", "180.131.145.254"}

# ── Trustpositif / Internet Positif ──────────────────────────────────────────
# Saat domain diblokir Trustpositif, DNS Telkom/ISP mengarah ke:
TRUST_BLOCK_IP  = {
    "36.86.63.185",   # trustpositif.kominfo.go.id (lama)
    "203.0.113.0",    # placeholder Kominfo
    "114.137.65.130", # Telkom redirect
    "103.7.30.57",    # XL redirect
    "180.131.144.144","180.131.145.254",  # Nawala juga
}
TRUST_DNS       = ["114.114.114.114", "8.8.8.8"]  # DNS publik untuk crosscheck

# ── Kata kunci halaman blokir (untuk IP/HTTP) ─────────────────────────────────
BLOCK_KEYWORDS = [
    "nawala", "diblokir", "internet positif", "internetpositif",
    "trustpositif", "kominfo", "info.nawala", "blocked by",
    "situs ini diblokir", "positif.go.id",
]

IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def is_ip_address(text: str) -> bool:
    return bool(IP_RE.match(text.strip()))


def extract_domain(url: str) -> str:
    url = url.strip()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0].split("?")[0].split("#")[0]
    return url.lower()


# ── DNS resolver sync ─────────────────────────────────────────────────────────

def _dns_resolve(domain: str, nameservers: list) -> set:
    """Resolve domain ke set IP menggunakan nameserver tertentu."""
    try:
        import dns.resolver, dns.exception
        r = dns.resolver.Resolver()
        r.nameservers = nameservers
        r.timeout = 5
        r.lifetime = 8
        answers = r.resolve(domain, "A")
        return {str(a) for a in answers}
    except Exception as e:
        logger.debug(f"DNS {nameservers[0]} → {domain}: {e}")
        return set()


def _check_domain_sync(domain: str) -> tuple[bool, str]:
    """
    Cek domain via DNS Nawala dan DNS publik.
    Returns (blocked: bool, reason: str)
    """
    # Cek via DNS Nawala
    nawala_ips = _dns_resolve(domain, NAWALA_DNS)
    if nawala_ips & NAWALA_BLOCK_IP:
        return True, "Nawala"

    # Cek via DNS publik — apakah IP sama dengan IP blokir
    public_ips = _dns_resolve(domain, TRUST_DNS)
    if public_ips & TRUST_BLOCK_IP:
        return True, "Trustpositif"

    return False, ""


# ── HTTP checker untuk IP ─────────────────────────────────────────────────────

def _check_ip_sync(ip: str) -> tuple[bool, str]:
    for scheme in ("http", "https"):
        try:
            req = urllib.request.Request(
                f"{scheme}://{ip}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                body      = resp.read(8192).decode("utf-8", errors="ignore").lower()
                final_url = resp.geturl().lower()
                for kw in BLOCK_KEYWORDS:
                    if kw in body or kw in final_url:
                        reason = "Trustpositif" if "trustpositif" in (body + final_url) else "Nawala/ISP"
                        return True, reason
                return False, ""
        except Exception as e:
            logger.debug(f"HTTP {scheme}://{ip}: {e}")
            continue
    return False, ""


# ── Public API ────────────────────────────────────────────────────────────────

class NawalaChecker:
    async def check(self, target: str) -> bool:
        """True = DIBLOKIR."""
        blocked, _ = await self.check_detail(target)
        return blocked

    async def check_detail(self, target: str) -> tuple[bool, str]:
        """Returns (blocked, reason) — reason: 'Nawala', 'Trustpositif', ''."""
        import asyncio
        loop = asyncio.get_running_loop()
        if is_ip_address(target):
            return await loop.run_in_executor(None, _check_ip_sync, target)
        else:
            return await loop.run_in_executor(None, _check_domain_sync, target)
