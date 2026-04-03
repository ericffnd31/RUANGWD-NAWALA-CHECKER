"""
Nawala DNS Checker
Mengecek apakah domain diblokir Nawala menggunakan DNS resolution.
"""

import asyncio
import re
import dns.resolver
import dns.exception
import logging

logger = logging.getLogger(__name__)

NAWALA_BLOCK_IPS = {"180.131.144.144", "180.131.145.254"}
NAWALA_DNS_SERVERS = ["180.131.144.144", "180.131.145.254"]


def extract_domain(url: str) -> str:
    """
    Ekstrak hostname dari URL lengkap.
    Contoh:
      mez.ink/ruangwd       → mez.ink
      https://example.com/  → example.com
      heylink.me/RUANGWD    → heylink.me
    """
    url = url.strip()
    url = re.sub(r'^https?://', '', url)   # hapus protokol
    url = url.split('/')[0]                # ambil bagian host saja
    url = url.split('?')[0]               # hapus query string
    url = url.split('#')[0]               # hapus fragment
    return url.lower()


class NawalaChecker:
    def __init__(self):
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = NAWALA_DNS_SERVERS
        self.resolver.timeout = 5
        self.resolver.lifetime = 8

    async def check(self, url_or_domain: str) -> bool:
        """
        Cek apakah domain/URL diblokir Nawala.
        Menerima full URL maupun domain saja.
        Returns True jika DIBLOKIR, False jika TIDAK DIBLOKIR.
        """
        domain = extract_domain(url_or_domain)
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._resolve, domain)
        except Exception as e:
            logger.warning(f"Error checking {domain}: {e}")
            return False

    def _resolve(self, domain: str) -> bool:
        try:
            answers = self.resolver.resolve(domain, "A")
            for rdata in answers:
                ip = str(rdata)
                logger.debug(f"{domain} → {ip}")
                if ip in NAWALA_BLOCK_IPS:
                    return True
            return False
        except dns.resolver.NXDOMAIN:
            return False
        except dns.resolver.NoAnswer:
            return False
        except dns.exception.Timeout:
            logger.warning(f"DNS timeout: {domain}")
            return False
        except Exception as e:
            logger.error(f"DNS error {domain}: {e}")
            return False
