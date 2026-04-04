"""
Nawala Checker — DNS (domain) + HTTP (IP address)
"""

import re
import socket
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

NAWALA_BLOCK_IPS   = {"180.131.144.144", "180.131.145.254"}
NAWALA_DNS_SERVERS = ["180.131.144.144", "180.131.145.254"]

NAWALA_KEYWORDS = [
    "nawala", "diblokir", "internet positif", "internetpositif",
    "info.nawala", "blocked by",
]

IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def is_ip_address(text: str) -> bool:
    return bool(IP_RE.match(text.strip()))


def extract_domain(url: str) -> str:
    url = url.strip()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0].split("?")[0].split("#")[0]
    return url.lower()


def _check_domain_dns(domain: str) -> bool:
    """Cek domain via DNS Nawala — SYNC (dijalankan di executor)."""
    try:
        import dns.resolver, dns.exception
        resolver = dns.resolver.Resolver()
        resolver.nameservers = NAWALA_DNS_SERVERS
        resolver.timeout  = 5
        resolver.lifetime = 8
        answers = resolver.resolve(domain, "A")
        for rdata in answers:
            if str(rdata) in NAWALA_BLOCK_IPS:
                return True
        return False
    except Exception as e:
        logger.warning(f"DNS check {domain}: {e}")
        return False


def _check_ip_http(ip: str) -> bool:
    """Cek IP via HTTP — SYNC (dijalankan di executor)."""
    for scheme in ("http", "https"):
        try:
            req = urllib.request.Request(
                f"{scheme}://{ip}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read(8192).decode("utf-8", errors="ignore").lower()
                final_url = resp.geturl().lower()
                for kw in NAWALA_KEYWORDS:
                    if kw in body or kw in final_url:
                        logger.info(f"IP {ip} DIBLOKIR (kw: {kw})")
                        return True
                return False
        except Exception as e:
            logger.debug(f"HTTP {scheme}://{ip} → {e}")
            continue
    return False


class NawalaChecker:
    async def check(self, target: str) -> bool:
        """
        Cek apakah domain/IP diblokir Nawala.
        True = DIBLOKIR, False = AMAN
        """
        import asyncio
        loop = asyncio.get_running_loop()
        if is_ip_address(target):
            return await loop.run_in_executor(None, _check_ip_http, target)
        else:
            return await loop.run_in_executor(None, _check_domain_dns, target)
