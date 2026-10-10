import aiosqlite
from datetime import date

DB_NAME = "bot_database.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                requests_count INTEGER DEFAULT 0,
                last_date TEXT
            )
        """)
        await db.commit()

async def check_and_use_limit(user_id: int, daily_limit: int = 10) -> bool:
    today = str(date.today())
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT requests_count, last_date FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        
        if row is None:
            await db.execute("INSERT INTO users (user_id, requests_count, last_date) VALUES (?, 1, ?)", (user_id, today))
            await db.commit()
            return True
        
        count, last_date = row
        if last_date != today:
            await db.execute("UPDATE users SET requests_count = 1, last_date = ? WHERE user_id = ?", (today, user_id))
            await db.commit()
            return True
        else:
            if count < daily_limit:
                await db.execute("UPDATE users SET requests_count = requests_count + 1 WHERE user_id = ?", (user_id,))
                await db.commit()
                return True
            return False
