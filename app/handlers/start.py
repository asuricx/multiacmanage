from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import get_session
from app.models.account import Account, AccountStatus
from app.models.proxy import Proxy
from app.services.account_service import AccountService
from app.services.login_wizard import LoginWizard
from app.utils.fsm import FSMManager
from app.utils.keyboard import Keyboards


async def is_admin_check(_, __, query_or_msg):
    user = query_or_msg.from_user
    if not user:
        return False
    if not settings.ADMIN_IDS:
        return True
    return user.id in settings.ADMIN_IDS


admin_filter = filters.create(is_admin_check)


async def get_dashboard_text() -> str:
    stats = await AccountService.get_accounts_summary()
    async with get_session() as db:
        p_stmt = select(func.count(Proxy.id)).where(Proxy.is_active == True)
        active_proxies = (await db.execute(p_stmt)).scalar() or 0

    return (
        "🤖 **سامانه پیشرفته اتوماسیون و مدیریت یوزربات تلگرام**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **خلاصه وضعیت کنونی:**\n\n"
        f"👥 **کل اکانت‌ها:** `{stats['total']}`\n"
        f"🟢 **اکانت‌های سالم و فعال:** `{stats['active']}`\n"
        f"🔴 **اکانت‌های مسدود یا بن:** `{stats['banned']}`\n"
        f"🟡 **محدودیت FloodWait:** `{stats['flood_wait']}`\n"
        f"⚪ **سشن‌های منقضی/معیوب:** `{stats['invalid']}`\n\n"
        f"🌐 **پروکسی‌های فعال استخر:** `{active_proxies}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "جهت مدیریت بخش‌های مختلف از دکمه‌های زیر استفاده کنید:"
    )


def register_start_handlers(app: Client):

    @app.on_message(filters.command("start") & filters.private & admin_filter)
    async def cmd_start(_: Client, msg: Message):
        await FSMManager.clear_state(msg.from_user.id)
        text = await get_dashboard_text()
        await msg.reply_text(text, reply_markup=Keyboards.main_menu())

    @app.on_callback_query(filters.regex("^menu_main$") & admin_filter)
    async def cb_main_menu(_: Client, query: CallbackQuery):
        await FSMManager.clear_state(query.from_user.id)
        text = await get_dashboard_text()
        await query.message.edit_text(text, reply_markup=Keyboards.main_menu())
        await query.answer()

    @app.on_callback_query(filters.regex("^menu_refresh$") & admin_filter)
    async def cb_refresh(_: Client, query: CallbackQuery):
        text = await get_dashboard_text()
        await query.message.edit_text(text, reply_markup=Keyboards.main_menu())
        await query.answer("داشبورد با موفقیت به‌روزرسانی شد. 🔄")

    @app.on_callback_query(filters.regex("^menu_backup$") & admin_filter)
    async def cb_backup_menu(_: Client, query: CallbackQuery):
        await FSMManager.clear_state(query.from_user.id)
        text = (
            "💾 **سیستم پشتیبان‌گیری خودکار دیتابیس (Backup Manager)**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ **وضعیت زمان‌بندی خودکار:**\n"
            f"• دوره تناوب: هر `{settings.BACKUP_INTERVAL_HOURS}` ساعت (ارسال خودکار فایل به ادمین)\n"
            f"• فرمت ذخیره‌سازی: `.sql.gz` (فشرده‌سازی کامل GZIP)\n"
            f"• نگهداری نسخه‌های محلی: تا `{settings.BACKUP_RETENTION_DAYS}` روز\n"
            f"• نوع پایگاه داده: `PostgreSQL`\n\n"
            "شما همچنین می‌توانید همین حالا یک نسخه پشتیبان زنده دریافت کنید:"
        )
        await query.message.edit_text(text, reply_markup=Keyboards.backup_menu())
        await query.answer()

    @app.on_callback_query(filters.regex("^backup_now$") & admin_filter)
    async def cb_backup_now(_: Client, query: CallbackQuery):
        from app.services.backup_service import BackupService
        await query.answer("⏳ در حال استخراج و فشرده‌سازی بک‌آپ دیتابیس...", show_alert=False)
        loading_msg = await query.message.reply_text("⏳ در حال تهیه خروجی امن از دیتابیس...")
        try:
            res = await BackupService.send_backup_to_recipients(
                client=_,
                recipient_ids=[query.from_user.id],
            )
            await loading_msg.delete()
            if res.get("success"):
                await query.answer("✅ فایل بک‌آپ دیتابیس ارسال شد.", show_alert=True)
            else:
                await query.message.reply_text(f"❌ خطا در ارسال بک‌آپ: `{res.get('error')}`")
        except Exception as e:
            await loading_msg.delete()
            await query.message.reply_text(f"❌ خطا در تهیه بک‌آپ دیتابیس: `{e}`")

    @app.on_callback_query(filters.regex("^cancel$") & admin_filter)
    async def cb_cancel(_: Client, query: CallbackQuery):
        await LoginWizard.cancel_login(query.from_user.id)
        await FSMManager.clear_state(query.from_user.id)
        text = await get_dashboard_text()
        await query.message.edit_text(
            f"❌ عملیات جاری لغو گردید.\n\n{text}",
            reply_markup=Keyboards.main_menu(),
        )
        await query.answer("عملیات لغو شد.")

    @app.on_callback_query(filters.regex("^noop$"))
    async def cb_noop(_: Client, query: CallbackQuery):
        await query.answer()
