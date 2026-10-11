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
                    msg = "🎉 Yangi do'stingiz qo'shildi! +4 limit va +1 Sirli Quti berildi!"
                    await bot.send_message(inviter_id, msg)
                except Exception:
                    pass
            await db.commit()

    text = (
        f"Assalomu alaykum, {message.from_user.first_name}! 👋\n\n"
        "Men BirZum AI — ko'p funksiyali yordamchingizman:\n"
        "▫️ Dars/Masala: Rasm yuboring, yechib beraman.\n"
        "▫️ Voice-to-Text: Ovozli xabarni matnga aylantirib beraman.\n"
        "▫️ Media Yuklash: Reels, TikTok yoki YouTube havolasi yuboring.\n\n"
        "🎁 Har kuni 4 ta bepul so'rov va 1 ta Sirli Quti mavjud!"
    )
    await message.answer(text, reply_markup=get_main_menu())

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
        share_url = f"https://t.me/share/url?url={ref_link}&text=Sirli+Qutidan+sovg'alar+ol!"
        kb.append([InlineKeyboardButton(text="🚀 Do'stni chaqirish (+1 Urinish)", url=share_url)])

    holat = "🟢 Sizda ochish imkoni mavjud!" if can_open else "⏳ Bugungi bepul imkoningiz tugadi."
    await message.answer(f"🎁 KUNLIK SIRLI QUTI\n\n{holat}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

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
            prize = "🎉 +3 ta Bepul Limit yutdingiz!"
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 3 WHERE user_id = ?", (user_id,))
        elif chance <= 90:
            prize = "🔥 +5 ta Bepul Limit yutdingiz!"
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 5 WHERE user_id = ?", (user_id,))
        elif chance <= 98:
            prize = "⚡️ 1 Kunlik Cheksiz VIP Rejim yutdingiz!"
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits + 100 WHERE user_id = ?", (user_id,))
        else:
            prize = "👑 JEKPOT! Rasmiy Telegram Gift yutib oldingiz!"
            admin_msg = f"🚨 Gift Yutildi! ID: {user_id} (@{callback.from_user.username})"
            await bot.send_message(ADMIN_ID, admin_msg)
        await db.commit()

    ref_link = f"https://t.me/{me.username}?start=ref_{user_id}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Sirli+Qutidan+sovg'alar+ol!"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Yana urinish olish", url=share_url)]])
    await callback.message.edit_text(f"📦 Quti ochildi!\n\n{prize}", reply_markup=kb)

@dp.message(F.text.in_(["🏆 Reyting (/top)", "/top"]))
async def top_cmd(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, referral_count FROM user_rewards ORDER BY referral_count DESC LIMIT 10") as cur:
            rows = await cur.fetchall()

    text = "🏆 Eng Ko'p Do'st Taklif Qilganlar (TOP-10):\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, cnt) in enumerate(rows, 1):
        m = medals[i-1] if i <= 3 else f"{i}."
        text += f"{m} ID: {uid} — {cnt} ta do'st\n"
    await message.answer(text)

@dp.message(F.text.in_(["⭐️ Telegram Premium & Gift", "/rewards"]))
async def rewards_cmd(message: Message):
    user_id = message.from_user.id
    me = await bot.get_me()

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT referral_count FROM user_rewards WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0

    target = 15 if count < 15 else (30 if count < 30 else 50)
    bar = render_progress_bar(count, target)

    kb = [[InlineKeyboardButton(text="📲 Do'stlarga ulashish", url=f"https://t.me/share/url?url=https://t.me/{me.username}?start=ref_{user_id}&text=Zo'r+bot!")] ]
    if count >= 50:
        kb.append([InlineKeyboardButton(text="🌟 1 Oylik Premium olish", callback_data="claim_PREMIUM")])
    elif count >= 30:
        kb.append([InlineKeyboardButton(text="⭐️ 50 ta Stars olish", callback_data="claim_STARS")])
    elif count >= 15:
        kb.append([InlineKeyboardButton(text="🎁 Gift olish", callback_data="claim_GIFT")])

    text = (
        f"🏆 Sovg'alar Markazi\n\nTaklif qilingan do'stlar: {count} ta\n"
        f"Progress: {bar}\n\n"
        f"🔗 Havolangiz:\nhttps://t.me/{me.username}?start=ref_{user_id}"
    )
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("claim_"))
async def claim_cb(callback: CallbackQuery):
    reward = callback.data.split("_")[1]
    await callback.answer("So'rovingiz adminga yuborildi!", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)
    admin_notif = f"🚨 Sovg'a Talabi! Foydalanuvchi: {callback.from_user.id} (@{callback.from_user.username}) | Sovg'a: {reward}"
    await bot.send_message(ADMIN_ID, admin_notif)

@dp.message(F.photo)
async def handle_photo_ai(message: Message):
    if not await check_and_use_limit(message.from_user.id):
        await message.reply("⏳ Kunlik limitingiz tugadi! Do'stingizni taklif qiling.")
        return

    wait = await message.reply("🔍 Rasm tahlil qilinmoqda...")
    buf = io.BytesIO()
    await bot.download(message.photo[-1], destination=buf)
    img_bytes = buf.getvalue()
    buf.close()

    caption = message.caption or ""
    is_screen = any(w in caption.lower() for w in ["skrin", "ekran", "nima bu", "qayerga", "tugma"])
    if is_screen:
        prompt = "Sen mobil/dastur UI yordamchisisan. Skrinshotni o'rganib: 1. Qisqa mohiyati; 2. Matn tarjimasi; 3. Foydalanuvchi aynan qaysi tugmani bosishi kerakligini o'zbek tilida yoz."
    else:
        prompt = "Sen o'qituvchisan. Rasmdagi masala yoki testni qadamma-qadam yechib, to'g'ri javobni o'zbek tilida tushuntir."

    try:
        res = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"inline_data": {"mime_type": "image/jpeg", "data": img_bytes}}, prompt]
        )
        await wait.edit_text(res.text.strip())
    except Exception as e:
        await wait.edit_text(f"Xatolik: {e}")

