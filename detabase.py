import aiosqlite
from datetime import date
from config import DB_NAME

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL;")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_limits (
                user_id INTEGER PRIMARY KEY,
                last_active_date TEXT,
                daily_used INTEGER DEFAULT 0,
                bonus_limits INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_rewards (
                user_id INTEGER PRIMARY KEY,
                inviter_id INTEGER,
                referral_count INTEGER DEFAULT 0,
                claimed_gift INTEGER DEFAULT 0,
                claimed_stars INTEGER DEFAULT 0,
                claimed_premium INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_boxes (
                user_id INTEGER PRIMARY KEY,
                last_open_date TEXT,
                extra_spins INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def check_and_use_limit(user_id: int) -> bool:
    today_str = str(date.today())
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT last_active_date, daily_used, bonus_limits FROM user_limits WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()

        if not row:
            await db.execute("INSERT INTO user_limits (user_id, last_active_date, daily_used, bonus_limits) VALUES (?, ?, 1, 0)", (user_id, today_str))
            await db.commit()
            return True

        last_date, daily_used, bonus_limits = row
        if last_date != today_str:
            daily_used = 0
            last_date = today_str

        if daily_used < 4:
            await db.execute("UPDATE user_limits SET last_active_date = ?, daily_used = daily_used + 1 WHERE user_id = ?", (last_date, user_id))
            await db.commit()
            return True
        elif bonus_limits > 0:
            await db.execute("UPDATE user_limits SET bonus_limits = bonus_limits - 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            return True
        else:
            return False
