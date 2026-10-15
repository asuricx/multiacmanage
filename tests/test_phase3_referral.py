import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base
from app.models.account import Account, AccountStatus
from app.models.referral import ReferralJoinJob, ReferralJobStatus, JoinLog, JoinLogStatus
from app.services.referral_service import ReferralService
from app.utils.keyboard import Keyboards


def test_referral_url_and_param_parsing():
    """Verify parsing bot username and referral parameters from links and text."""
    # 1. Full HTTPS Telegram link with ?start=
    bot1, param1 = ReferralService.parse_bot_and_param("https://t.me/DogesBot?start=r_123456")
    assert bot1 == "DogesBot"
    assert param1 == "r_123456"

    # 2. Link with ?startapp=
    bot2, param2 = ReferralService.parse_bot_and_param("t.me/tapswap_bot?startapp=ref_abc")
    assert bot2 == "tapswap_bot"
    assert param2 == "ref_abc"

    # 3. Simple username with @
    bot3, param3 = ReferralService.parse_bot_and_param("@MajorBot")
    assert bot3 == "MajorBot"
    assert param3 is None

    # 4. Space-separated text
    bot4, param4 = ReferralService.parse_bot_and_param("major_bot ref_999")
    assert bot4 == "major_bot"
    assert param4 == "ref_999"

    print("test_referral_url_and_param_parsing: PASSED")


@pytest.mark.asyncio
async def test_referral_job_crud_and_status():
    """Verify ReferralJoinJob creation and status transitions in SQLite memory DB."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        job = ReferralJoinJob(
            bot_username="CatizenBot",
            start_param="r_cat_123",
            delay_seconds=45,
            status=ReferralJobStatus.RUNNING.value,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

        assert job.id is not None
        assert job.status == ReferralJobStatus.RUNNING.value

        # Update status to PAUSED
        job.status = "PAUSED"
        await session.commit()
        assert job.status == "PAUSED"

        # Update status to COMPLETED
        job.status = ReferralJobStatus.COMPLETED.value
        await session.commit()
        assert job.status == ReferralJobStatus.COMPLETED.value

    await test_engine.dispose()
    print("test_referral_job_crud_and_status: PASSED")


@pytest.mark.asyncio
async def test_eligible_unused_accounts_and_duplicate_prevention():
    """Verify that accounts that have already started a target bot are never duplicated."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Create 3 active accounts
        acc1 = Account(id=1, user_id=101, session_string="s1", status=AccountStatus.ACTIVE.value)
        acc2 = Account(id=2, user_id=102, session_string="s2", status=AccountStatus.ACTIVE.value)
        acc3 = Account(id=3, user_id=103, session_string="s3", status=AccountStatus.ACTIVE.value)
        session.add_all([acc1, acc2, acc3])

        # Create previous job on @target_bot
        job_prev = ReferralJoinJob(id=1, bot_username="target_bot", start_param="p1", status=ReferralJobStatus.COMPLETED.value)
        session.add(job_prev)
        await session.flush()

        # Account 1 previously SUCCEEDED
        log1 = JoinLog(job_id=job_prev.id, account_id=acc1.id, status=JoinLogStatus.SUCCESS.value)
        # Account 2 previously FAILED
        log2 = JoinLog(job_id=job_prev.id, account_id=acc2.id, status=JoinLogStatus.FAILED.value)
        session.add_all([log1, log2])
        await session.commit()

        # Create a new job on same @target_bot
        job_new = ReferralJoinJob(id=2, bot_username="target_bot", start_param="p2", status=ReferralJobStatus.RUNNING.value)
        session.add(job_new)
        await session.commit()

        # Query eligible accounts
        from sqlalchemy import select
        used_stmt = (
            select(JoinLog.account_id)
            .join(ReferralJoinJob, JoinLog.job_id == ReferralJoinJob.id)
            .where(
                ReferralJoinJob.bot_username == "target_bot",
                JoinLog.status == JoinLogStatus.SUCCESS.value,
            )
        )
        used_ids = (await session.execute(used_stmt)).scalars().all()
        assert 1 in used_ids
        assert 2 not in used_ids
        assert 3 not in used_ids

        eligible_stmt = (
            select(Account)
            .where(
                Account.status == AccountStatus.ACTIVE.value,
                Account.id.notin_(used_ids) if used_ids else True,
            )
        )
        eligible = (await session.execute(eligible_stmt)).scalars().all()
        eligible_ids = [a.id for a in eligible]

        # Account 1 MUST be excluded, Accounts 2 and 3 MUST be included!
        assert 1 not in eligible_ids
        assert 2 in eligible_ids
        assert 3 in eligible_ids

    await test_engine.dispose()
    print("test_eligible_unused_accounts_and_duplicate_prevention: PASSED")


