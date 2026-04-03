"""
Nawala DNS Checker
Mengecek apakah domain diblokir oleh Nawala menggunakan DNS resolution.
Nawala menggunakan DNS 180.131.144.144 dan 180.131.145.254.
Jika domain diblokir, DNS akan mengarahkan ke IP Nawala tersebut.
"""

import asyncio
import dns.resolver
import dns.exception
import logging

logger = logging.getLogger(__name__)

# IP server Nawala yang digunakan untuk memblokir domain
NAWALA_BLOCK_IPS = {
    "180.131.144.144",
    "180.131.145.254",
}

# DNS server Nawala
NAWALA_DNS_SERVERS = ["180.131.144.144", "180.131.145.254"]


class NawalaChecker:
    def __init__(self):
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = NAWALA_DNS_SERVERS
        self.resolver.timeout = 5
        self.resolver.lifetime = 8

    async def check(self, domain: str) -> bool:
        """
        Cek apakah domain diblokir Nawala.
        Returns True jika DIBLOKIR, False jika TIDAK DIBLOKIR.
        """
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._resolve, domain)
            return result
        except Exception as e:
            logger.warning(f"Error checking {domain}: {e}")
            return False

    def _resolve(self, domain: str) -> bool:
        """Resolve DNS menggunakan server Nawala dan cek IP."""
        try:
            answers = self.resolver.resolve(domain, "A")
            for rdata in answers:
                ip = str(rdata)
                logger.debug(f"{domain} → {ip}")
                if ip in NAWALA_BLOCK_IPS:
                    return True  # DIBLOKIR
            return False  # TIDAK DIBLOKIR
        except dns.resolver.NXDOMAIN:
            # Domain tidak ada → bukan karena Nawala
            return False
        except dns.resolver.NoAnswer:
            return False
        except dns.exception.Timeout:
            logger.warning(f"DNS timeout untuk {domain}")
            return False
        except Exception as e:
            logger.error(f"DNS error untuk {domain}: {e}")
            return False
