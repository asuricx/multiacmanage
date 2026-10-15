from datetime import datetime, timezone
import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message
from sqlalchemy import select, func

from app.core.database import get_session
from app.handlers.start import admin_filter
from app.models.account import Account, AccountStatus
from app.models.referral import ReferralJoinJob, ReferralJobStatus, JoinLog, JoinLogStatus
from app.services.referral_service import ReferralService
from app.tasks.referral_worker import ReferralWorker
from app.utils.fsm import FSMManager
from app.utils.keyboard import Keyboards

logger = logging.getLogger("ReferralHandler")

REFERRAL_STATES = {
    "WAIT_REF_BOT",
    "WAIT_REF_PARAM",
    "WAIT_REF_CUSTOM_DELAY",
}


def register_referral_handlers(app: Client):

    # 1. Main Referral Menu
    @app.on_callback_query(filters.regex("^menu_referral$") & admin_filter)
    async def cb_menu_referral(_: Client, query: CallbackQuery):
        await FSMManager.clear_state(query.from_user.id)
        summary = await ReferralService.get_referral_summary()

        async with get_session() as db:
            active_accs_stmt = select(func.count(Account.id)).where(Account.status == AccountStatus.ACTIVE.value)
            active_accs = (await db.execute(active_accs_stmt)).scalar() or 0

        text = (
            "🤖 **ماژول استارت و جوین بات رفرال (Referral Bot Joiner)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "این بخش وظیفه استارت خودکار ربات‌های تلگرام (بازی‌ها، ربات‌های ایردراپ و رفرال) "
            "با اکانت‌های استفاده‌نشده و اعمال فواصل زمانی امن و طبیعی را بر عهده دارد.\n\n"
            "📊 **آمار کلی سیستم:**\n"
            f"• کل جاب‌های ثبت‌شده: `{summary['total_jobs']}`\n"
            f"• جاب‌های فعال در حال اجرا: `🟢 {summary['running_jobs']}`\n"
            f"• مجموع استارت‌های موفق انجام‌شده: `🎉 {summary['total_joins']}`\n"
            f"• اکانت‌های فعال آماده به کار: `👥 {active_accs}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "جهت ایجاد جاب جدید یا مدیریت جاب‌های قبلی، گزینه مورد نظر را انتخاب کنید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.referral_menu())
        await query.answer()

    # 2. List Referral Jobs (Paginated)
    @app.on_callback_query(filters.regex(r"^ref_list_(\d+)$") & admin_filter)
    async def cb_ref_list(_: Client, query: CallbackQuery):
        page = int(query.matches[0].group(1))
        jobs, total, total_pages = await ReferralService.get_paginated_jobs(page=page, page_size=6)

        if total == 0:
            text = (
                "📋 **لیست جاب‌های رفرال**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "هنوز هیچ جاب رفرالی در سیستم تعریف نشده است.\n"
                "جهت ایجاد اولین جاب، روی «➕ ایجاد جاب رفرال جدید» کلیک کنید."
            )
            await query.message.edit_text(text, reply_markup=Keyboards.referral_menu())
            await query.answer()
            return

        text = (
            f"📋 **لیست جاب‌های رفرال** (مجموع: `{total}` جاب)\n"
            f"صفحه `{page}` از `{total_pages}`\n"
            "جهت مشاهده جزئیات و کنترل، روی جاب مورد نظر کلیک کنید:"
        )
        await query.message.edit_text(
            text,
            reply_markup=Keyboards.referral_jobs_list(jobs, current_page=page, total_pages=total_pages),
        )
        await query.answer()

    # 3. View Single Referral Job
    @app.on_callback_query(filters.regex(r"^ref_view_(\d+)$") & admin_filter)
    async def cb_ref_view(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        job = await ReferralService.get_job_by_id(job_id)
        if not job:
            await query.answer("جاب رفرال مورد نظر یافت نشد.", show_alert=True)
            return

        stats = await ReferralService.get_job_stats(job_id)

        status_emojis = {
            ReferralJobStatus.RUNNING.value: "🟢 در حال اجرا (RUNNING)",
            ReferralJobStatus.PENDING.value: "🟡 در انتظار (PENDING)",
            ReferralJobStatus.COMPLETED.value: "✅ پایان‌یافته (COMPLETED)",
            ReferralJobStatus.STOPPED.value: "⏹ متوقف‌شده (STOPPED)",
            "PAUSED": "⏸ متوقف موقت (PAUSED)",
        }
        st_text = status_emojis.get(job.status, f"❓ {job.status}")

        param_display = f"`{job.start_param}`" if job.start_param else "_(بدون پارامتر رفرال)_"
        created_str = job.created_at.strftime("%Y-%m-%d %H:%M:%S") if job.created_at else "نامشخص"

        progress_pct = int((stats["success"] / stats["total"]) * 100) if stats["total"] > 0 else 0

        d_min = getattr(job, "delay_min", None) or max(5, int(job.delay_seconds * 0.85))
        d_max = getattr(job, "delay_max", None) or max(d_min + 5, int(job.delay_seconds * 1.15))
        timing_info = f"`{d_min}` تا `{d_max}` ثانیه (کاملاً تصادفی)"
        if getattr(job, "target_duration_minutes", None):
            timing_info += f" | توزیع در `{job.target_duration_minutes}` دقیقه"

        text = (
            f"🤖 **جزئیات جاب رفرال #{job.id}**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• ربات هدف: `@{job.bot_username}`\n"
            f"• پارامتر رفرال (Start Param): {param_display}\n"
            f"• الگوی تاخیر: {timing_info}\n"
            f"• وضعیت کنونی: {st_text}\n"
            f"• تاریخ ایجاد: `{created_str}`\n\n"
            "📊 **پیشرفت و آمار اجرای اکانت‌ها:**\n"
            f"• کل اکانت‌های تارگت: `{stats['total']}`\n"
            f"• موفق و ملحق‌شده: `✅ {stats['success']}` ({progress_pct}%)\n"
            f"• با خطا/تایم‌اوت: `⚠️ {stats['failed']}`\n"
            f"• اکانت‌های باقیمانده در صف: `⏳ {stats['remaining']}`\n"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.referral_job_details(job, stats))
        await query.answer()

    # 4. Pause Referral Job
    @app.on_callback_query(filters.regex(r"^ref_pause_(\d+)$") & admin_filter)
    async def cb_ref_pause(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        await ReferralService.update_job_status(job_id, "PAUSED")
        ReferralWorker.stop_job_task(job_id)
        await query.answer("⏸ جاب موقتاً متوقف گردید.", show_alert=True)
        job = await ReferralService.get_job_by_id(job_id)
        if job:
            await cb_ref_view(_, query)

    # 5. Resume Referral Job
    @app.on_callback_query(filters.regex(r"^ref_resume_(\d+)$") & admin_filter)
    async def cb_ref_resume(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        await ReferralService.update_job_status(job_id, ReferralJobStatus.RUNNING.value)
        ReferralWorker.start_job_task(job_id)
        await query.answer("▶️ جاب مجدداً آغاز گردید.", show_alert=True)
        job = await ReferralService.get_job_by_id(job_id)
        if job:
            await cb_ref_view(_, query)

    # 6. Stop Referral Job
    @app.on_callback_query(filters.regex(r"^ref_stop_(\d+)$") & admin_filter)
    async def cb_ref_stop(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        await ReferralService.update_job_status(job_id, ReferralJobStatus.STOPPED.value)
        ReferralWorker.stop_job_task(job_id)
        await query.answer("⏹ جاب به طور کامل متوقف گردید.", show_alert=True)
        job = await ReferralService.get_job_by_id(job_id)
        if job:
            await cb_ref_view(_, query)

    # 7. Delete Referral Job
    @app.on_callback_query(filters.regex(r"^ref_del_(\d+)$") & admin_filter)
    async def cb_ref_del(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        ReferralWorker.stop_job_task(job_id)
        deleted = await ReferralService.delete_job(job_id)
        if deleted:
            await query.answer("🗑 جاب و لاگ‌های آن با موفقیت حذف گردیدند.", show_alert=True)
            jobs, total, total_pages = await ReferralService.get_paginated_jobs(page=1, page_size=6)
            if total > 0:
                await query.message.edit_text(
                    f"📋 **لیست جاب‌های رفرال** (مجموع: `{total}` جاب)\nصفحه `1` از `{total_pages}`",
                    reply_markup=Keyboards.referral_jobs_list(jobs, current_page=1, total_pages=total_pages),
                )
            else:
                await query.message.edit_text(
                    "📋 هیچ جاب رفرالی در سیستم موجود نیست.",
                    reply_markup=Keyboards.referral_menu(),
                )
        else:
            await query.answer("خطا در حذف جاب.", show_alert=True)

    # 8. View Referral Job Logs (Paginated)
    @app.on_callback_query(filters.regex(r"^ref_logs_(\d+)_(\d+)$") & admin_filter)
    async def cb_ref_logs(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        page = int(query.matches[0].group(2))

        job = await ReferralService.get_job_by_id(job_id)
        if not job:
            await query.answer("جاب یافت نشد.", show_alert=True)
            return

        logs, total, total_pages = await ReferralService.get_job_paginated_logs(job_id, page=page, page_size=8)
        if not logs:
            text = (
                f"📜 **لاگ اجرای اکانت‌ها برای جاب #{job_id}** (@{job.bot_username})\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "هنوز هیچ لاگی برای این جاب ثبت نشده است."
            )
            await query.message.edit_text(text, reply_markup=Keyboards.referral_job_details(job, {"total": 0, "success": 0}))
            await query.answer()
            return

        lines = [
            f"📜 **لاگ اجرای اکانت‌ها برای جاب #{job_id}** (@{job.bot_username})",
            f"صفحه `{page}` از `{total_pages}` (مجموع: `{total}` تلاش)",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        for l in logs:
            st_icon = "🟢" if l.status == JoinLogStatus.SUCCESS.value else "🔴"
            time_str = l.executed_at.strftime("%H:%M:%S") if l.executed_at else ""
            err_str = f" - `{l.error}`" if l.error else ""
            lines.append(f"• {st_icon} اکانت `#{l.account_id}` ({l.status}) [{time_str}]{err_str}")

        text = "\n".join(lines)
        await query.message.edit_text(
            text,
            reply_markup=Keyboards.referral_logs_list(logs, job_id, current_page=page, total_pages=total_pages),
        )
        await query.answer()

    # 9. Start New Referral Job Wizard
    @app.on_callback_query(filters.regex("^ref_new$") & admin_filter)
    async def cb_ref_new(_: Client, query: CallbackQuery):
        # Ensure active accounts exist
        async with get_session() as db:
            active_count = (await db.execute(
                select(func.count(Account.id)).where(Account.status == AccountStatus.ACTIVE.value)
            )).scalar() or 0

        if active_count == 0:
            await query.answer("❌ ابتدا باید حداقل ۱ اکانت فعال در سیستم داشته باشید.", show_alert=True)
            return

        await FSMManager.set_state(query.from_user.id, "WAIT_REF_BOT")
        text = (
            "🤖 **ایجاد جاب استارت رفرال بات (گام ۱ از ۳)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً **یوزرنیم ربات هدف** یا **لینک کامل رفرال** را ارسال نمایید.\n\n"
            "📌 **نمونه‌های قابل قبول:**\n"
            "• `https://t.me/DogesBot?start=r_123456`\n"
            "• `t.me/tapswap_bot?startapp=ref_abc`\n"
            "• `@MyAirdropBot`\n"
            "• `major_bot`\n\n"
            "💡 _نکته: در صورتی که لینک کامل رفرال را ارسال کنید، نام ربات و کد رفرال به صورت خودکار تشخیص داده خواهند شد._"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_referral"))
        await query.answer()

    # 10. Skip Param Callback
    @app.on_callback_query(filters.regex("^ref_param_skip$") & admin_filter)
    async def cb_ref_param_skip(_: Client, query: CallbackQuery):
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            await query.answer("نشست منقضی شده است.", show_alert=True)
            return

        await FSMManager.update_data(query.from_user.id, start_param=None)
        await FSMManager.set_state(query.from_user.id, "WAIT_REF_DELAY", data={**data, "start_param": None})

        text = (
            "⏱ **تنظیم فاصله زمانی امن (گام ۳ از ۳)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"ربات هدف: `@{data.get('bot_username')}`\n"
            "کد رفرال: _(بدون پارامتر - /start ساده)_\n\n"
            "لطفاً فاصله زمانی طبیعی بین استارت هر اکانت را انتخاب نمایید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.referral_delay_picker())
        await query.answer()

    # 11. Time-Window Distribution Callbacks (پخش در بازه زمانی کل)
    @app.on_callback_query(filters.regex(r"^refd_win_(\d+)$") & admin_filter)
    async def cb_refd_win(_: Client, query: CallbackQuery):
        duration_mins = int(query.matches[0].group(1))
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            await query.answer("نشست منقضی شده است.", show_alert=True)
            return

        bot_username = data.get("bot_username")
        start_param = data.get("start_param")

        eligible = await ReferralService.get_eligible_accounts_for_job(0, bot_username)
        eligible_count = len(eligible)

        d_min, d_max = ReferralService.calculate_delays_from_duration(eligible_count, duration_mins)

        await FSMManager.update_data(
            query.from_user.id,
            delay_min=d_min,
            delay_max=d_max,
            target_duration_minutes=duration_mins,
        )
        await FSMManager.set_state(
            query.from_user.id,
            "CONFIRM_REF_JOB",
            data={**data, "delay_min": d_min, "delay_max": d_max, "target_duration_minutes": duration_mins},
        )

        param_display = f"`{start_param}`" if start_param else "_(بدون پارامتر رفرال)_"
        text = (
            "🚀 **پیش‌نمایش و تایید نهایی جاب رفرال**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• ربات هدف: `@{bot_username}`\n"
            f"• کد رفرال: {param_display}\n"
            f"• بازه زمانی کل: `پخش در {duration_mins} دقیقه`\n"
            f"• تاخیر رندوم شناور بین هر اکانت: `{d_min}` تا `{d_max}` ثانیه (کاملاً ارگانیک)\n"
            f"• تعداد اکانت‌های واجد شرایط: `👥 {eligible_count}` اکانت\n\n"
            "آیا مایل به راه‌اندازی و شروع آنی این جاب هستید؟"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.referral_confirm_keyboard())
        await query.answer()

    # 12. Random Delay Range Callbacks (بازه تاخیر رندوم ثانیه‌ای)
    @app.on_callback_query(filters.regex(r"^refd_rng_(\d+)_(\d+)$") & admin_filter)
    async def cb_refd_rng(_: Client, query: CallbackQuery):
        d_min = int(query.matches[0].group(1))
        d_max = int(query.matches[0].group(2))
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            await query.answer("نشست منقضی شده است.", show_alert=True)
            return

        bot_username = data.get("bot_username")
        start_param = data.get("start_param")

        await FSMManager.update_data(
            query.from_user.id,
            delay_min=d_min,
            delay_max=d_max,
            target_duration_minutes=None,
        )
        await FSMManager.set_state(
            query.from_user.id,
            "CONFIRM_REF_JOB",
            data={**data, "delay_min": d_min, "delay_max": d_max, "target_duration_minutes": None},
        )

        eligible = await ReferralService.get_eligible_accounts_for_job(0, bot_username)
        eligible_count = len(eligible)

        param_display = f"`{start_param}`" if start_param else "_(بدون پارامتر رفرال)_"
        text = (
            "🚀 **پیش‌نمایش و تایید نهایی جاب رفرال**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• ربات هدف: `@{bot_username}`\n"
            f"• کد رفرال: {param_display}\n"
            f"• بازه تاخیر رندوم بین اکانت‌ها: `{d_min}` تا `{d_max}` ثانیه (کاملاً تصادفی)\n"
            f"• تعداد اکانت‌های واجد شرایط: `👥 {eligible_count}` اکانت\n\n"
            "آیا مایل به راه‌اندازی و شروع آنی این جاب هستید؟"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.referral_confirm_keyboard())
        await query.answer()

    # 13. Custom Delay Prompt
    @app.on_callback_query(filters.regex("^refd_custom$") & admin_filter)
    async def cb_refd_custom(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_REF_CUSTOM_DELAY")
        text = (
            "✍️ **تنظیم دستی فاصله و الگوی زمان‌بندی**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "شما می‌توانید یکی از الگوهای دلخواه زیر را تایپ و ارسال فرمایید:\n\n"
            "1️⃣ **بازه تاخیر رندوم ثانیه‌ای:**\n"
            "• `20-80` (بین ۲۰ تا ۸۰ ثانیه رندوم بین هر اکانت)\n"
            "• `30-90`\n\n"
            "2️⃣ **پخش کل اکانت‌ها در بازه زمانی مشخص (Time Window):**\n"
            "• `1h` یا `1 ساعت` (پخش تمام اکانت‌ها در بازه ۱ ساعت)\n"
            "• `30m` یا `30 دقیقه`\n"
            "• `2h` یا `2 ساعت`\n\n"
            "3️⃣ **ثانیه تک با تاخیر شناور ارگانیک:**\n"
            "• `45` (حدود ۴۵ ثانیه با تاخیر شناور طبیعی)\n\n"
            "لطفاً مقدار مورد نظر خود را ارسال کنید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_referral"))
        await query.answer()

    # 14. Confirm and Start Job
    @app.on_callback_query(filters.regex("^ref_confirm_start$") & admin_filter)
    async def cb_ref_confirm_start(_: Client, query: CallbackQuery):
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data or not data.get("bot_username"):
            await query.answer("نشست منقضی شده است.", show_alert=True)
            return

        bot_username = data.get("bot_username")
        start_param = data.get("start_param")
        delay_min = data.get("delay_min", 30)
        delay_max = data.get("delay_max", 90)
        target_duration_minutes = data.get("target_duration_minutes")

        job = await ReferralService.create_job(
            bot_username=bot_username,
            start_param=start_param,
            delay_min=delay_min,
            delay_max=delay_max,
            target_duration_minutes=target_duration_minutes,
        )

        # Clear FSM
        await FSMManager.clear_state(query.from_user.id)

        # Start worker immediately
        ReferralWorker.start_job_task(job.id)

        await query.answer("🚀 جاب رفرال با موفقیت ایجاد و فعال گردید!", show_alert=True)
        stats = await ReferralService.get_job_stats(job.id)

        timing_text = f"`{job.delay_min}` تا `{job.delay_max}` ثانیه (رندوم)"
        if job.target_duration_minutes:
            timing_text += f" (پخش در `{job.target_duration_minutes}` دقیقه)"

        text = (
            f"✅ **جاب رفرال #{job.id} با موفقیت راه‌اندازی شد!**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• ربات: `@{job.bot_username}`\n"
            f"• کد رفرال: `{job.start_param or 'ساده'}`\n"
            f"• الگوی زمان‌بندی: {timing_text}\n"
            f"• اکانت‌های در صف اجرا: `{stats['remaining']}` اکانت\n\n"
            "عملیات استارت اکانت‌ها در پس‌زمینه با فواصل امن و رندوم آغاز شد."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.referral_job_details(job, stats))

    # 14. Text Handler for FSM States
    @app.on_message(filters.text & filters.private & admin_filter)
    async def handle_referral_text(_: Client, msg: Message):
        state, data = await FSMManager.get_state(msg.from_user.id)
        if state not in REFERRAL_STATES:
            msg.continue_propagation()
            return

        # State 1: Input Bot Username or Full URL
        if state == "WAIT_REF_BOT":
            bot_user, start_param = ReferralService.parse_bot_and_param(msg.text)
            if not bot_user:
                await msg.reply_text("❌ نام یا آدرس ربات نامعتبر است. لطفاً مجدداً ارسال فرمایید:")
                return

            # Check if active accounts exist
            eligible = await ReferralService.get_eligible_accounts_for_job(0, bot_user)
            if not eligible:
                await msg.reply_text(
                    f"⚠️ هیچ اکانت آزادی برای استارت ربات `@{bot_user}` وجود ندارد (همه اکانت‌ها قبلاً این ربات را استارت زده‌اند یا غیرفعال هستند).",
                    reply_markup=Keyboards.cancel("menu_referral"),
                )
                return

            # If parameter was already in the link
            if start_param:
                await FSMManager.set_state(
                    msg.from_user.id,
                    "WAIT_REF_DELAY",
                    data={"bot_username": bot_user, "start_param": start_param},
                )
                text = (
                    "⏱ **تنظیم فاصله زمانی امن (گام ۳ از ۳)**\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• ربات هدف: `@{bot_user}`\n"
                    f"• پارامتر استخراج‌شده از لینک: `{start_param}`\n\n"
                    "لطفاً فاصله زمانی ایمن بین استارت هر اکانت را انتخاب فرمایید:"
                )
                await msg.reply_text(text, reply_markup=Keyboards.referral_delay_picker())
            else:
                # Ask for start parameter
                await FSMManager.set_state(
                    msg.from_user.id,
                    "WAIT_REF_PARAM",
                    data={"bot_username": bot_user},
                )
                text = (
                    "🔗 **ارسال کد یا پارامتر رفرال (گام ۲ از ۳)**\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"ربات هدف: `@{bot_user}`\n\n"
                    "لطفاً **کد رفرال** را ارسال فرمایید (مثال: `ref_12345` یا `r_xyz`).\n"
                    "در صورتی که ربات پارامتر رفرال ندارد، دکمه «بدون پارامتر» را بزنید:"
                )
                await msg.reply_text(text, reply_markup=Keyboards.referral_skip_param())

        # State 2: Input Start Parameter
        elif state == "WAIT_REF_PARAM":
            param = msg.text.strip()
            bot_username = data.get("bot_username")
            await FSMManager.set_state(
                msg.from_user.id,
                "WAIT_REF_DELAY",
                data={**data, "start_param": param},
            )
            text = (
                "⏱ **تنظیم فاصله زمانی امن (گام ۳ از ۳)**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• ربات هدف: `@{bot_username}`\n"
                f"• پارامتر رفرال: `{param}`\n\n"
                "لطفاً سرعت و فاصله زمانی ایمن بین استارت هر اکانت را انتخاب نمایید:"
            )
            await msg.reply_text(text, reply_markup=Keyboards.referral_delay_picker())

        # State 3: Custom Timing Pattern / Delay
        elif state == "WAIT_REF_CUSTOM_DELAY":
            bot_username = data.get("bot_username")
            start_param = data.get("start_param")

            eligible = await ReferralService.get_eligible_accounts_for_job(0, bot_username)
            eligible_count = len(eligible)

            parsed = ReferralService.parse_timing_input(msg.text, accounts_count=eligible_count)
            if not parsed:
                err_text = (
                    "❌ **فرمت ورودی نامعتبر است.**\n\n"
                    "لطفاً یکی از الگوهای معتبر زیر را ارسال فرمایید:\n"
                    "• **بازه تصادفی:** `20-80` یا `30 تا 90`\n"
                    "• **پخش در بازه زمانی:** `1h` یا `1 ساعت` یا `30 دقیقه`\n"
                    "• **ثانیه تک:** `45`"
                )
                await msg.reply_text(err_text)
                return

            d_min, d_max, target_duration = parsed

            await FSMManager.set_state(
                msg.from_user.id,
                "CONFIRM_REF_JOB",
                data={
                    **data,
                    "delay_min": d_min,
                    "delay_max": d_max,
                    "target_duration_minutes": target_duration,
                },
            )

            param_display = f"`{start_param}`" if start_param else "_(بدون پارامتر رفرال)_"
            if target_duration:
                timing_desc = (
                    f"• بازه زمانی کل: `پخش در {target_duration} دقیقه`\n"
                    f"• تاخیر رندوم شناور بین هر اکانت: `{d_min}` تا `{d_max}` ثانیه (ارگانیک)"
                )
            else:
                timing_desc = f"• بازه تاخیر رندوم بین اکانت‌ها: `{d_min}` تا `{d_max}` ثانیه (کاملاً تصادفی)"

            text = (
                "🚀 **پیش‌نمایش و تایید نهایی جاب رفرال**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• ربات هدف: `@{bot_username}`\n"
                f"• کد رفرال: {param_display}\n"
                f"{timing_desc}\n"
                f"• تعداد اکانت‌های واجد شرایط: `👥 {eligible_count}` اکانت\n\n"
                "آیا مایل به راه‌اندازی و شروع آنی این جاب هستید؟"
            )
            await msg.reply_text(text, reply_markup=Keyboards.referral_confirm_keyboard())
