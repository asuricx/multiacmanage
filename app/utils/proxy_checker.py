import asyncio
import html
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp_socks import ProxyConnector

from app.core.config import settings
from app.models.proxy import ProxyProtocol


class ProxyChecker:
    """
    Utility for parsing, validating, and testing SOCKS5 / HTTP proxies against Telegram endpoints.
    """

    TELEGRAM_TEST_URL = "https://api.telegram.org"

    @classmethod
    def parse_proxy_string(cls, raw_line: str) -> Optional[Dict[str, any]]:
        """
        Parses various proxy formats into a standardized dictionary:
        {
            "protocol": "SOCKS5" | "HTTP",
            "host": str,
            "port": int,
            "username": Optional[str],
            "password": Optional[str]
        }
        """
        line = html.unescape(raw_line.strip())
        if not line or line.startswith("#"):
            return None

        # 1. Telegram URI format: tg://socks?server=... or https://t.me/socks?... or tg://proxy?... or https://t.me/proxy?...
        if "proxy?" in line or "socks?" in line:
            try:
                # Find the URL part within line
                match = re.search(r'(?:tg://|https?://t\.me/)(?:proxy|socks)\?[^\s"\'<>]+', line, re.IGNORECASE)
                url_to_parse = match.group(0).rstrip('.,;:\"\'') if match else line
                parsed = urlparse(url_to_parse)
                query = parse_qs(parsed.query)
                server = query.get("server", [None])[0]
                port = query.get("port", [None])[0]
                user = query.get("user", [None])[0]
                passwd = query.get("pass", [None])[0]
                secret = query.get("secret", [None])[0]
                if server and port and port.isdigit():
                    port_num = int(port)
                    if 1 <= port_num <= 65535:
                        proto = ProxyProtocol.MTPROTO.value if (secret or "proxy" in url_to_parse) else ProxyProtocol.SOCKS5.value
                        return {
                            "protocol": proto,
                            "host": server.strip(),
                            "port": port_num,
                            "username": user.strip() if user else None,
                            "password": passwd.strip() if passwd else None,
                            "secret": secret.strip() if secret else None,
                        }
            except Exception:
                pass

        # 2. Standard URL: socks5://user:pass@host:port or http://...
        if "://" in line:
            try:
                match = re.search(r'(socks5|http)://(?:([^:@\s]+):([^:@\s]+)@)?([a-zA-Z0-9.-]+):([0-9]{2,5})', line, re.IGNORECASE)
                if match:
                    scheme, user, passwd, host, port = match.groups()
                    port_num = int(port)
                    if 1 <= port_num <= 65535:
                        return {
                            "protocol": scheme.upper(),
                            "host": host.strip(),
                            "port": port_num,
                            "username": user if user else None,
                            "password": passwd if passwd else None,
                            "secret": None,
                        }
            except Exception:
                pass

        # 3. Delimited: host:port:username:password or host:port
        parts = line.split(":")
        if len(parts) == 2:
            host, port = parts[0].strip(), parts[1].strip()
            if port.isdigit():
                port_num = int(port)
                if 1 <= port_num <= 65535:
                    return {
                        "protocol": ProxyProtocol.SOCKS5.value,
                        "host": host,
                        "port": port_num,
                        "username": None,
                        "password": None,
                        "secret": None,
                    }
        elif len(parts) == 4:
            host, port, user, passwd = [p.strip() for p in parts]
            if port.isdigit():
                port_num = int(port)
                if 1 <= port_num <= 65535:
                    return {
                        "protocol": ProxyProtocol.SOCKS5.value,
                        "host": host,
                        "port": port_num,
                        "username": user if user else None,
                        "password": passwd if passwd else None,
                        "secret": None,
                    }

        return None

    @classmethod
    def extract_proxies_from_raw_content(cls, raw_content: str) -> List[Dict[str, any]]:
        """
        Extracts only valid proxies from text, HTML, or button URLs.
        Ignores generic channels, invite links, and non-proxy URLs.
        """
        if not raw_content:
            return []

        text = html.unescape(raw_content)
        proxies: List[Dict[str, any]] = []
        seen = set()

        # 1. Telegram MTProto / SOCKS links (tg:// and t.me)
        tg_pattern = r'(?:tg://|https?://t\.me/)(?:proxy|socks)\?[^\s"\'<>]+'
        for match in re.finditer(tg_pattern, text, re.IGNORECASE):
            url = match.group(0).rstrip('.,;:\"\'')
            try:
                parsed = urlparse(url)
                query = parse_qs(parsed.query)
                server = query.get("server", [None])[0]
                port = query.get("port", [None])[0]
                secret = query.get("secret", [None])[0]
                user = query.get("user", [None])[0]
                passwd = query.get("pass", [None])[0]

                if server and port and port.isdigit():
                    port_num = int(port)
                    if 1 <= port_num <= 65535:
                        key = (server.strip().lower(), port_num)
                        if key not in seen:
                            seen.add(key)
                            proto = (
                                ProxyProtocol.MTPROTO.value
                                if secret or "proxy" in parsed.path or "proxy" in parsed.scheme
                                else ProxyProtocol.SOCKS5.value
                            )
                            proxies.append({
                                "protocol": proto,
                                "host": server.strip(),
                                "port": port_num,
                                "username": user.strip() if user else None,
                                "password": passwd.strip() if passwd else None,
                                "secret": secret.strip() if secret else None,
                            })
            except Exception:
                continue

        # 2. Protocol URLs (socks5:// and http://)
        proto_pattern = r'(socks5|http)://(?:([^:@\s]+):([^:@\s]+)@)?([a-zA-Z0-9.-]+):([0-9]{2,5})'
        for match in re.finditer(proto_pattern, text, re.IGNORECASE):
            scheme, user, passwd, host, port = match.groups()
            if port and port.isdigit():
                port_num = int(port)
                if 1 <= port_num <= 65535 and not host.startswith(("t.me", "telegram.me", "localhost")):
                    key = (host.strip().lower(), port_num)
                    if key not in seen:
                        seen.add(key)
                        proxies.append({
                            "protocol": scheme.upper(),
                            "host": host.strip(),
                            "port": port_num,
                            "username": user.strip() if user else None,
                            "password": passwd.strip() if passwd else None,
                            "secret": None,
                        })

        return proxies

    @classmethod
    def format_proxy_url(cls, p: dict) -> str:
        """Constructs proxy connection URL for aiohttp-socks or requests."""
        proto = p.get("protocol", "SOCKS5").lower()
        host = p["host"]
        port = p["port"]
        user = p.get("username")
        passwd = p.get("password")

        if user and passwd:
            return f"{proto}://{user}:{passwd}@{host}:{port}"
        elif user:
            return f"{proto}://{user}@{host}:{port}"
        return f"{proto}://{host}:{port}"

    @classmethod
    async def check_proxy_health(
        cls,
        proxy_info: dict,
        timeout_seconds: Optional[int] = None,
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Tests the proxy connection against Telegram MTProto Datacenter and API.
        Returns: (is_alive, ping_ms, error_message)
        """
        timeout_val = timeout_seconds or settings.PROXY_HEALTH_CHECK_TIMEOUT
        proxy_url = cls.format_proxy_url(proxy_info)
        proto = proxy_info.get("protocol", "SOCKS5").upper()
        start_time = time.monotonic()

        # Method 1: MTProto proxy direct TCP handshake test
        if proto == "MTPROTO":
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(proxy_info["host"], proxy_info["port"]),
                    timeout=timeout_val,
                )
                ping_ms = max(int((time.monotonic() - start_time) * 1000), 1)
                writer.close()
                await writer.wait_closed()
                return True, ping_ms, None
            except asyncio.TimeoutError:
                return False, None, "تایم‌اوت در اتصال به سرور MTProto"
            except Exception as e:
                return False, None, f"خطا در اتصال MTProto: {str(e)[:50]}"

        # Method 2: SOCKS5 / HTTP Direct TCP MTProto DC check via python_socks
        try:
            from python_socks.async_.asyncio import Proxy as AsyncProxy
            proxy = AsyncProxy.from_url(proxy_url)
            # Telegram Production DC2
            sock = await asyncio.wait_for(
                proxy.connect("149.154.167.50", 443),
                timeout=timeout_val,
            )
            ping_ms = max(int((time.monotonic() - start_time) * 1000), 1)
            sock.close()
            return True, ping_ms, None
        except Exception:
            pass

        # Method 3: Fallback via aiohttp with remote DNS (socks5h / rdns)
        try:
            rdns_url = proxy_url.replace("socks5://", "socks5h://")
            connector = ProxyConnector.from_url(rdns_url, rdns=True)
            timeout = aiohttp.ClientTimeout(total=timeout_val, connect=timeout_val)

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            ) as session:
                async with session.get(cls.TELEGRAM_TEST_URL) as response:
                    ping_ms = max(int((time.monotonic() - start_time) * 1000), 1)
                    return True, ping_ms, None

        except asyncio.TimeoutError:
            return False, None, "تایم‌اوت در اتصال به سرور پروکسی"
        except Exception as e:
            err_msg = str(e)
            if "ProxyConnectionError" in err_msg or "Cannot connect" in err_msg or "Errno 111" in err_msg:
                return False, None, "عدم توانایی برقراری اتصال با سرور پروکسی"
            return False, None, f"خطای اتصال: {err_msg[:60]}"

    @classmethod
    def extract_proxies_from_text(cls, text: str) -> List[dict]:
        """Extracts and parses all potential proxy lines from raw text."""
        results = []
        for line in text.splitlines():
            parsed = cls.parse_proxy_string(line)
            if parsed:
                results.append(parsed)
        return results
