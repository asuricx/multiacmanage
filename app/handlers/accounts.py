import os
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

from app.handlers.start import admin_filter
from app.models.account import AccountStatus
from app.services.account_service import AccountService
from app.services.login_wizard import LoginWizard
from app.services.proxy_service import ProxyService
from app.utils.fsm import FSMManager
from app.utils.keyboard import Keyboards


def register_account_handlers(app: Client):

    # 1. Accounts Main Submenu
    @app.on_callback_query(filters.regex("^menu_accounts$") & admin_filter)
    async def cb_menu_accounts(_: Client, query: CallbackQuery):
        await FSMManager.clear_state(query.from_user.id)
        stats = await AccountService.get_accounts_summary()
        text = (
            "👥 **مدیریت یوزر بات‌ها**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **آمار اکانت‌ها:**\n"
            f"• کل: `{stats['total']}` عدد\n"
            f"• فعال: `🟢 {stats['active']}`\n"
            f"• بن شده: `🔴 {stats['banned']}`\n"
            f"• محدودیت موقت: `🟡 {stats['flood_wait']}`\n"
            f"• معیوب / منقضی: `⚪ {stats['invalid']}`\n\n"
            "یکی از گزینه‌های زیر را انتخاب کنید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.accounts_menu())
        await query.answer()

    # 2. Add Account Menu
    @app.on_callback_query(filters.regex("^acc_add_menu$") & admin_filter)
    async def cb_add_menu(_: Client, query: CallbackQuery):
        text = (
            "➕ **افزودن اکانت به سامانه**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "روش مورد نظر خود را برای ثبت اکانت انتخاب نمایید:\n\n"
            "1️⃣ **ارسال رشته متنی سشن:** پذیرش سشن‌های تلتون یا پایروگرام (امکان ارسال چندین سشن در یک پیام).\n"
            "2️⃣ **ارسال فایل سشن:** دریافت مستقیم فایل `.session` دیتابیس SQLite.\n"
            "3️⃣ **ورود تعاملی:** دریافت کد ورود تلگرام و رمز عبور دو مرحله‌ای (2FA)."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.add_account_menu())
        await query.answer()

    # 3. Add via String Session(s)
    @app.on_callback_query(filters.regex("^acc_add_text$") & admin_filter)
    async def cb_add_text(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_SESSION_TEXT")
        text = (
            "📝 **ارسال سشن‌های متنی (String Sessions)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً سشن یا سشن‌های مورد نظر را در قالب متن ارسال نمایید.\n\n"
            "💡 **ویژگی‌های ماژول تبدیل:**\n"
            "• پشتیبانی هم‌زمان از سشن‌های **Telethon** و **Pyrogram (v1 & v2)**.\n"
            "• قابلیت ارسال **چندین سشن** در یک پیام (هر سشن در یک خط مجزا).\n"
            "• تست سلامت خودکار و تفکیک نتایج هر اکانت."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_accounts"))
        await query.answer()

    # 4. Add via File Upload
    @app.on_callback_query(filters.regex("^acc_add_file$") & admin_filter)
    async def cb_add_file(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_SESSION_FILE")
        text = (
            "📁 **آپلود فایل سشن (.session)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً فایل سشن تلگرام خود را با فرمت `.session` به صورت داکیومنت ارسال فرمایید.\n\n"
            "سیستم به طور خودکار ساختار جداول تلتون یا پایروگرام را استخراج، به سشن استرینگ Kurigram تبدیل، و اکانت را ثبت می‌کند."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_accounts"))
        await query.answer()

    # 5. Add via Interactive Phone Login
    @app.on_callback_query(filters.regex("^acc_add_phone$") & admin_filter)
    async def cb_add_phone(_: Client, query: CallbackQuery):
        await FSMManager.set_state(query.from_user.id, "WAIT_PHONE_NUMBER")
        text = (
            "📱 **ورود تعاملی با شماره تلفن**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً شماره تلفن اکانت تلگرام را به همراه کد کشور ارسال کنید:\n\n"
            "مثال: `+989123456789` یا `+12025550143`"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.cancel("menu_accounts"))
        await query.answer()

    # 6. Accounts List & Pagination
    @app.on_callback_query(filters.regex(r"^acc_list_(\d+)$") & admin_filter)
    async def cb_acc_list(_: Client, query: CallbackQuery):
        page = int(query.matches[0].group(1))
        accounts, total, total_pages = await AccountService.get_paginated_accounts(page=page, page_size=6)

        if not accounts and total == 0:
            await query.message.edit_text(
                "📋 هیچ اکانتی در دیتابیس ثبت نشده است.\nجهت ثبت اولین اکانت از دکمه افزودن استفاده کنید.",
                reply_markup=Keyboards.accounts_menu(),
            )
            await query.answer()
            return

        text = (
            f"📋 **لیست اکانت‌های ثبت شده** (مجموع: `{total}` اکانت)\n"
            f"صفحه `{page}` از `{total_pages}`\n\n"
            "برای مشاهده جزئیات و مدیریت هر اکانت، روی دکمه مربوطه کلیک کنید:"
        )
        await query.message.edit_text(
            text,
            reply_markup=Keyboards.accounts_list(accounts, current_page=page, total_pages=total_pages),
        )
        await query.answer()

    # 7. Account Detail View
    @app.on_callback_query(filters.regex(r"^acc_view_(\d+)$") & admin_filter)
    async def cb_acc_view(_: Client, query: CallbackQuery):
        acc_id = int(query.matches[0].group(1))
        account = await AccountService.get_account_by_id(acc_id)
        if not account:
            await query.answer("❌ اکانت یافت نشد.", show_alert=True)
            return

        proxy_str = f"`{account.proxy.protocol}://{account.proxy.host}:{account.proxy.port}`" if account.proxy else "ندارد (مستقیم)"
        last_check_str = account.last_checked_at.strftime("%Y-%m-%d %H:%M UTC") if account.last_checked_at else "هنوز بررسی نشده"

        text = (
            f"👤 **جزئیات اکانت #{account.id}**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• نام: **{account.first_name or '-'}**\n"
            f"• یوزرنیم: @{account.username or '-'}\n"
            f"• شماره: `{account.phone or '-'}`\n"
            f"• شناسه عددی (User ID): `{account.user_id or '-'}`\n"
            f"• وضعیت سلامت: {account.status_emoji} **{account.status}**\n"
            f"• قالب سشن: `{account.session_format}`\n"
            f"• پروکسی متصل: {proxy_str}\n"
            f"• آخرین بررسی: `{last_check_str}`\n"
        )
        if account.error_message:
            text += f"• آخرین خطا: `{account.error_message}`\n"

        await query.message.edit_text(text, reply_markup=Keyboards.account_detail(account))
        await query.answer()

    # 8. Single Account Test
    @app.on_callback_query(filters.regex(r"^acc_check_(\d+)$") & admin_filter)
    async def cb_acc_check(_: Client, query: CallbackQuery):
        acc_id = int(query.matches[0].group(1))
        await query.answer("⏳ در حال بررسی سلامت سشن...", show_alert=False)
        ok, msg = await AccountService.test_single_account(acc_id)
        alert_text = "🟢 اکانت سالم و متصل است." if ok else f"🔴 خطا: {msg}"
        await query.answer(alert_text, show_alert=True)

        # Refresh detail view
        account = await AccountService.get_account_by_id(acc_id)
        if account:
            proxy_str = f"`{account.proxy.protocol}://{account.proxy.host}:{account.proxy.port}`" if account.proxy else "ندارد"
            last_check_str = account.last_checked_at.strftime("%Y-%m-%d %H:%M UTC") if account.last_checked_at else "-"
            text = (
                f"👤 **جزئیات اکانت #{account.id}**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"• نام: **{account.first_name or '-'}**\n"
                f"• یوزرنیم: @{account.username or '-'}\n"
                f"• شماره: `{account.phone or '-'}`\n"
                f"• شناسه: `{account.user_id or '-'}`\n"
                f"• وضعیت: {account.status_emoji} **{account.status}**\n"
                f"• پروکسی: {proxy_str}\n"
                f"• آخرین تست: `{last_check_str}`\n"
            )
            if account.error_message:
                text += f"• خطا: `{account.error_message}`\n"
            await query.message.edit_text(text, reply_markup=Keyboards.account_detail(account))

    # 9. Rotate Proxy for Account
    @app.on_callback_query(filters.regex(r"^acc_rotate_proxy_(\d+)$") & admin_filter)
    async def cb_acc_rotate_proxy(_: Client, query: CallbackQuery):
        acc_id = int(query.matches[0].group(1))
        rotated_proxy = await ProxyService.rotate_proxy_for_account(acc_id)
        if rotated_proxy:
            await query.answer(f"✅ پروکسی به {rotated_proxy.host}:{rotated_proxy.port} تغییر یافت.", show_alert=True)
        else:
            await query.answer("❌ پروکسی فعال جایگزینی در استخر پروکسی یافت نشد.", show_alert=True)

        account = await AccountService.get_account_by_id(acc_id)
        if account:
            await query.message.edit_reply_markup(reply_markup=Keyboards.account_detail(account))

    # 10. Delete Account
    @app.on_callback_query(filters.regex(r"^acc_delete_(\d+)$") & admin_filter)
    async def cb_acc_delete(_: Client, query: CallbackQuery):
        acc_id = int(query.matches[0].group(1))
        deleted = await AccountService.delete_account(acc_id)
        if deleted:
            await query.answer("🗑 اکانت با موفقیت حذف گردید.", show_alert=True)
            # Return to list page 1
            accounts, total, total_pages = await AccountService.get_paginated_accounts(page=1, page_size=6)
            await query.message.edit_text(
                f"📋 **لیست اکانت‌های ثبت شده** (مجموع: `{total}` اکانت)\nصفحه `1` از `{total_pages}`",
                reply_markup=Keyboards.accounts_list(accounts, current_page=1, total_pages=total_pages),
            )
        else:
            await query.answer("خطا در حذف اکانت.", show_alert=True)

    # 11. Test All Accounts
    @app.on_callback_query(filters.regex("^acc_test_all$") & admin_filter)
    async def cb_acc_test_all(_: Client, query: CallbackQuery):
        await query.answer("⏳ تست سلامت تمامی سشن‌ها آغاز شد...", show_alert=False)
        loading_msg = await query.message.reply_text("🩺 **در حال تست سلامت همزمان اکانت‌ها... لطفاً شکیبا باشید.**")
        results = await AccountService.test_all_accounts()
        await loading_msg.delete()

        report = (
            "📊 **نتیجه بررسی سلامت تمامی اکانت‌ها:**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• کل اکانت‌های بررسی‌شده: `{results['total']}`\n"
            f"• سالم و فعال: `🟢 {results['active']}`\n"
            f"• مسدود و بن شده: `🔴 {results['banned']}`\n"
            f"• دارای FloodWait: `🟡 {results['flood_wait']}`\n"
            f"• منقضی یا نامعتبر: `⚪ {results['invalid']}`"
        )
        await query.message.edit_text(report, reply_markup=Keyboards.accounts_menu())

    # 12. Purge Broken Accounts Confirmation & Execution
    @app.on_callback_query(filters.regex("^acc_purge_confirm$") & admin_filter)
    async def cb_purge_confirm(_: Client, query: CallbackQuery):
        text = (
            "⚠️ **آیا از پاکسازی تمام سشن‌های معیوب مطمئن هستید؟**\n\n"
            "تمامی اکانت‌هایی که در وضعیت `BANNED` یا `INVALID` قرار دارند، برای همیشه از دیتابیس پاک خواهند شد."
        )
        await query.message.edit_text(text, reply_markup=Keyboards.purge_confirm_keyboard())
        await query.answer()

    @app.on_callback_query(filters.regex("^acc_purge_execute$") & admin_filter)
    async def cb_purge_execute(_: Client, query: CallbackQuery):
        count = await AccountService.cleanup_broken_accounts()
        await query.answer(f"🧹 تعداد {count} اکانت معیوب پاکسازی شدند.", show_alert=True)
        stats = await AccountService.get_accounts_summary()
        text = (
            f"✅ **عملیات پاکسازی با موفقیت انجام شد.**\n\n"
            f"تعداد `{count}` سشن غیرقابل استفاده حذف گردید.\n"
            f"مجموع اکانت‌های باقی‌مانده: `{stats['total']}`"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.accounts_menu())

    # 13. Text Input Handler for FSM Dialogs
    @app.on_message(filters.text & filters.private & admin_filter)
    async def on_admin_text(_: Client, msg: Message):
        state, data = await FSMManager.get_state(msg.from_user.id)
        if not state:
            return

        account_states = {"WAIT_SESSION_TEXT", "WAIT_PHONE_NUMBER", "WAITING_LOGIN_CODE", "WAITING_2FA_PASSWORD"}
        if state not in account_states:
            msg.continue_propagation()
            return

        # Case A: Bulk / Single Session String Input
        if state == "WAIT_SESSION_TEXT":
            await FSMManager.clear_state(msg.from_user.id)
            status_msg = await msg.reply_text("⏳ در حال استخراج، تبدیل و اعتبارسنجی سشن‌ها...")
            success, fail, details = await AccountService.batch_add_from_text(msg.text)
            await status_msg.delete()

            if not details:
                await msg.reply_text(
                    "❌ هیچ رشته سشن معتبری در متن ارسالی یافت نشد. لطفاً از صحت فرمت سشن مطمئن شوید.",
                    reply_markup=Keyboards.accounts_menu(),
                )
                return

            report_lines = [
                "📊 **گزارش افزودن سشن‌های متنی:**\n"
                f"✅ موفق: `{success}` | ❌ ناموفق: `{fail}`\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ]
            for d in details:
                emoji = "🟢" if d["success"] else "🔴"
                if d["success"] and d["info"]:
                    inf = d["info"]
                    report_lines.append(
                        f"{emoji} سشن `{d['preview']}`:\n"
                        f"   • نام: {inf.get('first_name') or '-'}\n"
                        f"   • شناسه: `{inf.get('user_id') or '-'}`\n"
                        f"   • قالب: `{inf.get('detected_format')}`"
                    )
                else:
                    report_lines.append(f"{emoji} سشن `{d['preview']}`:\n   • {d['message']}")

            await msg.reply_text("\n\n".join(report_lines), reply_markup=Keyboards.accounts_menu())

        # Case B: Phone Number Input for Login Wizard
        elif state == "WAIT_PHONE_NUMBER":
            phone_text = msg.text.strip()
            status_msg = await msg.reply_text("⏳ در حال ارتباط با تلگرام و ارسال کد...")
            ok, response_text = await LoginWizard.start_login(msg.from_user.id, phone_text)
            await status_msg.delete()
            if ok:
                await msg.reply_text(response_text, reply_markup=Keyboards.cancel("cancel"))
            else:
                await msg.reply_text(response_text, reply_markup=Keyboards.accounts_menu())

        # Case C: Login Code Input for Wizard
        elif state == "WAITING_LOGIN_CODE":
            code_text = msg.text.strip()
            status_msg = await msg.reply_text("⏳ در حال اعتبارسنجی کد...")
            status, response_text, result = await LoginWizard.submit_code(msg.from_user.id, code_text)
            await status_msg.delete()

            if status == "SUCCESS":
                await msg.reply_text(response_text, reply_markup=Keyboards.accounts_menu())
            elif status == "2FA_REQUIRED":
                await msg.reply_text(response_text, reply_markup=Keyboards.cancel("cancel"))
            elif status == "INVALID_CODE":
                await msg.reply_text(response_text, reply_markup=Keyboards.cancel("cancel"))
            else:
                await msg.reply_text(response_text, reply_markup=Keyboards.accounts_menu())

        # Case D: 2FA Password Input for Wizard
        elif state == "WAITING_2FA_PASSWORD":
            password_text = msg.text.strip()
            status_msg = await msg.reply_text("⏳ در حال بررسی رمز عبور دو مرحله‌ای...")
            status, response_text, result = await LoginWizard.submit_password(msg.from_user.id, password_text)
            await status_msg.delete()

            if status == "SUCCESS":
                await msg.reply_text(response_text, reply_markup=Keyboards.accounts_menu())
            elif status == "INVALID_CODE":
                await msg.reply_text(response_text, reply_markup=Keyboards.cancel("cancel"))
            else:
                await msg.reply_text(response_text, reply_markup=Keyboards.accounts_menu())

    # 14. Document Handler for .session File Upload
    @app.on_message(filters.document & filters.private & admin_filter)
    async def on_admin_document(_: Client, msg: Message):
        state, _ = await FSMManager.get_state(msg.from_user.id)
        if state != "WAIT_SESSION_FILE":
            return

        doc = msg.document
        if not doc.file_name or not doc.file_name.lower().endswith(".session"):
            await msg.reply_text("❌ لطفاً فایلی با پسوند `.session` ارسال کنید.", reply_markup=Keyboards.cancel("menu_accounts"))
            return

        await FSMManager.clear_state(msg.from_user.id)
        status_msg = await msg.reply_text("⏳ در حال دانلود و استخراج اطلاعات فایل سشن...")

        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            await msg.download(file_name=tmp_path)
            ok, res_msg, info = await AccountService.add_from_session_file(tmp_path)
            await status_msg.delete()

            if ok and info:
                text = (
                    f"🎉 **فایل سشن با موفقیت پردازش و ثبت شد!**\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"• نام: **{info.get('first_name') or '-'}**\n"
                    f"• شناسه: `{info.get('user_id') or '-'}`\n"
                    f"• شماره: `{info.get('phone') or '-'}`\n"
                    f"• ساختار شناسایی‌شده: `{info.get('detected_format')}`\n"
                    f"• وضعیت: 🟢 ACTIVE"
                )
            else:
                text = f"❌ **خطا در پردازش فایل سشن:**\n\n{res_msg}"

            await msg.reply_text(text, reply_markup=Keyboards.accounts_menu())

        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
