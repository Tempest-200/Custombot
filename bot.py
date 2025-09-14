import os
import asyncio
from discord.ext import commands
import logging
from keep_alive import keep_alive
import aiosqlite


logging.basicConfig(level=logging.INFO)


PREFIX = os.getenv("PREFIX", ".")
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("MOD_DB", "data/mod.db")


intents = commands.Intents.default()
intents.members = True
intents.guilds = True


bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("------")


async def ensure_db():
# create data folder and tables if needed
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
async with aiosqlite.connect(DB_PATH) as db:
await db.execute('''
CREATE TABLE IF NOT EXISTS warns (
id INTEGER PRIMARY KEY AUTOINCREMENT,
guild_id INTEGER NOT NULL,
user_id INTEGER NOT NULL,
mod_id INTEGER NOT NULL,
reason TEXT,
created_at INTEGER NOT NULL,
expires_at INTEGER,
permanent INTEGER DEFAULT 0
)
''')
await db.execute('''
CREATE TABLE IF NOT EXISTS punishments (
id INTEGER PRIMARY KEY AUTOINCREMENT,
guild_id INTEGER NOT NULL,
user_id INTEGER NOT NULL,
type TEXT NOT NULL, -- mute or tempban
expires_at INTEGER NOT NULL
)
''')
await db.commit()


async def main():
await ensure_db()
# load cogs
bot.add_cog(await __import__("cogs.mod", fromlist=["ModCog"]).ModCog(bot, DB_PATH))


keep_alive() # start flask server in thread


if not TOKEN:
raise RuntimeError("DISCORD_TOKEN environment variable not set")


await bot.start(TOKEN)


if __name__ == "__main__":
try:
asyncio.run(main())
except KeyboardInterrupt:
logging.info("Shutting down")
