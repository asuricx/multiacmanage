from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from app.handlers.start import admin_filter
from app.services.proxy_service import ProxyService
from app.utils.fsm import FSMManager
from app.utils.keyboard import Keyboards


def register_proxy_handlers(app: Client):

    # 1. Proxies Main Menu
    @app.on_callback_query(filters.regex("^menu_proxies$") & admin_filter)
    async def cb_menu_proxies(_: Client, query: CallbackQuery):
        await FSMManager.clear_state(query.from_user.id)
        proxies, total, _ = await ProxyService.get_paginated_proxies(page=1, page_size=100)
        active_count = sum(1 for p in proxies if p.is_active)
        dead_count = total - active_count

        text = (
            "🌐 **مدیریت استخر پروکسی‌ها (Proxy Pool)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **آمار استخر پروکسی:**\n"
            f"• کل پروکسی‌ها: `{total}`\n"
            f"• فعال و سالم: `🟢 {active_count}`\n"
            f"• غیرفعال یا قطع: `🔴 {dead_count}`\n\n"
            "جهت مدیریت، افزودن پروکسی، یا اسکرپ خودکار از گزینه‌های زیر استفاده نمایید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.proxies_menu())
        await query.answer()

    # 2. Proxies List & Pagination
    @app.on_callback_query(filters.regex(r"^proxy_list_(\d+)$") & admin_filter)
    async def cb_proxy_list(_: Client, query: CallbackQuery):
        page = int(query.matches[0].group(1))
        proxies, total, total_pages = await ProxyService.get_paginated_proxies(page=page, page_size=6)

        if not proxies and total == 0:
            await query.message.edit_text(
                "📋 هیچ پروکسی در سیستم ثبت نشده است.\nاز دکمه افزودن دستی یا اسکرپ فوری استفاده کنید.",
                reply_markup=Keyboards.proxies_menu(),
            )
            await query.answer()
            return

        text = (
            f"📋 **لیست پروکسی‌های ثبت‌شده** (مجموع: `{total}` عدد)\n"
            f"صفحه `{page}` از `{total_pages}`\n\n"
            "برای مشاهده جزئیات هر پروکسی روی آن کلیک کنید:"
        )
        await query.message.edit_text(
            text,
            reply_markup=Keyboards.proxies_list(proxies, current_page=page, total_pages=total_pages),
        )
        await query.answer()

    # 3. View Single Proxy
    @app.on_callback_query(filters.regex(r"^proxy_view_(\d+)$") & admin_filter)
    async def cb_proxy_view(_: Client, query: CallbackQuery):
        proxy_id = int(query.matches[0].group(1))
        proxy = await ProxyService.get_proxy_by_id(proxy_id)
        if not proxy:
            await query.answer("❌ پروکسی یافت نشد.", show_alert=True)
            return

        status_emoji = "🟢" if proxy.is_active else "🔴"
        auth_status = "دارد (نام کاربری و رمز)" if proxy.username else "ندارد (عمومی)"
        last_check = proxy.last_checked_at.strftime("%Y-%m-%d %H:%M UTC") if proxy.last_checked_at else "بررسی نشده"

        text = (
            f"🌐 **جزئیات پروکسی #{proxy.id}**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• پروتکل: **{proxy.protocol}**\n"
            f"• آدرس سرور: `{proxy.host}`\n"
            f"• پورت: `{proxy.port}`\n"
            f"• احراز هویت: {auth_status}\n"
            f"• وضعیت اتصال: {status_emoji} **{'سالم و متصل' if proxy.is_active else 'قطع / غیرفعال'}**\n"
            f"• پینگ: `{proxy.ping_ms or '-'} ms`\n"
            f"• تعداد خطا: `{proxy.fail_count}`\n"
            f"• منبع: `{proxy.source}`\n"
            f"• آخرین بررسی: `{last_check}`"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.proxy_detail(proxy))
        await query.answer()

    # 4. Check Single Proxy
    @app.on_callback_query(filters.regex(r"^proxy_check_(\d+)$") & admin_filter)
    async def cb_proxy_check(_: Client, query: CallbackQuery):
        proxy_id = int(query.matches[0].group(1))
        await query.answer("⏳ در حال بررسی پینگ و اتصال به تلگرام...", show_alert=False)
        alive, ping, err = await ProxyService.test_single_proxy(proxy_id)
        alert_msg = f"🟢 پروکسی متصل است! پینگ: {ping}ms" if alive else f"🔴 قطع: {err or 'ناموفق'}"
        await query.answer(alert_msg, show_alert=True)

        # Refresh
        proxy = await ProxyService.get_proxy_by_id(proxy_id)
        if proxy:
            status_emoji = "🟢" if proxy.is_active else "🔴"
            last_check = proxy.last_checked_at.strftime("%Y-%m-%d %H:%M UTC") if proxy.last_checked_at else "-"
            text = (
                f"🌐 **جزئیات پروکسی #{proxy.id}**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• پروتکل: **{proxy.protocol}**\n"
                f"• آدرس: `{proxy.host}:{proxy.port}`\n"
                f"• وضعیت: {status_emoji} **{'فعال' if proxy.is_active else 'غیرفعال'}**\n"
                f"• پینگ: `{proxy.ping_ms or '-'} ms`\n"
                f"• آخرین بررسی: `{last_check}`"
            )
            await query.message.edit_text(text, reply_markup=Keyboards.proxy_detail(proxy))

    # 5. Delete Proxy
    @app.on_callback_query(filters.regex(r"^proxy_delete_(\d+)$") & admin_filter)
    async def cb_proxy_delete(_: Client, query: CallbackQuery):
        proxy_id = int(query.matches[0].group(1))
        deleted = await ProxyService.delete_proxy(proxy_id)
        if deleted:
            await query.answer("🗑 پروکسی با موفقیت حذف شد.", show_alert=True)
            proxies, total, total_pages = await ProxyService.get_paginated_proxies(page=1, page_size=6)
            await query.message.edit_text(
                f"📋 **لیست پروکسی‌ها** (مجموع: `{total}` عدد)\nصفحه `1` از `{total_pages}`",
                reply_markup=Keyboards.proxies_list(proxies, current_page=1, total_pages=total_pages),
            )
        else:
            await query.answer("خطا در حذف پروکسی.", show_alert=True)

    # 6. Add Manual Proxy Prompt
    @app.on_callback_query(filters.regex("^proxy_add_manual$") & admin_filter)
    async def cb_proxy_add_manual(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_PROXY_MANUAL")
        text = (
            "➕ **افزودن پروکسی دستی (SOCKS5 / HTTP)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً لیست پروکسی‌های خود را ارسال نمایید (هر پروکسی در یک خط).\n\n"
            "📌 **فرمت‌های پشتیبانی‌شده:**\n"
            "• `socks5://user:pass@host:port`\n"
            "• `http://user:pass@host:port`\n"
            "• `host:port`\n"
            "• `host:port:user:pass`\n"
            "• لینک‌های تلگرامی: `tg://socks?server=...&port=...`\n\n"
            "⚠️ تمامی پروکسی‌ها پیش از ثبت در دیتابیس تست پینگ و سلامت می‌شوند."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_proxies"))
        await query.answer()

    # 7. Test All Proxies & Clean Dead
    @app.on_callback_query(filters.regex("^proxy_test_all$") & admin_filter)
    async def cb_proxy_test_all(_: Client, query: CallbackQuery):
        await query.answer("⏳ تست سلامت و پاکسازی پروکسی‌ها در حال اجراست...", show_alert=False)
        loading_msg = await query.message.reply_text("🩺 **در حال بررسی سلامت و حذف پروکسی‌های خراب...**")
        active, dead = await ProxyService.test_all_proxies()
        deleted = 0
        if dead > 0:
            deleted = await ProxyService.cleanup_dead_proxies()
            await ProxyService.auto_assign_proxies()
        await loading_msg.delete()

        text = (
            "📊 **نتیجه تست سلامت و پالایش استخر پروکسی:**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• پروکسی‌های سالم و متصل: `🟢 {active}`\n"
            f"• پروکسی‌های خراب حذف‌شده از دیتابیس: `🗑️ {deleted}`\n\n"
            "♻️ اکانت‌های فعال به پروکسی‌های سالم اختصاص یافتند."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.proxies_menu())

    # 8. Scrape Proxies Now (Full Pipeline)
    @app.on_callback_query(filters.regex("^proxy_scrape_now$") & admin_filter)
    async def cb_proxy_scrape_now(_: Client, query: CallbackQuery):
        await query.answer("⏳ فرآیند اسکرپ و همگام‌سازی کامل استخر پروکسی آغاز شد...", show_alert=False)
        loading_msg = await query.message.reply_text(
            "⚡ **در حال اسکرپ از کانال‌ها (پست‌ها و دکمه‌های اینلاین)، تست پینگ و حذف پروکسی‌های خراب...**"
        )
        report = await ProxyService.sync_proxies_pipeline()
        await loading_msg.delete()

        if report["assigned"] > 0:
            ip_status = f"🔗 اکانت‌های متصل‌شده به پروکسی: `{report['assigned']}` اکانت"
        else:
            ip_status = "🌐 **هیچ پروکسی سالمی در دسترس نیست؛ اکانت‌ها با آی‌پی اصلی سرور فعال هستند.**"

        text = (
            "⚡ **گزارش همگام‌سازی و اسکرپ استخر پروکسی:**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• پروکسی‌های یافت‌شده از کانال‌ها: `{report['found']}`\n"
            f"• پروکسی‌های جدید و سالم ذخیره‌شده: `🟢 {report['added']}`\n"
            f"• مجموع پروکسی‌های سالم فعال: `🟢 {report['active']}`\n"
            f"• پروکسی‌های خراب حذف‌شده: `🗑️ {report['deleted_dead']}`\n\n"
            f"{ip_status}"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.proxies_menu())

    # 9. Scraper Channels Management
    @app.on_callback_query(filters.regex("^proxy_channels$") & admin_filter)
    async def cb_proxy_channels(_: Client, query: CallbackQuery):
        channels = await ProxyService.get_source_channels()
        text = (
            "📡 **کانال‌های منبع اسکرپ خودکار پروکسی**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "سیستم به صورت روزانه این کانال‌ها را برای یافتن پروکسی‌های رایگان اسکرپ می‌کند:\n"
        )
        if not channels:
            text += "\nهنوز کانالی ثبت نشده است."
        await query.message.edit_text(text, reply_markup=Keyboards.proxy_channels_menu(channels))
        await query.answer()

    # 10. Add Channel Prompt
    @app.on_callback_query(filters.regex("^channel_add$") & admin_filter)
    async def cb_channel_add(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_CHANNEL_USERNAME")
        text = (
            "➕ **افزودن کانال تلگرام برای اسکرپ پروکسی**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً یوزرنیم کانال تلگرامی را ارسال کنید (مثال: `@ProxyMTProto` یا `ProxyMTProto`):"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("proxy_channels"))
        await query.answer()

    # 11. Delete Channel
    @app.on_callback_query(filters.regex(r"^channel_del_(\d+)$") & admin_filter)
    async def cb_channel_del(_: Client, query: CallbackQuery):
        ch_id = int(query.matches[0].group(1))
        deleted = await ProxyService.delete_source_channel(ch_id)
        if deleted:
            await query.answer("🗑 کانال حذف شد.", show_alert=True)
            channels = await ProxyService.get_source_channels()
            await query.message.edit_reply_markup(reply_markup=Keyboards.proxy_channels_menu(channels))
        else:
            await query.answer("خطا در حذف کانال.", show_alert=True)

    # 12. Auto-Assign Proxies to Accounts
    @app.on_callback_query(filters.regex("^proxy_auto_assign$") & admin_filter)
    async def cb_proxy_auto_assign(_: Client, query: CallbackQuery):
        assigned = await ProxyService.auto_assign_proxies()
        await query.answer(f"🔄 تعداد {assigned} اکانت به پروکسی‌های سالم متصل شدند.", show_alert=True)
        await cb_menu_proxies(_, query)

    # 13. Text Input Handler for Proxy FSM
    @app.on_message(filters.text & filters.private & admin_filter)
    async def on_proxy_admin_text(_: Client, msg: Message):
        state, _ = await FSMManager.get_state(msg.from_user.id)
        if not state:
            return

        proxy_states = {"WAIT_PROXY_MANUAL", "WAIT_CHANNEL_USERNAME"}
        if state not in proxy_states:
            msg.continue_propagation()
            return

        if state == "WAIT_PROXY_MANUAL":
            await FSMManager.clear_state(msg.from_user.id)
            status_msg = await msg.reply_text("⏳ در حال تست و اعتبارسنجی پروکسی‌های ارسالی...")
            added, failed, reports = await ProxyService.add_manual_proxies(msg.text)
            await status_msg.delete()

            text = (
                "📊 **گزارش افزودن پروکسی‌ها:**\n"
                f"✅ سالم و ذخیره‌شده: `{added}`\n"
                f"❌ ناموفق / قطع: `{failed}`\n"
                "━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(reports[:15])
            )
            await msg.reply_text(text, reply_markup=Keyboards.proxies_menu())

        elif state == "WAIT_CHANNEL_USERNAME":
            await FSMManager.clear_state(msg.from_user.id)
            ch_user = msg.text.strip()
            ok = await ProxyService.add_source_channel(ch_user)
            if ok:
                await msg.reply_text(f"✅ کانال `{ch_user}` با موفقیت به منابع اسکرپ اضافه گردید.", reply_markup=Keyboards.proxies_menu())
            else:
                await msg.reply_text("⚠️ این کانال قبلاً در لیست ثبت شده بود.", reply_markup=Keyboards.proxies_menu())
