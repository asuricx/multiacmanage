from typing import List, Optional, Dict
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.models.account import Account
from app.models.proxy import Proxy
from app.models.referral import ReferralJoinJob, ReferralJobStatus, JoinLog


class Keyboards:
    """Inline Keyboard builders for Admin control panel."""

    @staticmethod
    def cancel(action: str = "cancel") -> InlineKeyboardMarkup:
        """Single cancel button."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو عملیات", callback_data=action)]
        ])

    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        """Main Dashboard menu."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 مدیریت یوزر بات‌ها", callback_data="menu_accounts")],
            [InlineKeyboardButton("👍 ماژول ریاکشن هوشمند", callback_data="menu_reactions")],
            [InlineKeyboardButton("🤖 ماژول جوین بات رفرال", callback_data="menu_referral")],
            [InlineKeyboardButton("🌐 مدیریت پروکسی‌ها (Proxy Pool)", callback_data="menu_proxies")],
            [InlineKeyboardButton("💾 پشتیبان‌گیری دیتابیس (Backup)", callback_data="menu_backup")],
            [InlineKeyboardButton("🔄 به‌روزرسانی وضعیت داشبورد", callback_data="menu_refresh")],
        ])

    @staticmethod
    def backup_menu() -> InlineKeyboardMarkup:
        """Database backup control menu."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 دریافت آنی فایل بک‌آپ دیتابیس", callback_data="backup_now")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu_main")],
        ])

    @staticmethod
    def accounts_menu() -> InlineKeyboardMarkup:
        """Accounts management sub-menu."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ افزودن اکانت", callback_data="acc_add_menu"),
                InlineKeyboardButton("📋 وضعیت و لیست اکانت‌ها", callback_data="acc_list_1"),
            ],
            [
                InlineKeyboardButton("🩺 تست سلامت همه اکانت‌ها", callback_data="acc_test_all"),
                InlineKeyboardButton("🧹 پاکسازی سشن‌های معیوب", callback_data="acc_purge_confirm"),
            ],
            [
                InlineKeyboardButton("🌐 تنظیمات پروکسی", callback_data="menu_proxies"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu_main"),
            ],
        ])

    @staticmethod
    def add_account_menu() -> InlineKeyboardMarkup:
        """Account addition methods menu."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 ارسال سشن‌های متنی (چندگانه / تک)", callback_data="acc_add_text")],
            [InlineKeyboardButton("📁 آپلود فایل .session (تلتون / پایروگرام)", callback_data="acc_add_file")],
            [InlineKeyboardButton("📱 ورود تعاملی با شماره تلفن (کد / 2FA)", callback_data="acc_add_phone")],
            [InlineKeyboardButton("🔙 بازگشت به مدیریت اکانت‌ها", callback_data="menu_accounts")],
        ])

    @staticmethod
    def purge_confirm_keyboard() -> InlineKeyboardMarkup:
        """Confirmation for cleaning broken accounts."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله، پاکسازی کن", callback_data="acc_purge_execute"),
                InlineKeyboardButton("❌ انصراف", callback_data="menu_accounts"),
            ]
        ])

    @staticmethod
    def accounts_list(
        accounts: List[Account],
        current_page: int,
        total_pages: int,
    ) -> InlineKeyboardMarkup:
        """Paginated list of accounts with status indicators."""
        keyboard: List[List[InlineKeyboardButton]] = []

        # Account items (1 per row)
        for acc in accounts:
            label = f"{acc.status_emoji} {acc.display_name} | {acc.phone or 'بدون شماره'}"
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"acc_view_{acc.id}")
            ])

        # Pagination controls
        nav_buttons: List[InlineKeyboardButton] = []
        if current_page > 1:
            nav_buttons.append(
                InlineKeyboardButton("◀️ قبلی", callback_data=f"acc_list_{current_page - 1}")
            )
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {current_page}/{max(total_pages, 1)}", callback_data="noop")
        )
        if current_page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton("بعدی ▶️", callback_data=f"acc_list_{current_page + 1}")
            )

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Batch action shortcuts
        keyboard.append([
            InlineKeyboardButton("🩺 تست همه", callback_data="acc_test_all"),
            InlineKeyboardButton("🧹 پاکسازی معیوب‌ها", callback_data="acc_purge_confirm"),
        ])
        keyboard.append([
            InlineKeyboardButton("🔙 بازگشت به منوی اکانت‌ها", callback_data="menu_accounts")
        ])

        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def account_detail(account: Account) -> InlineKeyboardMarkup:
        """Actions for an individual account."""
        keyboard = [
            [
                InlineKeyboardButton("🩺 تست مجدد سلامت", callback_data=f"acc_check_{account.id}"),
                InlineKeyboardButton("🔀 چرخش پروکسی", callback_data=f"acc_rotate_proxy_{account.id}"),
            ],
            [
                InlineKeyboardButton("🗑 حذف این اکانت", callback_data=f"acc_delete_{account.id}"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="acc_list_1"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def proxies_menu() -> InlineKeyboardMarkup:
        """Proxy Pool management menu."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ افزودن پروکسی دستی", callback_data="proxy_add_manual"),
                InlineKeyboardButton("📋 لیست و وضعیت پروکسی‌ها", callback_data="proxy_list_1"),
            ],
            [
                InlineKeyboardButton("🩺 تست سلامت همه پروکسی‌ها", callback_data="proxy_test_all"),
                InlineKeyboardButton("⚡ اسکرپ فوری از کانال‌ها", callback_data="proxy_scrape_now"),
            ],
            [
                InlineKeyboardButton("📡 مدیریت کانال‌های اسکرپ", callback_data="proxy_channels"),
                InlineKeyboardButton("🔄 انتساب خودکار به اکانت‌ها", callback_data="proxy_auto_assign"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu_main"),
            ]
        ])

    @staticmethod
    def proxies_list(
        proxies: List[Proxy],
        current_page: int,
        total_pages: int,
    ) -> InlineKeyboardMarkup:
        """Paginated list of proxies."""
        keyboard: List[List[InlineKeyboardButton]] = []

        for p in proxies:
            status_emoji = "🟢" if p.is_active else "🔴"
            ping_label = f"{p.ping_ms}ms" if p.ping_ms else "نامشخص"
            label = f"{status_emoji} {p.protocol}://{p.host}:{p.port} ({ping_label})"
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"proxy_view_{p.id}")
            ])

        nav_buttons: List[InlineKeyboardButton] = []
        if current_page > 1:
            nav_buttons.append(
                InlineKeyboardButton("◀️ قبلی", callback_data=f"proxy_list_{current_page - 1}")
            )
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {current_page}/{max(total_pages, 1)}", callback_data="noop")
        )
        if current_page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton("بعدی ▶️", callback_data=f"proxy_list_{current_page + 1}")
            )

        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([
            InlineKeyboardButton("🩺 تست همه پروکسی‌ها", callback_data="proxy_test_all"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="menu_proxies"),
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def proxy_detail(proxy: Proxy) -> InlineKeyboardMarkup:
        """Actions for an individual proxy."""
        keyboard = [
            [
                InlineKeyboardButton("🩺 تست سلامت مجدد", callback_data=f"proxy_check_{proxy.id}"),
                InlineKeyboardButton("🗑 حذف پروکسی", callback_data=f"proxy_delete_{proxy.id}"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به لیست پروکسی‌ها", callback_data="proxy_list_1"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def proxy_channels_menu(channels: list) -> InlineKeyboardMarkup:
        """Channels list for scraping."""
        keyboard: List[List[InlineKeyboardButton]] = []
        for ch in channels:
            status = "🟢" if ch.is_enabled else "🔴"
            keyboard.append([
                InlineKeyboardButton(f"{status} {ch.channel_username}", callback_data=f"channel_view_{ch.id}"),
                InlineKeyboardButton("🗑 حذف", callback_data=f"channel_del_{ch.id}"),
            ])

        keyboard.append([
            InlineKeyboardButton("➕ افزودن کانال جدید", callback_data="channel_add"),
        ])
        keyboard.append([
            InlineKeyboardButton("🔙 بازگشت به منوی پروکسی‌ها", callback_data="menu_proxies"),
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def reactions_menu() -> InlineKeyboardMarkup:
        """Smart Reactions main menu."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ ایجاد جاب ریاکشن جدید", callback_data="reaction_new"),
                InlineKeyboardButton("📋 لیست و وضعیت جاب‌ها", callback_data="reaction_list_1"),
            ],
            [
                InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu_main"),
            ]
        ])

    @staticmethod
    def reactions_list(
        jobs: list,
        current_page: int,
        total_pages: int,
    ) -> InlineKeyboardMarkup:
        """Paginated list of Reaction Jobs."""
        keyboard: List[List[InlineKeyboardButton]] = []
        status_map = {
            "RUNNING": "🟢",
            "PAUSED": "🟡",
            "STOPPED": "⏹",
            "COMPLETED": "✅",
        }

        for j in jobs:
            st_emoji = status_map.get(j.status, "❓")
            em_summary = " ".join([f"{k}:{v}%" for k, v in list(j.emoji_distribution.items())[:2]])
            label = f"{st_emoji} #{j.id} {j.target_channel} ({em_summary})"
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"reaction_view_{j.id}")
            ])

        nav_buttons: List[InlineKeyboardButton] = []
        if current_page > 1:
            nav_buttons.append(
                InlineKeyboardButton("◀️ قبلی", callback_data=f"reaction_list_{current_page - 1}")
            )
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {current_page}/{max(total_pages, 1)}", callback_data="noop")
        )
        if current_page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton("بعدی ▶️", callback_data=f"reaction_list_{current_page + 1}")
            )

        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([
            InlineKeyboardButton("➕ ایجاد جاب جدید", callback_data="reaction_new"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="menu_reactions"),
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def reaction_detail(job) -> InlineKeyboardMarkup:
        """Detail controls for a specific Reaction Job."""
        buttons = []
        if job.status == "RUNNING":
            buttons.append(
                InlineKeyboardButton("⏸ مکث (Pause)", callback_data=f"reaction_pause_{job.id}")
            )
        elif job.status == "PAUSED":
            buttons.append(
                InlineKeyboardButton("▶️ ادامه (Resume)", callback_data=f"reaction_resume_{job.id}")
            )

        if job.status in ("RUNNING", "PAUSED"):
            buttons.append(
                InlineKeyboardButton("⏹ توقف کامل (Stop)", callback_data=f"reaction_stop_{job.id}")
            )

        row2 = [
            InlineKeyboardButton("🗑 حذف جاب", callback_data=f"reaction_del_{job.id}"),
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="reaction_list_1"),
        ]

        layout = []
        if buttons:
            layout.append(buttons)
        layout.append(row2)
        return InlineKeyboardMarkup(layout)

    @staticmethod
    def reaction_emojis_picker(
        available_emojis: list,
        selected_emojis: list,
    ) -> InlineKeyboardMarkup:
        """Inline Keyboard displaying available emojis as interactive toggle buttons."""
        keyboard: List[List[InlineKeyboardButton]] = []
        row: List[InlineKeyboardButton] = []

        for em in available_emojis:
            is_sel = em in selected_emojis
            mark = "✅" if is_sel else "⬜"
            btn_text = f"{mark} {em}"
            # Encode emoji in callback
            row.append(InlineKeyboardButton(btn_text, callback_data=f"rk_tog_{em}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        # Action shortcuts
        keyboard.append([
            InlineKeyboardButton("🔄 انتخاب همه", callback_data="rk_all"),
            InlineKeyboardButton("🧹 لغو همه", callback_data="rk_clear"),
        ])
        keyboard.append([
            InlineKeyboardButton("➡️ تایید و ادامه (مرحله بعد)", callback_data="rk_confirm"),
        ])
        keyboard.append([
            InlineKeyboardButton("❌ لغو", callback_data="menu_reactions"),
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def reaction_delay_picker() -> InlineKeyboardMarkup:
        """Quick delay preset buttons."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ سریع (۵ تا ۳۰ ثانیه)", callback_data="rd_5_30")],
            [InlineKeyboardButton("🚶 معمولی (۳۰ تا ۱۸۰ ثانیه)", callback_data="rd_30_180")],
            [InlineKeyboardButton("🐢 انسانی (۱ تا ۵ دقیقه)", callback_data="rd_60_300")],
            [InlineKeyboardButton("✍️ تایپ بازه دلخواه دستی", callback_data="rd_custom")],
            [InlineKeyboardButton("❌ لغو", callback_data="menu_reactions")],
        ])

    @staticmethod
    def reaction_days_picker() -> InlineKeyboardMarkup:
        """Quick days range preset buttons."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 فقط آخرین پست و پست‌های جدید", callback_data="rday_0")],
            [InlineKeyboardButton("📅 پست‌های ۱ روز اخیر", callback_data="rday_1")],
            [InlineKeyboardButton("📅 پست‌های ۳ روز اخیر", callback_data="rday_3")],
            [InlineKeyboardButton("📅 پست‌های ۷ روز اخیر", callback_data="rday_7")],
            [InlineKeyboardButton("❌ لغو", callback_data="menu_reactions")],
        ])

    @staticmethod
    def referral_menu() -> InlineKeyboardMarkup:
        """Main menu for Referral Bot Joiner."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ایجاد جاب رفرال جدید", callback_data="ref_new")],
            [InlineKeyboardButton("📋 لیست جاب‌های رفرال", callback_data="ref_list_1")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="menu_main")],
        ])

    @staticmethod
    def referral_delay_picker() -> InlineKeyboardMarkup:
        """Presets for safe human-like referral delays and time-window distribution."""
        return InlineKeyboardMarkup([
            # Section 1: Time Window Distribution (توزیع در بازه زمانی کل)
            [
                InlineKeyboardButton("🕒 پخش کل در ۱ ساعت", callback_data="refd_win_60"),
                InlineKeyboardButton("🕒 پخش کل در ۲ ساعت", callback_data="refd_win_120"),
            ],
            [
                InlineKeyboardButton("🕒 پخش کل در ۳۰ دقیقه", callback_data="refd_win_30"),
                InlineKeyboardButton("🕒 پخش کل در ۴ ساعت", callback_data="refd_win_240"),
            ],
            # Section 2: Random Delay Range (بازه تاخیر رندوم ثانیه‌ای)
            [
                InlineKeyboardButton("⚡ سریع (۱۰ تا ۳۰ ثانیه)", callback_data="refd_rng_10_30"),
                InlineKeyboardButton("🚶 معمولی (۳۰ تا ۹۰ ثانیه)", callback_data="refd_rng_30_90"),
            ],
            [
                InlineKeyboardButton("🐢 امن (۶۰ تا ۱۸۰ ثانیه)", callback_data="refd_rng_60_180"),
                InlineKeyboardButton("🛡️ ضداسپم (۲ تا ۵ دقیقه)", callback_data="refd_rng_120_300"),
            ],
            # Section 3: Custom Timing
            [InlineKeyboardButton("✍️ تایپ دستی (مثال: '20-80' یا '1h' یا '30')", callback_data="refd_custom")],
            [InlineKeyboardButton("❌ لغو", callback_data="menu_referral")],
        ])

    @staticmethod
    def referral_skip_param() -> InlineKeyboardMarkup:
        """Skip button when setting up referral parameter."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ بدون پارامتر (فقط ارسال /start ساده)", callback_data="ref_param_skip")],
            [InlineKeyboardButton("❌ لغو", callback_data="menu_referral")],
        ])

    @staticmethod
    def referral_confirm_keyboard() -> InlineKeyboardMarkup:
        """Confirmation button before starting a referral job."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 تایید و شروع آنی جاب", callback_data="ref_confirm_start")],
            [InlineKeyboardButton("❌ لغو", callback_data="menu_referral")],
        ])

    @staticmethod
    def referral_jobs_list(jobs: List[ReferralJoinJob], current_page: int, total_pages: int) -> InlineKeyboardMarkup:
        """Paginated list of referral jobs."""
        keyboard = []
        status_icons = {
            ReferralJobStatus.RUNNING.value: "🟢",
            ReferralJobStatus.PENDING.value: "🟡",
            ReferralJobStatus.COMPLETED.value: "✅",
            ReferralJobStatus.STOPPED.value: "⏹",
            "PAUSED": "⏸",
        }

        for j in jobs:
            icon = status_icons.get(j.status, "❓")
            param_text = f" ({j.start_param})" if j.start_param else ""
            btn_text = f"{icon} @{j.bot_username}{param_text} #{j.id}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ref_view_{j.id}")])

        # Pagination controls
        nav_buttons = []
        if current_page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"ref_list_{current_page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="noop"))
        if current_page < total_pages:
            nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"ref_list_{current_page + 1}"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([
            InlineKeyboardButton("➕ ایجاد جاب جدید", callback_data="ref_new"),
            InlineKeyboardButton("🔙 بازگشت به منوی رفرال", callback_data="menu_referral"),
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def referral_job_details(job: ReferralJoinJob, stats: Dict[str, int]) -> InlineKeyboardMarkup:
        """Control buttons for a specific referral job."""
        keyboard = []

        if job.status == ReferralJobStatus.RUNNING.value:
            keyboard.append([
                InlineKeyboardButton("⏸ توقف موقت (Pause)", callback_data=f"ref_pause_{job.id}"),
                InlineKeyboardButton("🛑 توقف کامل (Stop)", callback_data=f"ref_stop_{job.id}"),
            ])
        elif job.status in ("PAUSED", ReferralJobStatus.PENDING.value):
            keyboard.append([
                InlineKeyboardButton("▶️ ادامه / فعال‌سازی (Resume)", callback_data=f"ref_resume_{job.id}"),
                InlineKeyboardButton("🛑 توقف کامل (Stop)", callback_data=f"ref_stop_{job.id}"),
            ])
        elif job.status in (ReferralJobStatus.STOPPED.value, ReferralJobStatus.COMPLETED.value):
            keyboard.append([
                InlineKeyboardButton("▶️ شروع مجدد (برای اکانت‌های جدید)", callback_data=f"ref_resume_{job.id}"),
            ])

        keyboard.append([
            InlineKeyboardButton(f"📜 مشاهده لاگ اجرای اکانت‌ها ({stats.get('success', 0)}/{stats.get('total', 0)})", callback_data=f"ref_logs_{job.id}_1"),
        ])
        keyboard.append([
            InlineKeyboardButton("🗑 حذف جاب", callback_data=f"ref_del_{job.id}"),
            InlineKeyboardButton("🔙 لیست جاب‌ها", callback_data="ref_list_1"),
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def referral_logs_list(logs: List[JoinLog], job_id: int, current_page: int, total_pages: int) -> InlineKeyboardMarkup:
        """Paginated logs view for a referral job."""
        keyboard = []
        nav_buttons = []
        if current_page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"ref_logs_{job_id}_{current_page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"📄 {current_page}/{total_pages}", callback_data="noop"))
        if current_page < total_pages:
            nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"ref_logs_{job_id}_{current_page + 1}"))

        if nav_buttons:
            keyboard.append(nav_buttons)

        keyboard.append([
            InlineKeyboardButton("🔙 بازگشت به جاب", callback_data=f"ref_view_{job_id}"),
        ])
        return InlineKeyboardMarkup(keyboard)

