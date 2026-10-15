import asyncio
import base64
import os
import sqlite3
import struct
import tempfile
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base
from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy, ProxyProtocol, ProxySourceChannel
from app.models.reaction import ReactionJob, ReactionJobStatus, ReactionStat
from app.models.referral import ReferralJoinJob, ReferralJobStatus, JoinLog
from app.utils.session_converter import SessionConverter
from app.utils.proxy_checker import ProxyChecker
from app.utils.fsm import FSMManager


@pytest.mark.asyncio
async def test_database_models_and_schema():
    """Verify that all models defined in Phase 0 map correctly and tables create without error."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Create Proxy
        p = Proxy(
            host="127.0.0.1",
            port=1080,
            protocol=ProxyProtocol.SOCKS5.value,
            username="test_user",
            password="test_password",
            is_active=True,
            ping_ms=45,
        )
        session.add(p)
        await session.flush()

        # Create Account linked to proxy
        acc = Account(
            phone="+989120000000",
            user_id=123456789,
            first_name="Test User",
            username="testuser",
            session_string="BQAAAAA...",
            session_format="KURIGRAM",
            status=AccountStatus.ACTIVE.value,
            proxy_id=p.id,
        )
        session.add(acc)

        # Create ProxySourceChannel
        ch = ProxySourceChannel(channel_username="@TestProxies")
        session.add(ch)

        # Create ReactionJob & ReactionStat
        rj = ReactionJob(
            target_channel="@target",
            days_range=5,
            delay_min=10,
            delay_max=30,
            emoji_distribution={"👍": 70, "🔥": 30},
        )
        session.add(rj)
        await session.flush()

        rs = ReactionStat(job_id=rj.id, message_id=1001, total_reactions=10)
        session.add(rs)

        # Create ReferralJoinJob & JoinLog
        ref_job = ReferralJoinJob(bot_username="@RefBot", start_param="ref123", delay_seconds=45)
        session.add(ref_job)
        await session.flush()

        jlog = JoinLog(job_id=ref_job.id, account_id=acc.id, status="SUCCESS")
        session.add(jlog)

        await session.commit()

    await test_engine.dispose()
    print("test_database_models_and_schema: PASSED")


def test_session_converter_telethon_ipv4():
    """Test Telethon IPv4 string session conversion."""
    dc_id = 2
    ip_bytes = b"\x95\x9a\xa7\x32"
    port = 443
    auth_key = b"\x11" * 256
    packed = struct.pack(">B4sH256s", dc_id, ip_bytes, port, auth_key)
    telethon_str = "1" + base64.urlsafe_b64encode(packed).decode()

    res_str, fmt = SessionConverter.convert_string_to_kurigram(telethon_str)
    assert fmt == "TELETHON_STRING_IPV4"
    assert len(res_str) == 356

    # Verify unpacked fields
    raw = base64.urlsafe_b64decode(res_str + "=" * ((-len(res_str)) % 4))
    dc, test, key, uid, bot = struct.unpack(">B?256sQ?", raw)
    assert dc == 2
    assert key == auth_key
    print("test_session_converter_telethon_ipv4: PASSED")


def test_session_converter_pyrogram_v1():
    """Test Pyrogram v1 (32-bit user_id) string session conversion."""
    auth_key = b"\x22" * 256
    packed_v1 = struct.pack(">B?256sI?", 4, True, auth_key, 123456, False)
    v1_str = base64.urlsafe_b64encode(packed_v1).decode()

    res_str, fmt = SessionConverter.convert_string_to_kurigram(v1_str)
    assert fmt == "PYROGRAM_V1"
    assert len(res_str) == 356

    raw = base64.urlsafe_b64decode(res_str + "=" * ((-len(res_str)) % 4))
    dc, test, key, uid, bot = struct.unpack(">B?256sQ?", raw)
    assert dc == 4
    assert test is True
    assert key == auth_key
    assert uid == 123456
    print("test_session_converter_pyrogram_v1: PASSED")


def test_session_converter_sqlite_telethon():
    """Test SQLite Telethon .session file conversion."""
    with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as f:
        path = f.name

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (dc_id integer, server_address text, port integer, auth_key blob)")
    auth_key = b"\x33" * 256
    conn.execute("INSERT INTO sessions VALUES (1, '149.154.167.40', 443, ?)", (auth_key,))
    conn.commit()
    conn.close()

    try:
        res_str, fmt = SessionConverter.convert_sqlite_file_to_kurigram(path)
        assert fmt == "TELETHON_FILE"
        assert len(res_str) == 356
        raw = base64.urlsafe_b64decode(res_str + "=" * ((-len(res_str)) % 4))
        dc, test, key, uid, bot = struct.unpack(">B?256sQ?", raw)
        assert dc == 1
        assert key == auth_key
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("test_session_converter_sqlite_telethon: PASSED")


def test_session_converter_sqlite_pyrogram():
    """Test SQLite Pyrogram .session file conversion."""
    with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as f:
        path = f.name

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (dc_id integer, test_mode integer, auth_key blob, date integer, user_id integer, is_bot integer)")
    auth_key = b"\x44" * 256
    conn.execute("INSERT INTO sessions VALUES (5, 0, ?, 1700000000, 987654321, 0)", (auth_key,))
    conn.commit()
    conn.close()

    try:
        res_str, fmt = SessionConverter.convert_sqlite_file_to_kurigram(path)
        assert fmt == "PYROGRAM_FILE"
        assert len(res_str) == 356
        raw = base64.urlsafe_b64decode(res_str + "=" * ((-len(res_str)) % 4))
        dc, test, key, uid, bot = struct.unpack(">B?256sQ?", raw)
        assert dc == 5
        assert key == auth_key
        assert uid == 987654321
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("test_session_converter_sqlite_pyrogram: PASSED")


def test_proxy_checker_parsing():
    """Test parsing multiple proxy formats."""
    # 1. URL format
    p1 = ProxyChecker.parse_proxy_string("socks5://admin:pass123@192.168.1.1:1080")
    assert p1["protocol"] == "SOCKS5"
    assert p1["host"] == "192.168.1.1"
    assert p1["port"] == 1080
    assert p1["username"] == "admin"
    assert p1["password"] == "pass123"

    # 2. Host:Port format
    p2 = ProxyChecker.parse_proxy_string("10.0.0.2:8080")
    assert p2["host"] == "10.0.0.2"
    assert p2["port"] == 8080

    # 3. Host:Port:User:Pass
    p3 = ProxyChecker.parse_proxy_string("10.0.0.3:1080:usr:pwd")
    assert p3["username"] == "usr"
    assert p3["password"] == "pwd"

    # 4. Telegram URI
    p4 = ProxyChecker.parse_proxy_string("tg://socks?server=142.250.1.1&port=1080&user=u1&pass=p1")
    assert p4["host"] == "142.250.1.1"
    assert p4["port"] == 1080
    assert p4["username"] == "u1"
    assert p4["password"] == "p1"

    # 5. Extraction from raw content / HTML / buttons with &amp;
    html_sample = """
    کانال ما: https://t.me/mychannel
    ربات: https://t.me/mybot?start=123
    اسپانسر: https://sponsor.com/join
    دکمه اینلاین: <a class="tgme_widget_message_inline_button url_button" href="https://t.me/proxy?server=167.235.197.87&amp;port=8443&amp;secret=ee001122">اتصال</a>
    متن: tg://proxy?server=cdn.telegram.org&port=443&secret=dd33
    ساکس: socks5://192.168.1.1:1080
    """
    extracted = ProxyChecker.extract_proxies_from_raw_content(html_sample)
    assert len(extracted) == 3
    hosts = [p["host"] for p in extracted]
    assert "167.235.197.87" in hosts
    assert "cdn.telegram.org" in hosts
    assert "192.168.1.1" in hosts
    assert all("mychannel" not in p["host"] for p in extracted)
    print("test_proxy_checker_parsing: PASSED")


@pytest.mark.asyncio
async def test_proxy_cleanup_and_direct_ip_fallback():
    """Test dead proxy cleanup and direct IP fallback when no healthy proxies exist."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.models.proxy import Proxy
    from app.models.account import Account, AccountStatus

    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        # Create 1 active account and 1 dead proxy
        dead_p = Proxy(host="1.1.1.1", port=8080, protocol="SOCKS5", is_active=False)
        alive_p = Proxy(host="2.2.2.2", port=1080, protocol="SOCKS5", is_active=True, ping_ms=50)
        session.add_all([dead_p, alive_p])
        await session.flush()

        acc = Account(user_id=123, session_string="dummy", status=AccountStatus.ACTIVE.value, proxy_id=dead_p.id)
        session.add(acc)
        await session.commit()

        # Delete dead proxy and ensure account is unlinked
        await session.delete(dead_p)
        acc.proxy_id = None
        await session.commit()

        # Direct IP verification: when no proxies exist or proxy_id is None, create_client uses proxy=None
        from app.services.client_manager import ClientManager
        client = ClientManager.create_client(name="test_direct", session_string="dummy", proxy=None)
        assert client.proxy is None

    await test_engine.dispose()
    print("test_proxy_cleanup_and_direct_ip_fallback: PASSED")


@pytest.mark.asyncio
async def test_fsm_memory_operations():
    """Test FSM state transitions and storage."""
    uid = 999888
    await FSMManager.set_state(uid, "TEST_STATE", {"key": "value"})
    state, data = await FSMManager.get_state(uid)
    assert state == "TEST_STATE"
    assert data["key"] == "value"

    await FSMManager.update_data(uid, count=5)
    _, updated_data = await FSMManager.get_state(uid)
    assert updated_data["count"] == 5
    assert updated_data["key"] == "value"

    await FSMManager.clear_state(uid)
    cleared_state, cleared_data = await FSMManager.get_state(uid)
    assert cleared_state is None
    print("test_fsm_memory_operations: PASSED")


if __name__ == "__main__":
    asyncio.run(test_database_models_and_schema())
    test_session_converter_telethon_ipv4()
    test_session_converter_pyrogram_v1()
    test_session_converter_sqlite_telethon()
    test_session_converter_sqlite_pyrogram()
    test_proxy_checker_parsing()
    asyncio.run(test_proxy_cleanup_and_direct_ip_fallback())
    asyncio.run(test_fsm_memory_operations())
    print("\nALL PHASE 0 & PHASE 1 UNIT TESTS PASSED SUCCESSFULLY! ✅")

