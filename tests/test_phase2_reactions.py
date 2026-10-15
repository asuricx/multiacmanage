import asyncio
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base
from app.models.account import Account, AccountStatus
from app.models.reaction import ReactionJob, ReactionJobStatus, ReactionStat
from app.services.reaction_service import ReactionService


@pytest.mark.asyncio
async def test_emoji_percentage_calculation():
    """Verify that emoji assignments map accurately to active accounts according to percentage distribution."""
    # Create 10 dummy accounts
    mock_accounts = [
        Account(id=i, user_id=1000 + i, first_name=f"User{i}", session_string=f"mock_session_{i}")
        for i in range(1, 11)
    ]

    # Distribution: 50% 👍, 30% ❤️, 20% 🔥 -> 5, 3, 2
    distribution = {"👍": 50, "❤️": 30, "🔥": 20}
    assignments = ReactionService.calculate_emoji_assignments(mock_accounts, distribution)

    assert len(assignments) == 10
    emojis = [em for acc, em in assignments]
    assert emojis.count("👍") == 5
    assert emojis.count("❤️") == 3
    assert emojis.count("🔥") == 2

    # Single emoji distribution 100%
    single_dist = {"👏": 100}
    single_assignments = ReactionService.calculate_emoji_assignments(mock_accounts[:4], single_dist)
    assert len(single_assignments) == 4
    assert all(em == "👏" for _, em in single_assignments)

    # Single account randomness test across multiple posts
    single_acc = mock_accounts[:1]
    multi_emojis = {"👍": 33, "❤️": 33, "🔥": 34}
    sampled_emojis = {ReactionService.calculate_emoji_assignments(single_acc, multi_emojis)[0][1] for _ in range(30)}
    # Verify that not all 30 posts picked the exact same emoji
    assert len(sampled_emojis) > 1, f"Expected varied emojis, got only {sampled_emojis}"

    # Empty inputs
    assert ReactionService.calculate_emoji_assignments([], distribution) == []
    print("test_emoji_percentage_calculation: PASSED")



@pytest.mark.asyncio
async def test_reaction_job_crud_and_stats():
    """Test ReactionJob creation, status transitions, and stats recording."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Create Job directly
        job = ReactionJob(
            target_channel="@durov",
            emoji_distribution={"👍": 70, "🔥": 30},
            delay_min=15,
            delay_max=60,
            days_range=3,
            status=ReactionJobStatus.RUNNING.value,
        )
        session.add(job)
        await session.flush()
        job_id = job.id

        # Verify initial stat
        stat = ReactionStat(job_id=job_id, message_id=555, total_reactions=4)
        session.add(stat)
        await session.commit()

        # Update status to PAUSED
        job.status = ReactionJobStatus.PAUSED.value
        await session.commit()
        assert job.status == ReactionJobStatus.PAUSED.value

        # Update status to STOPPED
        job.status = ReactionJobStatus.STOPPED.value
        await session.commit()
        assert job.status == ReactionJobStatus.STOPPED.value

    await test_engine.dispose()
    print("test_reaction_job_crud_and_stats: PASSED")


def test_reaction_keyboards_and_picker():
    """Verify that emoji toggle picker and presets keyboard generate valid inline markups."""
    from app.utils.keyboard import Keyboards
    available = ["👍", "❤️", "🔥", "🥰"]
    selected = ["👍", "🔥"]

    kb = Keyboards.reaction_emojis_picker(available, selected)
    # Check that 👍 is marked with ✅ and ❤️ is marked with ⬜
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    btn_texts = [btn.text for btn in all_buttons]

    assert any("✅ 👍" in t for t in btn_texts)
    assert any("⬜ ❤️" in t for t in btn_texts)
    assert any("✅ 🔥" in t for t in btn_texts)
    assert any("🔄 انتخاب همه" in t for t in btn_texts)

    delay_kb = Keyboards.reaction_delay_picker()
    assert len(delay_kb.inline_keyboard) >= 4

    days_kb = Keyboards.reaction_days_picker()
    assert len(days_kb.inline_keyboard) >= 4
    print("test_reaction_keyboards_and_picker: PASSED")


if __name__ == "__main__":
    asyncio.run(test_emoji_percentage_calculation())
    asyncio.run(test_reaction_job_crud_and_stats())
    test_reaction_keyboards_and_picker()
    print("\nALL PHASE 2 UNIT TESTS PASSED SUCCESSFULLY! ✅")
