import os
import io
import time
import random
import asyncio
import tempfile
import aiosqlite
from datetime import date
from typing import Any, Callable, Dict, Awaitable

from aiohttp import web
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, TelegramObject, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from google import genai
import yt_dlp

from config import BOT_TOKEN, GEMINI_API_KEY, ADMIN_ID, DB_NAME
from database import init_db, check_and_use_limit

class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 1.0):
        self.limit = limit
        self.users: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
            now = time.time()
            if uid in self.users and (now - self.users[uid]) < self.limit:
                return
            self.users[uid] = now
        return await handler(event, data)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.message.middleware(AntiFloodMiddleware(limit=0.8))
ai_client = genai.Client(api_key=GEMINI_API_KEY)

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Sirli Quti"), KeyboardButton(text="🏆 Reyting (/top)")],
            [KeyboardButton(text="⭐️ Telegram Premium & Gift"), KeyboardButton(text="ℹ️ Yordam")]
        ],
        resize_keyboard=True
    )

def render_progress_bar(current: int, target: int, length: int = 10) -> str:
    filled = min(length, int((current / target) * length))
    return "▓" * filled + "░" * (length - filled) + f" {min(100, int((current / target) * 100))}%"

@dp.message(CommandStart())
async def start_cmd(message: Message):
    user_id = message.from_user.id
    args = message.text.split()[1] if len(message.text.split()) > 1 else ""

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM user_rewards WHERE user_id = ?", (user_id,)) as cur:
            exists = await cur.fetchone()

        if not exists:
            inviter_id = None
            if args.startswith("ref_"):
                try:
                    parsed_id = int(args.replace("ref_", ""))
                    if parsed_id != user_id:
                        inviter_id = parsed_id
                except ValueError:
                    pass

            await db.execute("INSERT INTO user_rewards (user_id, inviter_id) VALUES (?, ?)", (user_id, inviter_id))
            
            if inviter_id:
                await db.execute("UPDATE user_rewards SET referral_count = referral_count + 1 WHERE user_id = ?", (inviter_id,))
                await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 4 WHERE user_id = ?", (inviter_id,))
                await db.execute("UPDATE user_boxes SET extra_spins = extra_spins + 1 WHERE user_id = ?", (inviter_id,))
                try:
                    await bot.send_message(
                        inviter_id,
                        f"🎉 <b>Yangi do‘stingiz botga qo‘shildi!</b>\n"
                        f"Sizga <b>+4 ta so‘rov limiti</b> va <b>+1 ta Sirli Quti ochish</b> imkoniyati berildi!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            await db.commit()

    await message.answer(
        f"Assalomu alaykum, <b>{message.from_user.first_name}</b>! 👋\n\n"
        "Men <b>BirZum AI</b> — ko‘p funksiyali yordamchingizman:\n"
        "▫️ <b>Dars/Masala:</b> Rasm yuboring, yechib beraman.\n"
        "▫️ <b>Voice-to-Text:</b> Ovozli xabarni matnga aylantirib, xulosa qilaman.\n"
        "▫️ <b>Media Yuklash:</b> Reels, TikTok yoki YouTube havolasini yuboring.\n"
        "▫️ <b>Ovoz Effektlari:</b> Ovoz yuborib effekt tanlang.\n\n"
        "🎁 <i>Har kuni 4 ta bepul so‘rov va 1 ta Sirli Quti imkoni mavjud!</i>",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@dp.message(F.text == "🎁 Sirli Quti")
async def mystery_box_cmd(message: Message):
    user_id = message.from_user.id
    today_str = str(date.today())
    me = await bot.get_me()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT last_open_date, extra_spins FROM user_boxes WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()

        if not row:
            await db.execute("INSERT INTO user_boxes (user_id, last_open_date, extra_spins) VALUES (?, '', 0)", (user_id,))
            await db.commit()
            can_open = True
        else:
            can_open = (row[0] != today_str) or (row[1] > 0)

    kb = []
    if can_open:
        kb.append([InlineKeyboardButton(text="🎁 Qutini Ochish!", callback_data="open_box")])
    else:
        ref_link = f"https://t.me/{me.username}?start=ref_{user_id}"
        share_url = f"https://t.me/share/url?url={ref_link}&text=Sirli+Qutidan+sovg'alar+ol!+Sinab+ko'r:"
        kb.append([InlineKeyboardButton(text="🚀 Do‘stni chaqirish (+1 Urinish)", url=share_url)])

    await message.answer(
        "🎁 <b>KUNLIK SIRLI QUTI</b>\n\n"
        "Har kuni 1 marta bepul oching va sovg‘alar yutib oling!\n\n"
        + ("🟢 <b>Sizda ochish imkoni mavjud!</b>" if can_open else "⏳ Bugungi bepul imkoningiz tugadi."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "open_box")
async def open_box_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    today_str = str(date.today())
    me = await bot.get_me()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT last_open_date, extra_spins FROM user_boxes WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            last_date, extra_spins = row if row else ('', 0)

        if last_date == today_str and extra_spins <= 0:
            await callback.answer("Bugungi imkoniyatingiz tugagan!", show_alert=True)
            return

        if extra_spins > 0:
            await db.execute("UPDATE user_boxes SET extra_spins = extra_spins - 1 WHERE user_id = ?", (user_id,))
        else:
            await db.execute("UPDATE user_boxes SET last_open_date = ? WHERE user_id = ?", (today_str, user_id))
        await db.commit()

    chance = random.randint(1, 100)
    async with aiosqlite.connect(DB_NAME) as db:
        if chance <= 65:
            prize = "🎉 <b>+3 ta Bepul Limit yutdingiz!</b>"
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 3 WHERE user_id = ?", (user_id,))
        elif chance <= 90:
            prize = "🔥 <b>+5 ta Bepul Limit yutdingiz!</b>"
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 5 WHERE user_id = ?", (user_id,))
        elif chance <= 98:
            prize = "⚡️ <b>1 Kunlik Cheksiz VIP Rejim yutdingiz!</b>"
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 100 WHERE user_id = ?", (user_id,))
        else:
            prize = "👑 <b>JEKPOT! Rasmiy Telegram Gift yutib oldingiz!</b>"
            await bot.send_message(ADMIN_ID, f"🚨 <b>Gift Yutgan Odam!</b> ID: <code>{user_id}</code> (@{callback.from_user.username})", parse_mode="HTML")
        await db.commit()

    ref_link = f"https://t.me/{me.username}?start=ref_{user_id}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Sirli+Qutidan+sovg'alar+ol!+Sinab+ko'r:"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Yana urinish olish (Do‘stga ulashish)", url=share_url)]])

    await callback.message.edit_text(f"📦 <b>Quti ochildi!</b>\n\n{prize}", reply_markup=kb, parse_mode="HTML")

@dp.message(F.text.in_(["🏆 Reyting (/top)", "/top"]))
async def top_cmd(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, referral_count FROM user_rewards ORDER BY referral_count DESC LIMIT 10")