@dp.message(F.voice)
async def handle_voice_msg(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Matnga o'girish", callback_data=f"v2t_{message.voice.file_id}")]
    ])
    await message.reply("Ovozli xabar qabul qilindi.", reply_markup=kb)

@dp.callback_query(F.data.startswith("v2t_"))
async def voice_to_text_cb(callback: CallbackQuery):
    if not await check_and_use_limit(callback.from_user.id):
        await callback.answer("Kunlik limitingiz tugagan!", show_alert=True)
        return

    await callback.message.edit_text("🎙 Ovoz matnga aylantirilmoqda...")
    file_id = callback.data.replace("v2t_", "")
    file_info = await bot.get_file(file_id)

    buf = io.BytesIO()
    await bot.download_file(file_info.file_path, destination=buf)
    audio_bytes = buf.getvalue()
    buf.close()

    try:
        res = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {"inline_data": {"mime_type": "audio/ogg", "data": audio_bytes}},
                "Ushbu audio yozuvdagi so'zlarni to'liq matn qilib yoz va qisqa xulosa ber."
            ]
        )
        await callback.message.edit_text(res.text.strip())
    except Exception as e:
        await callback.message.edit_text(f"Xatolik: {e}")

@dp.message(F.text.regexp(r'(https?://[^\s]+)'))
async def handle_media_download(message: Message):
    url = message.text.strip()
    if not any(d in url for d in ["instagram.com", "tiktok.com", "youtube.com", "youtu.be"]):
        return

    if not await check_and_use_limit(message.from_user.id):
        await message.reply("⏳ Kunlik limitingiz tugagan!")
        return

    wait = await message.reply("📥 Video yuklab olinmoqda...")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        out_tmpl = tmp.name

    ydl_opts = {
        'outtmpl': out_tmpl,
        'format': 'best[ext=mp4]/best',
        'max_filesize': 50 * 1024 * 1024,
        'quiet': True
    }

    loop = asyncio.get_event_loop()
    def download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    try:
        await loop.run_in_executor(None, download)
        await wait.delete()
        await message.reply_video(FSInputFile(out_tmpl), caption="🎬 @BirZum_bot orqali yuklandi")
    except Exception as e:
        await wait.edit_text("❌ Videoni yuklab bo'lmadi.")
    finally:
        if os.path.exists(out_tmpl):
            os.remove(out_tmpl)

@dp.message(Command("send"), F.from_user.id == ADMIN_ID)
async def broadcast_cmd(message: Message):
    if not message.reply_to_message:
        await message.reply("Postga reply qilib /send deb yozing!")
        return

    src = message.reply_to_message
    status = await message.answer("⏳ Tarqatilmoqda...")
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT DISTINCT user_id FROM user_rewards") as cur:
            users = await cur.fetchall()

    sent, blocked = 0, 0
    for (uid,) in users:
        try:
            await src.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            blocked += 1

    await status.edit_text(f"✅ Tugatildi! Yuborildi: {sent} ta")

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌍 Web server started on port {port}")

async def main():
    await init_db()
    await start_web_server()
    print("🤖 Bot muvaffaqiyatli ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()


