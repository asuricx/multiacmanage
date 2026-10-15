import re
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from sqlalchemy import select, func

from app.core.database import get_session
from app.handlers.start import admin_filter
from app.models.account import Account, AccountStatus
from app.models.reaction import ReactionJob, ReactionJobStatus
from app.services.reaction_service import ReactionService
from app.utils.fsm import FSMManager
from app.utils.keyboard import Keyboards


def register_reaction_handlers(app: Client):

    # 1. Reactions Main Submenu
    @app.on_callback_query(filters.regex("^menu_reactions$") & admin_filter)
    async def cb_menu_reactions(_: Client, query: CallbackQuery):
        await FSMManager.clear_state(query.from_user.id)
        jobs, total, _ = await ReactionService.get_paginated_jobs(page=1, page_size=100)
        running_count = sum(1 for j in jobs if j.status == ReactionJobStatus.RUNNING.value)
        paused_count = sum(1 for j in jobs if j.status == ReactionJobStatus.PAUSED.value)

        text = (
            "👍 **ماژول ریاکشن هوشمند تلگرام**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "این ماژول به یوزربات‌ها اجازه می‌دهد بدون نیاز به جوین شدن در کانال‌های عمومی، "
            "با رفتار طبیعی انسانی و تاخیرهای تصادفی بر روی پست‌ها ریاکشن بزنند.\n\n"
            "📊 **وضعیت کنونی جاب‌ها:**\n"
            f"• کل جاب‌ها: `{total}`\n"
            f"• در حال اجرا: `🟢 {running_count}`\n"
            f"• مکث‌شده: `🟡 {paused_count}`\n\n"
            "یکی از گزینه‌های زیر را انتخاب نمایید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.reactions_menu())
        await query.answer()

    # 2. Reactions List & Pagination
    @app.on_callback_query(filters.regex(r"^reaction_list_(\d+)$") & admin_filter)
    async def cb_reaction_list(_: Client, query: CallbackQuery):
        page = int(query.matches[0].group(1))
        jobs, total, total_pages = await ReactionService.get_paginated_jobs(page=page, page_size=6)

        if not jobs and total == 0:
            await query.message.edit_text(
                "📋 هیچ جاب ریاکشنی ثبت نشده است.\nاز دکمه زیر برای ساخت اولین جاب استفاده کنید.",
                reply_markup=Keyboards.reactions_menu(),
            )
            await query.answer()
            return

        text = (
            f"📋 **لیست جاب‌های ریاکشن** (مجموع: `{total}` جاب)\n"
            f"صفحه `{page}` از `{total_pages}`\n\n"
            "برای مشاهده جزئیات و کنترل هر جاب، روی آن کلیک کنید:"
        )
        await query.message.edit_text(
            text,
            reply_markup=Keyboards.reactions_list(jobs, current_page=page, total_pages=total_pages),
        )
        await query.answer()

    # 3. View Single Reaction Job
    @app.on_callback_query(filters.regex(r"^reaction_view_(\d+)$") & admin_filter)
    async def cb_reaction_view(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        job = await ReactionService.get_job_by_id(job_id)
        if not job:
            await query.answer("❌ جاب یافت نشد.", show_alert=True)
            return

        status_emoji = {
            "RUNNING": "🟢 در حال اجرا",
            "PAUSED": "🟡 مکث‌شده",
            "STOPPED": "⏹ متوقف‌شده",
            "COMPLETED": "✅ تکمیل‌شده",
        }.get(job.status, job.status)

        dist_str = " | ".join([f"{k}: {v}%" for k, v in job.emoji_distribution.items()])
        total_posts_reacted = len(job.stats) if job.stats else 0
        total_reactions_sent = sum(s.total_reactions for s in job.stats) if job.stats else 0

        created_str = job.created_at.strftime("%Y-%m-%d %H:%M UTC") if job.created_at else "-"

        text = (
            f"👍 **جزئیات جاب ریاکشن #{job.id}**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• کانال هدف: **{job.target_channel}**\n"
            f"• وضعیت جاب: {status_emoji}\n"
            f"• توزیع درصدی ایموجی‌ها:\n  `{dist_str}`\n"
            f"• بازه تاخیر انسانی: `{job.delay_min}` تا `{job.delay_max}` ثانیه\n"
            f"• بازه زمانی پست‌ها: `{job.days_range}` روز اخیر\n"
            f"• تعداد پست‌های ری‌اکت‌شده: `{total_posts_reacted}`\n"
            f"• مجموع کل ریاکشن‌های زده‌شده: `{total_reactions_sent}`\n"
            f"• زمان ایجاد: `{created_str}`"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.reaction_detail(job))
        await query.answer()

    # 4. Pause Reaction Job
    @app.on_callback_query(filters.regex(r"^reaction_pause_(\d+)$") & admin_filter)
    async def cb_reaction_pause(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        await ReactionService.update_job_status(job_id, ReactionJobStatus.PAUSED.value)
        await query.answer("⏸ جاب موقتاً متوقف شد.", show_alert=True)
        job = await ReactionService.get_job_by_id(job_id)
        if job:
            await cb_reaction_view(_, query)

    # 5. Resume Reaction Job
    @app.on_callback_query(filters.regex(r"^reaction_resume_(\d+)$") & admin_filter)
    async def cb_reaction_resume(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        await ReactionService.update_job_status(job_id, ReactionJobStatus.RUNNING.value)
        await query.answer("▶️ جاب مجدداً فعال شد.", show_alert=True)
        job = await ReactionService.get_job_by_id(job_id)
        if job:
            await cb_reaction_view(_, query)

    # 6. Stop Reaction Job
    @app.on_callback_query(filters.regex(r"^reaction_stop_(\d+)$") & admin_filter)
    async def cb_reaction_stop(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        await ReactionService.update_job_status(job_id, ReactionJobStatus.STOPPED.value)
        await query.answer("⏹ جاب به طور کامل متوقف گردید.", show_alert=True)
        job = await ReactionService.get_job_by_id(job_id)
        if job:
            await cb_reaction_view(_, query)

    # 7. Delete Reaction Job
    @app.on_callback_query(filters.regex(r"^reaction_del_(\d+)$") & admin_filter)
    async def cb_reaction_del(_: Client, query: CallbackQuery):
        job_id = int(query.matches[0].group(1))
        deleted = await ReactionService.delete_job(job_id)
        if deleted:
            await query.answer("🗑 جاب با موفقیت حذف گردید.", show_alert=True)
            jobs, total, total_pages = await ReactionService.get_paginated_jobs(page=1, page_size=6)
            await query.message.edit_text(
                f"📋 **لیست جاب‌های ریاکشن** (مجموع: `{total}` جاب)\nصفحه `1` از `{total_pages}`",
                reply_markup=Keyboards.reactions_list(jobs, current_page=1, total_pages=total_pages),
            )
        else:
            await query.answer("خطا در حذف جاب.", show_alert=True)

    # 8. Start New Reaction Job Wizard
    @app.on_callback_query(filters.regex("^reaction_new$") & admin_filter)
    async def cb_reaction_new(_: Client, query: CallbackQuery):
        # Verify that there are active accounts available
        async with get_session() as db:
            stmt = select(func.count(Account.id)).where(Account.status == AccountStatus.ACTIVE.value)
            active_accs = (await db.execute(stmt)).scalar() or 0

        if active_accs == 0:
            await query.answer(
                "❌ برای ایجاد جاب ریاکشن ابتدا باید حداقل یک اکانت فعال (ACTIVE) در سیستم داشته باشید.",
                show_alert=True,
            )
            return

        await FSMManager.set_state(query.from_user.id, "WAIT_REACTION_CHANNEL")
        text = (
            "➕ **ایجاد جاب ریاکشن هوشمند جدید (گام ۱ از ۴)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 تعداد اکانت‌های فعال آماده به کار: `{active_accs}` عدد\n\n"
            "لطفاً **یوزرنیم یا لینک کانال پابلیک هدف** را ارسال کنید:\n\n"
            "مثال: `@durov` یا `https://t.me/durov`"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_reactions"))
        await query.answer()

    # 9. Emoji Picker Callbacks (Toggle, Select All, Clear, Confirm)
    @app.on_callback_query(filters.regex(r"^rk_tog_(.+)$") & admin_filter)
    async def cb_rk_toggle(_: Client, query: CallbackQuery):
        emoji_target = query.matches[0].group(1)
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            await query.answer("نشست منقضی شده است.", show_alert=True)
            return

        selected = list(data.get("selected", []))
        if emoji_target in selected:
            selected.remove(emoji_target)
        else:
            selected.append(emoji_target)

        await FSMManager.update_data(query.from_user.id, selected=selected)
        available = data.get("available", ReactionService.DEFAULT_EMOJIS)
        await query.message.edit_reply_markup(
            reply_markup=Keyboards.reaction_emojis_picker(available, selected)
        )
        await query.answer()

    @app.on_callback_query(filters.regex("^rk_all$") & admin_filter)
    async def cb_rk_all(_: Client, query: CallbackQuery):
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            return
        available = data.get("available", ReactionService.DEFAULT_EMOJIS)
        await FSMManager.update_data(query.from_user.id, selected=list(available))
        await query.message.edit_reply_markup(
            reply_markup=Keyboards.reaction_emojis_picker(available, list(available))
        )
        await query.answer("همه انتخاب شدند.")

    @app.on_callback_query(filters.regex("^rk_clear$") & admin_filter)
    async def cb_rk_clear(_: Client, query: CallbackQuery):
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            return
        available = data.get("available", ReactionService.DEFAULT_EMOJIS)
        await FSMManager.update_data(query.from_user.id, selected=[])
        await query.message.edit_reply_markup(
            reply_markup=Keyboards.reaction_emojis_picker(available, [])
        )
        await query.answer("انتخاب‌ها پاک شدند.")

    @app.on_callback_query(filters.regex("^rk_confirm$") & admin_filter)
    async def cb_rk_confirm(_: Client, query: CallbackQuery):
        state, data = await FSMManager.get_state(query.from_user.id)
        selected = data.get("selected", [])
        if not selected:
            await query.answer("❌ لطفاً حداقل یک ایموجی انتخاب کنید.", show_alert=True)
            return

        # Calculate equal distribution
        eq_pct = max(1, 100 // len(selected))
        emoji_dist = {em: eq_pct for em in selected}
        await FSMManager.update_data(query.from_user.id, emoji_distribution=emoji_dist)
        await FSMManager.set_state(query.from_user.id, "WAIT_REACTION_DELAYS", data={**data, "emoji_distribution": emoji_dist})

        dist_preview = " | ".join([f"{k}: {v}%" for k, v in emoji_dist.items()])
        text = (
            "⏱ **تنظیم بازه تاخیر انسانی (گام ۳ از ۴)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"ایموجی‌های انتخابی: `{dist_preview}`\n\n"
            "لطفاً سرعت و الگوی تاخیر بین ارسال ریاکشن‌ها را انتخاب نمایید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.reaction_delay_picker())
        await query.answer()

    # 10. Delay Picker Callbacks
    @app.on_callback_query(filters.regex(r"^rd_(\d+)_(\d+)$") & admin_filter)
    async def cb_rd_preset(_: Client, query: CallbackQuery):
        delay_min = int(query.matches[0].group(1))
        delay_max = int(query.matches[0].group(2))
        state, data = await FSMManager.get_state(query.from_user.id)
        await FSMManager.update_data(query.from_user.id, delay_min=delay_min, delay_max=delay_max)
        await FSMManager.set_state(query.from_user.id, "WAIT_REACTION_DAYS", data={**data, "delay_min": delay_min, "delay_max": delay_max})

        text = (
            "📅 **بازه زمانی پست‌ها (گام ۴ از ۴)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"بازه تاخیر: `{delay_min}` تا `{delay_max}` ثانیه\n\n"
            "پست‌های چه بازه‌ای از کانال بررسی و ری‌اکت زده شوند؟"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.reaction_days_picker())
        await query.answer()

    @app.on_callback_query(filters.regex("^rd_custom$") & admin_filter)
    async def cb_rd_custom(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_REACTION_CUSTOM_DELAY")
        text = (
            "✍️ **تایپ بازه تاخیر دستی (ثانیه)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً بازه حداقل و حداکثر تاخیر را ارسال کنید (مثال: `20-90` یا `60`):"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_reactions"))
        await query.answer()

    # 11. Days Picker Callbacks & Finalize Job Creation
    @app.on_callback_query(filters.regex(r"^rday_(\d+)$") & admin_filter)
    async def cb_rday_select(_: Client, query: CallbackQuery):
        days_range = int(query.matches[0].group(1))
        state, data = await FSMManager.get_state(query.from_user.id)
        if not data:
            await query.answer("نشست منقضی شده است.", show_alert=True)
            return

        channel = data.get("channel")
        emoji_dist = data.get("emoji_distribution", {"👍": 100})
        delay_min = data.get("delay_min", 30)
        delay_max = data.get("delay_max", 180)

        await FSMManager.clear_state(query.from_user.id)
        await query.answer("⏳ در حال ایجاد جاب...", show_alert=False)

        job = await ReactionService.create_job(
            target_channel=channel,
            emoji_distribution=emoji_dist,
            delay_min=delay_min,
            delay_max=delay_max,
            days_range=days_range,
        )

        # Trigger immediate check on the channel
        from app.tasks.reaction_worker import ReactionWatcher
        asyncio.create_task(ReactionWatcher._check_channels_posts([job]))

        dist_str = " | ".join([f"{k}: {v}%" for k, v in job.emoji_distribution.items()])
        days_label = "فقط آخرین پست و پست‌های جدید" if job.days_range == 0 else f"{job.days_range} روز گذشته + پست‌های جدید"
        summary_text = (
            f"🎉 **جاب ریاکشن هوشمند با موفقیت ایجاد و فعال شد!**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 شناسه جاب: `#{job.id}`\n"
            f"📢 کانال هدف: **{job.target_channel}**\n"
            f"🟢 وضعیت: **RUNNING (در حال اجرا)**\n"
            f"🎨 ایموجی‌ها: `{dist_str}`\n"
            f"⏱ تاخیر تصادفی: بین `{job.delay_min}` و `{job.delay_max}` ثانیه\n"
            f"📅 بازه زمانی: `{days_label}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "واچر سیستم کانال را رصد کرده و اکانت‌ها طبق تاخیرهای طبیعی ری‌اکت می‌زنند."
        )
        await query.message.edit_text(summary_text, reply_markup=Keyboards.reactions_menu())

    # 12. Text Handler for Wizard Step 1 & Custom Delays
    @app.on_message(filters.text & filters.private & admin_filter)
    async def on_reaction_admin_text(_: Client, msg: Message):
        state, data = await FSMManager.get_state(msg.from_user.id)
        if not state:
            return

        reaction_states = {"WAIT_REACTION_CHANNEL", "WAIT_REACTION_CUSTOM_DELAY"}
        if state not in reaction_states:
            msg.continue_propagation()
            return

        # Step 1: Channel Username Input -> Extract Allowed Emojis -> Show Inline Keyboard Picker
        if state == "WAIT_REACTION_CHANNEL":
            channel_text = msg.text.strip()
            if not channel_text:
                await msg.reply_text("❌ نام کانال نمی‌تواند خالی باشد.")
                return

            status_msg = await msg.reply_text("⏳ در حال بررسی کانال و استخراج ایموجی‌های فعال...")
            available = await ReactionService.get_channel_available_reactions(channel_text)
            await status_msg.delete()

            selected = [available[0]] if available else ["👍"]
            await FSMManager.set_state(
                msg.from_user.id,
                state="WAIT_REACTION_EMOJIS",
                data={"channel": channel_text, "available": available, "selected": selected},
            )
            text = (
                f"👍 **انتخاب ایموجی‌های مجاز کانال (گام ۲ از ۴)**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"کانال: `{channel_text}`\n\n"
                "ایموجی‌های فعال این کانال شناسایی شدند.\n"
                "برای انتخاب یا لغو هر ایموجی، روی دکمه آن کلیک کنید:"
            )
            await msg.reply_text(
                text,
                reply_markup=Keyboards.reaction_emojis_picker(available, selected),
            )

        elif state == "WAIT_REACTION_CUSTOM_DELAY":
            delay_text = msg.text.strip()
            delay_min, delay_max = 30, 180
            del_matches = re.findall(r"\d+", delay_text)
            if len(del_matches) >= 2:
                delay_min = int(del_matches[0])
                delay_max = int(del_matches[1])
            elif len(del_matches) == 1:
                delay_max = int(del_matches[0])
                delay_min = max(5, delay_max // 4)

            if delay_min > delay_max:
                delay_min, delay_max = delay_max, delay_min

            await FSMManager.update_data(msg.from_user.id, delay_min=delay_min, delay_max=delay_max)
            await FSMManager.set_state(msg.from_user.id, "WAIT_REACTION_DAYS", data={**data, "delay_min": delay_min, "delay_max": delay_max})

            text = (
                "📅 **بازه زمانی پست‌ها (گام ۴ از ۴)**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"بازه تاخیر انتخابی: `{delay_min}` تا `{delay_max}` ثانیه\n\n"
                "پست‌های چه بازه‌ای از کانال ری‌اکت زده شوند؟"
            )
            await msg.reply_text(text, reply_markup=Keyboards.reaction_days_picker())
