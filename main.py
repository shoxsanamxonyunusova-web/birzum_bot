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
    user_id = message.from_


