import asyncio
from datetime import datetime, timezone
import html
import logging
import re
from typing import List, Optional, Tuple, Dict
import aiohttp
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy, ProxyProtocol, ProxySourceChannel
from app.utils.proxy_checker import ProxyChecker
from app.services.client_manager import ClientManager

logger = logging.getLogger("ProxyService")



class ProxyService:
    """
    Manages the Proxy Pool: manual imports, scraper channels, health checking, and auto-rotation.
    """

    @classmethod
    async def add_manual_proxies(cls, text: str) -> Tuple[int, int, List[str]]:
        """
        Parses proxy strings from text, tests health, and stores healthy ones in DB.
        Returns: (added_count, failed_count, report_lines)
        """
        lines = text.strip().splitlines()
        added_count = 0
        failed_count = 0
        reports = []

        async with get_session() as db:
            for line in lines:
                parsed = ProxyChecker.parse_proxy_string(line)
                if not parsed:
                    continue

                # Check if already exists in DB
                stmt = select(Proxy).where(
                    Proxy.host == parsed["host"],
                    Proxy.port == parsed["port"],
                )
                existing = (await db.execute(stmt)).scalar_one_or_none()
                if existing:
                    reports.append(f"⚠️ `{parsed['host']}:{parsed['port']}` قبلاً در دیتابیس ثبت شده بود.")
                    continue

                # Perform live health test
                is_alive, ping, err = await ProxyChecker.check_proxy_health(parsed, timeout_seconds=6)
                new_proxy = Proxy(
                    host=parsed["host"],
                    port=parsed["port"],
                    protocol=parsed["protocol"],
                    username=parsed.get("username"),
                    password=parsed.get("password"),
                    secret=parsed.get("secret"),
                    is_active=is_alive,
                    ping_ms=ping if is_alive else None,
                    source="MANUAL",
                    last_checked_at=datetime.now(timezone.utc),
                )
                db.add(new_proxy)
                added_count += 1

                if is_alive:
                    reports.append(f"✅ `{parsed['host']}:{parsed['port']}` ({parsed['protocol']}) - سالم و متصل ({ping}ms)")
                else:
                    failed_count += 1
                    reports.append(f"⚠️ `{parsed['host']}:{parsed['port']}` ({parsed['protocol']}) - ثبت شد (فعلاً قطع: {err or 'تایم‌اوت'})")

        return added_count, failed_count, reports

    @classmethod
    async def get_paginated_proxies(cls, page: int = 1, page_size: int = 8) -> Tuple[List[Proxy], int, int]:
        """Returns paginated proxies list and total count."""
        async with get_session() as db:
            count_stmt = select(func.count(Proxy.id))
            total = (await db.execute(count_stmt)).scalar() or 0

            offset = (page - 1) * page_size
            stmt = select(Proxy).order_by(Proxy.is_active.desc(), Proxy.id.desc()).offset(offset).limit(page_size)
            proxies = (await db.execute(stmt)).scalars().all()

            total_pages = (total + page_size - 1) // page_size if total > 0 else 1
            return list(proxies), total, total_pages

    @classmethod
    async def get_proxy_by_id(cls, proxy_id: int) -> Optional[Proxy]:
        async with get_session() as db:
            stmt = select(Proxy).where(Proxy.id == proxy_id)
            return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def test_single_proxy(cls, proxy_id: int) -> Tuple[bool, Optional[int], Optional[str]]:
        """Tests health of a single proxy by ID and updates DB."""
        async with get_session() as db:
            stmt = select(Proxy).where(Proxy.id == proxy_id)
            proxy = (await db.execute(stmt)).scalar_one_or_none()
            if not proxy:
                return False, None, "پروکسی یافت نشد."

            p_dict = {
                "protocol": proxy.protocol,
                "host": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": proxy.password,
            }
            is_alive, ping, err = await ProxyChecker.check_proxy_health(p_dict)
            proxy.is_active = is_alive
            proxy.ping_ms = ping if is_alive else None
            proxy.last_checked_at = datetime.now(timezone.utc)
            if not is_alive:
                proxy.fail_count += 1
            else:
                proxy.fail_count = 0

            return is_alive, ping, err

    @classmethod
    async def test_all_proxies(cls) -> Tuple[int, int]:
        """Runs health-checks concurrently on all proxies in DB."""
        async with get_session() as db:
            stmt = select(Proxy)
            proxies = (await db.execute(stmt)).scalars().all()

        active_count = 0
        dead_count = 0

        async def _check_and_update(p_id: int):
            nonlocal active_count, dead_count
            alive, ping, _ = await cls.test_single_proxy(p_id)
            if alive:
                active_count += 1
            else:
                dead_count += 1

        tasks = [_check_and_update(p.id) for p in proxies]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return active_count, dead_count

    @classmethod
    async def delete_proxy(cls, proxy_id: int) -> bool:
        async with get_session() as db:
            stmt = select(Proxy).where(Proxy.id == proxy_id)
            proxy = (await db.execute(stmt)).scalar_one_or_none()
            if proxy:
                await db.delete(proxy)
                return True
            return False

    @classmethod
    async def rotate_proxy_for_account(cls, account_id: int) -> Optional[Proxy]:
        """
        Picks the best available active proxy (lowest latency or least loaded)
        and binds it to the specified account.
        """
        async with get_session() as db:
            # Get account
            acc_stmt = select(Account).where(Account.id == account_id)
            acc = (await db.execute(acc_stmt)).scalar_one_or_none()
            if not acc:
                return None

            # Find active proxies excluding currently assigned broken one
            p_stmt = select(Proxy).where(
                Proxy.is_active == True,
                Proxy.id != (acc.proxy_id or 0)
            ).order_by(Proxy.ping_ms.asc().nullslast()).limit(1)

            next_proxy = (await db.execute(p_stmt)).scalar_one_or_none()
            if next_proxy:
                acc.proxy_id = next_proxy.id
                return next_proxy
            return None

    @classmethod
    async def cleanup_dead_proxies(cls) -> int:
        """
        Deletes all non-functional/dead proxies from DB.
        Accounts using these proxies are reset to proxy_id = None (Direct host IP).
        """
        async with get_session() as db:
            stmt = select(Proxy).where(Proxy.is_active == False)
            dead_proxies = (await db.execute(stmt)).scalars().all()
            if not dead_proxies:
                return 0

            dead_ids = [p.id for p in dead_proxies]

            # Clear proxy_id on accounts pointing to dead proxies
            await db.execute(
                update(Account).where(Account.proxy_id.in_(dead_ids)).values(proxy_id=None)
            )

            # Delete dead proxies from proxies table
            await db.execute(
                delete(Proxy).where(Proxy.id.in_(dead_ids))
            )

            return len(dead_ids)

    @classmethod
    async def auto_assign_proxies(cls) -> Tuple[int, int]:
        """
        Assigns healthy proxies to all active accounts.
        If NO healthy proxies exist in the pool, sets account.proxy_id = None
        so all accounts cleanly fall back to direct connection using the server's main IP.
        Returns: (assigned_count, direct_ip_count)
        """
        async with get_session() as db:
            accs_stmt = select(Account).where(Account.status == AccountStatus.ACTIVE.value)
            accounts = list((await db.execute(accs_stmt)).scalars().all())
            if not accounts:
                return 0, 0

            p_stmt = select(Proxy).where(Proxy.is_active == True).order_by(Proxy.ping_ms.asc().nullslast())
            active_proxies = list((await db.execute(p_stmt)).scalars().all())

            # If NO healthy proxies exist: all accounts fall back to direct host IP
            if not active_proxies:
                for acc in accounts:
                    acc.proxy_id = None
                return 0, len(accounts)

            # Distribute healthy proxies across accounts
            assigned = 0
            for idx, acc in enumerate(accounts):
                chosen = active_proxies[idx % len(active_proxies)]
                acc.proxy_id = chosen.id
                assigned += 1

            return assigned, 0

    @classmethod
    async def scrape_proxies_from_channels(cls) -> Tuple[int, int]:
        """
        Scrapes public Telegram channels listed in ProxySourceChannel to discover new proxies.
        Extracts proxies from:
        1. Inline keyboard buttons (reply_markup.inline_keyboard)
        2. Text hyperlinks (entities)
        3. Message body / captions
        4. Web preview fallback (t.me/s/...) with HTML unescaping
        """
        DEFAULT_CHANNELS = ["@ProxyMTProto", "@TelMTProto", "@iPProxy"]
        async with get_session() as db:
            ch_stmt = select(ProxySourceChannel).where(ProxySourceChannel.is_enabled == True)
            channels = list((await db.execute(ch_stmt)).scalars().all())

            # Auto-seed defaults if list is empty
            if not channels:
                for def_ch in DEFAULT_CHANNELS:
                    db.add(ProxySourceChannel(channel_username=def_ch, is_enabled=True))
                await db.flush()
                channels = list((await db.execute(ch_stmt)).scalars().all())

        if not channels:
            return 0, 0

        # Retrieve one active account to scrape directly via Telegram MTProto client if possible
        async with get_session() as db:
            stmt = select(Account).options(selectinload(Account.proxy)).where(Account.status == AccountStatus.ACTIVE.value).limit(1)
            watcher_acc = (await db.execute(stmt)).scalar_one_or_none()

        found_candidates: List[Dict[str, any]] = []
        userbot_success = False

        if watcher_acc:
            try:
                client = ClientManager.create_client(
                    name="proxy_channel_scraper",
                    session_string=watcher_acc.session_string,
                    proxy=watcher_acc.proxy,
                )
                await client.connect()
                try:
                    for ch in channels:
                        uname = ch.channel_username.strip()
                        if not uname.startswith("@") and not uname.startswith("-100"):
                            uname = "@" + uname.lstrip("@")
                        try:
                            async for message in client.get_chat_history(uname, limit=25):
                                if not message:
                                    continue

                                # 1. Extract from Inline Keyboard Buttons
                                if message.reply_markup and hasattr(message.reply_markup, "inline_keyboard"):
                                    for row in message.reply_markup.inline_keyboard:
                                        for btn in row:
                                            btn_url = getattr(btn, "url", None)
                                            if btn_url:
                                                found_candidates.extend(ProxyChecker.extract_proxies_from_raw_content(btn_url))

                                # 2. Extract from formatted text hyperlinks (entities)
                                entities = (message.entities or []) + (message.caption_entities or [])
                                for ent in entities:
                                    ent_url = getattr(ent, "url", None)
                                    if ent_url:
                                        found_candidates.extend(ProxyChecker.extract_proxies_from_raw_content(ent_url))

                                # 3. Extract from text & caption
                                full_text = (message.text or "") + " " + (message.caption or "")
                                if full_text.strip():
                                    found_candidates.extend(ProxyChecker.extract_proxies_from_raw_content(full_text))

                            async with get_session() as update_db:
                                ch_obj = (await update_db.execute(
                                    select(ProxySourceChannel).where(ProxySourceChannel.id == ch.id)
                                )).scalar_one_or_none()
                                if ch_obj:
                                    ch_obj.last_scraped_at = datetime.now(timezone.utc)

                            userbot_success = True
                        except Exception as e:
                            logger.warning(f"MTProto scraper failed on channel {uname}: {e}")
                finally:
                    if client.is_connected:
                        await client.disconnect()
            except Exception as e:
                logger.warning(f"Could not initialize MTProto client for scraper: {e}")

        # If userbot didn't scrape or as complementary method, use HTTP Web Preview with HTML unescape
        if not userbot_success or len(found_candidates) == 0:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                for ch in channels:
                    uname = ch.channel_username.lstrip("@")
                    url = f"https://t.me/s/{uname}"
                    try:
                        async with session.get(url, timeout=10) as resp:
                            if resp.status == 200:
                                raw_html = await resp.text()
                                found_candidates.extend(ProxyChecker.extract_proxies_from_raw_content(raw_html))
                                async with get_session() as update_db:
                                    ch_obj = (await update_db.execute(
                                        select(ProxySourceChannel).where(ProxySourceChannel.id == ch.id)
                                    )).scalar_one_or_none()
                                    if ch_obj:
                                        ch_obj.last_scraped_at = datetime.now(timezone.utc)
                    except Exception as e:
                        logger.warning(f"Web scraper error on {url}: {e}")

        # Deduplicate candidates by (host, port)
        unique_proxies: Dict[Tuple[str, int], Dict[str, any]] = {}
        for p in found_candidates:
            key = (p["host"].lower(), p["port"])
            if key not in unique_proxies:
                unique_proxies[key] = p

        if not unique_proxies:
            return 0, 0

        # Concurrently health-check newly discovered proxies (limit to 30 per cycle)
        candidates_to_test = list(unique_proxies.values())[:30]
        added_count = 0

        async def _test_and_save(p_dict: Dict[str, any]):
            nonlocal added_count
            is_alive, ping, _ = await ProxyChecker.check_proxy_health(p_dict, timeout_seconds=4)
            if not is_alive:
                return

            async with get_session() as db:
                stmt = select(Proxy).where(Proxy.host == p_dict["host"], Proxy.port == p_dict["port"])
                existing = (await db.execute(stmt)).scalar_one_or_none()
                if existing:
                    existing.is_active = True
                    existing.ping_ms = ping
                    existing.last_checked_at = datetime.now(timezone.utc)
                    if p_dict.get("secret"):
                        existing.secret = p_dict["secret"]
                else:
                    new_p = Proxy(
                        host=p_dict["host"],
                        port=p_dict["port"],
                        protocol=p_dict["protocol"],
                        username=p_dict.get("username"),
                        password=p_dict.get("password"),
                        secret=p_dict.get("secret"),
                        is_active=True,
                        ping_ms=ping,
                        source="SCRAPER",
                        last_checked_at=datetime.now(timezone.utc),
                    )
                    db.add(new_p)
                    added_count += 1

        check_tasks = [_test_and_save(p) for p in candidates_to_test]
        if check_tasks:
            await asyncio.gather(*check_tasks, return_exceptions=True)

        return len(unique_proxies), added_count

    @classmethod
    async def sync_proxies_pipeline(cls) -> Dict[str, int]:
        """
        Master Synchronization Pipeline:
        1. Scrapes channels for fresh proxies (messages & inline buttons).
        2. Health-checks all proxies in pool.
        3. Removes all dead proxies from database.
        4. Connects active accounts to healthy proxies, or falls back to direct main IP.
        """
        # Step 1: Scrape
        found, added = await cls.scrape_proxies_from_channels()

        # Step 2: Test health of existing
        active, dead = await cls.test_all_proxies()

        # Step 3: Remove dead proxies
        deleted_dead = await cls.cleanup_dead_proxies()

        # Step 4: Auto-assign / fallback to main IP
        assigned, direct_ip = await cls.auto_assign_proxies()

        return {
            "found": found,
            "added": added,
            "active": active,
            "deleted_dead": deleted_dead,
            "assigned": assigned,
            "direct_ip": direct_ip,
        }


    @classmethod
    async def get_source_channels(cls) -> List[ProxySourceChannel]:
        async with get_session() as db:
            stmt = select(ProxySourceChannel).order_by(ProxySourceChannel.id.asc())
            return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def add_source_channel(cls, username: str) -> bool:
        clean_user = "@" + username.lstrip("@").strip()
        async with get_session() as db:
            stmt = select(ProxySourceChannel).where(ProxySourceChannel.channel_username == clean_user)
            if (await db.execute(stmt)).scalar_one_or_none():
                return False
            db.add(ProxySourceChannel(channel_username=clean_user, is_enabled=True))
            return True

    @classmethod
    async def delete_source_channel(cls, channel_id: int) -> bool:
        async with get_session() as db:
            stmt = select(ProxySourceChannel).where(ProxySourceChannel.id == channel_id)
            ch = (await db.execute(stmt)).scalar_one_or_none()
            if ch:
                await db.delete(ch)
                return True
            return False
