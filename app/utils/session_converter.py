import base64
import os
import re
import sqlite3
import struct
import tempfile
from typing import List, Optional, Tuple

from app.core.exceptions import SessionConversionError


class SessionConverter:
    """
    Utility for detecting, parsing, and converting Telegram session formats
    (Telethon StringSession, Pyrogram v1/v2 StringSession, and SQLite .session files)
    into a unified Kurigram / Pyrogram 2.0+ session string.
    """

    # Kurigram & Pyrogram format constants
    PYROGRAM_V1_FORMAT = ">B?256sI?"      # dc_id, test_mode, auth_key, user_id (32-bit), is_bot
    PYROGRAM_V2_FORMAT = ">B?256sQ?"      # dc_id, test_mode, auth_key, user_id (64-bit), is_bot
    KURIGRAM_MODERN_FORMAT = ">BI?256sQ?" # dc_id, api_id, test_mode, auth_key, user_id (64-bit), is_bot

    TELETHON_IPV4_FORMAT = ">B4sH256s"   # dc_id, ip, port, auth_key (263 bytes)
    TELETHON_IPV6_FORMAT = ">B16sH256s"  # dc_id, ip, port, auth_key (275 bytes)

    @classmethod
    def pad_base64(cls, s: str) -> str:
        """Add missing padding to base64 string."""
        s = s.strip()
        return s + "=" * ((-len(s)) % 4)

    @classmethod
    def convert_string_to_kurigram(cls, session_str: str, api_id: int = 0) -> Tuple[str, str]:
        """
        Detects string session format and converts it to Kurigram session string.
        Returns tuple: (kurigram_session_string, detected_format_name)
        """
        session_str = session_str.strip()
        if not session_str:
            raise SessionConversionError("رشته سشن خالی است.")

        # 1. Telethon String Session detection
        # Telethon StringSession typically starts with '1' and has len ~353 (IPv4) or ~369 (IPv6)
        if session_str.startswith("1") and len(session_str) in range(340, 390):
            try:
                raw = base64.urlsafe_b64decode(cls.pad_base64(session_str[1:]))
                if len(raw) == 263:
                    dc_id, _ip, _port, auth_key = struct.unpack(cls.TELETHON_IPV4_FORMAT, raw)
                    packed = struct.pack(cls.PYROGRAM_V2_FORMAT, dc_id, False, auth_key, 0, False)
                    return base64.urlsafe_b64encode(packed).decode(), "TELETHON_STRING_IPV4"
                elif len(raw) == 275:
                    dc_id, _ip, _port, auth_key = struct.unpack(cls.TELETHON_IPV6_FORMAT, raw)
                    packed = struct.pack(cls.PYROGRAM_V2_FORMAT, dc_id, False, auth_key, 0, False)
                    return base64.urlsafe_b64encode(packed).decode(), "TELETHON_STRING_IPV6"
            except Exception as e:
                # Fallback to try pyrogram parsing
                pass

        # 2. Pyrogram / Kurigram String Session detection
        try:
            raw = base64.urlsafe_b64decode(cls.pad_base64(session_str))
            raw_len = len(raw)

            # Pyrogram v2 (267 bytes: 1 + 1 + 256 + 8 + 1)
            if raw_len == 267:
                dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(cls.PYROGRAM_V2_FORMAT, raw)
                # Already valid Pyrogram v2! Repack cleanly
                packed = struct.pack(cls.PYROGRAM_V2_FORMAT, dc_id, test_mode, auth_key, user_id, is_bot)
                return base64.urlsafe_b64encode(packed).decode(), "PYROGRAM_V2"

            # Kurigram modern format (271 bytes: 1 + 4 + 1 + 256 + 8 + 1)
            if raw_len == 271:
                return session_str, "KURIGRAM_MODERN"

            # Pyrogram v1 (263 bytes: 1 + 1 + 256 + 4 + 1)
            if raw_len == 263:
                dc_id, test_mode, auth_key, user_id, is_bot = struct.unpack(cls.PYROGRAM_V1_FORMAT, raw)
                # Convert 32-bit user_id to 64-bit Pyrogram v2
                packed = struct.pack(cls.PYROGRAM_V2_FORMAT, dc_id, test_mode, auth_key, user_id, is_bot)
                return base64.urlsafe_b64encode(packed).decode(), "PYROGRAM_V1"

        except Exception as e:
            raise SessionConversionError(f"قالب سشن متنی نامعتبر است یا قابل خواندن نیست: {e}")

        # If base64 decoded but length did not match
        raise SessionConversionError(
            f"طول باینری سشن ({len(raw)} بایت) با هیچ‌کدام از فرمت‌های استاندارد Telethon یا Pyrogram همخوانی ندارد."
        )

    @classmethod
    def convert_sqlite_file_to_kurigram(cls, file_bytes_or_path) -> Tuple[str, str]:
        """
        Parses a Telegram SQLite .session file (Telethon or Pyrogram)
        and converts it to a Kurigram session string.
        """
        temp_path = None
        if isinstance(file_bytes_or_path, bytes):
            with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as f:
                f.write(file_bytes_or_path)
                temp_path = f.name
            path_to_open = temp_path
        else:
            path_to_open = str(file_bytes_or_path)

        conn = None
        try:
            conn = sqlite3.connect(path_to_open)
            cursor = conn.cursor()

            # Check if 'sessions' table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
            if not cursor.fetchone():
                raise SessionConversionError("فایل دیتابیس ارسالی فاقد جدول استاندارد sessions تلگرام است.")

            cursor.execute("PRAGMA table_info(sessions)")
            columns = [col[1] for col in cursor.fetchall()]

            cursor.execute("SELECT * FROM sessions LIMIT 1")
            row = cursor.fetchone()
            if not row:
                raise SessionConversionError("جدول sessions در این فایل خالی است.")

            row_dict = dict(zip(columns, row))

            # Case A: Telethon SQLite session format
            if "server_address" in row_dict and "auth_key" in row_dict:
                dc_id = row_dict.get("dc_id", 2)
                auth_key = row_dict.get("auth_key")
                if not auth_key or len(auth_key) != 256:
                    raise SessionConversionError("کلید تایید (auth_key) در سشن تلتون نامعتبر یا خالی است.")
                packed = struct.pack(cls.PYROGRAM_V2_FORMAT, dc_id, False, auth_key, 0, False)
                return base64.urlsafe_b64encode(packed).decode(), "TELETHON_FILE"

            # Case B: Pyrogram SQLite session format
            elif "auth_key" in row_dict and ("test_mode" in row_dict or "user_id" in row_dict):
                dc_id = row_dict.get("dc_id", 2)
                test_mode = bool(row_dict.get("test_mode", 0))
                auth_key = row_dict.get("auth_key")
                user_id = row_dict.get("user_id", 0) or 0
                is_bot = bool(row_dict.get("is_bot", 0))
                if not auth_key or len(auth_key) != 256:
                    raise SessionConversionError("کلید تایید (auth_key) در سشن پایروگرام نامعتبر یا خالی است.")
                packed = struct.pack(cls.PYROGRAM_V2_FORMAT, dc_id, test_mode, auth_key, user_id, is_bot)
                return base64.urlsafe_b64encode(packed).decode(), "PYROGRAM_FILE"

            else:
                raise SessionConversionError(
                    f"ستون‌های جدول sessions ({columns}) با فرمت‌های شناخته‌شده Telethon یا Pyrogram سازگار نیست."
                )

        except sqlite3.Error as e:
            raise SessionConversionError(f"خطای خواندن دیتابیس SQLite سشن: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    @classmethod
    def extract_multiple_sessions_from_text(cls, text: str) -> List[str]:
        """
        Extracts candidate session strings from a text that may contain
        multiple lines, spaces, or extra characters.
        """
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        candidates = []

        for line in lines:
            # Match base64 urlsafe tokens with length >= 300
            tokens = re.findall(r"[A-Za-z0-9_\-=]{300,450}", line)
            if tokens:
                for token in tokens:
                    candidates.append(token)
            else:
                # If line is a single uninterrupted string
                clean_line = line.strip("`'\" \t")
                if len(clean_line) >= 300:
                    candidates.append(clean_line)

        # Deduplicate while preserving order
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)

        return unique_candidates