def test_referral_keyboards():
    """Verify referral keyboards generation."""
    m_kb = Keyboards.referral_menu()
    assert len(m_kb.inline_keyboard) == 3

    d_kb = Keyboards.referral_delay_picker()
    assert len(d_kb.inline_keyboard) >= 5

    dummy_job = ReferralJoinJob(id=1, bot_username="TestBot", start_param="p1", delay_seconds=30, status="RUNNING")
    j_kb = Keyboards.referral_job_details(dummy_job, {"total": 5, "success": 2})
    assert len(j_kb.inline_keyboard) >= 3

    l_kb = Keyboards.referral_jobs_list([dummy_job], 1, 1)
    assert len(l_kb.inline_keyboard) >= 2
    print("test_referral_keyboards: PASSED")


def test_random_timing_and_duration_distribution():
    """Verify time window calculations, Persian numerals and random delay parser."""
    # 1. 100 accounts in 60 minutes (1 hour)
    d_min, d_max = ReferralService.calculate_delays_from_duration(accounts_count=100, duration_minutes=60)
    # Average is 36s (3600 / 100) -> min=18, max=54 -> (18 + 54)/2 = exactly 36s
    assert d_min == 18
    assert d_max == 54
    expected_avg = (d_min + d_max) / 2
    assert expected_avg == 36.0

    # 2. Parse '1h', '1 hour', '1 ساعت', '۱ ساعت' (Persian digits)
    parsed_1h = ReferralService.parse_timing_input("1h", accounts_count=100)
    assert parsed_1h == (18, 54, 60)

    parsed_fa_hour = ReferralService.parse_timing_input("1 ساعت", accounts_count=100)
    assert parsed_fa_hour == (18, 54, 60)

    parsed_fa_digits = ReferralService.parse_timing_input("۱ ساعت", accounts_count=100)
    assert parsed_fa_digits == (18, 54, 60)

    # 3. Parse range '20-80', '20 تا 80', '۲۰-۸۰'
    parsed_range = ReferralService.parse_timing_input("20-80")
    assert parsed_range == (20, 80, None)

    parsed_range_fa = ReferralService.parse_timing_input("20 تا 80")
    assert parsed_range_fa == (20, 80, None)

    parsed_range_fa_digits = ReferralService.parse_timing_input("۲۰-۸۰")
    assert parsed_range_fa_digits == (20, 80, None)

    # 4. Parse single number '45' and '۴۵'
    parsed_single = ReferralService.parse_timing_input("45")
    assert parsed_single is not None
    assert parsed_single[0] == 36
    assert parsed_single[1] == 54
    assert parsed_single[2] is None

    parsed_single_fa = ReferralService.parse_timing_input("۴۵")
    assert parsed_single_fa == parsed_single

    # 5. Invalid input
    assert ReferralService.parse_timing_input("invalid_text") is None
    print("test_random_timing_and_duration_distribution: PASSED")


if __name__ == "__main__":
    test_referral_url_and_param_parsing()
    asyncio.run(test_referral_job_crud_and_status())
    asyncio.run(test_eligible_unused_accounts_and_duplicate_prevention())
    test_referral_keyboards()
    test_random_timing_and_duration_distribution()
    print("\nALL PHASE 3 REFERRAL UNIT TESTS PASSED SUCCESSFULLY! ✅")
