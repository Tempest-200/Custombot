import os
import asyncio
import logging
import aiosqlite
import discord
from discord.ext import commands
from keep_alive import keep_alive
from cogs.mod import ModCog  # changed import and removed await on constructor

logging.basicConfig(level=logging.INFO)

PREFIX = os.getenv("PREFIX", ".")
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("MOD_DB", "data/mod.db")

# Corrected: Intents come from discord, with privileged intents enabled
intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # required for mute, warns, etc.
intents.message_content = False  # enable True only if reading messages

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("------")

async def ensure_db():
    # Create data folder if it doesn't exist
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

    # Load the moderation cog
    await bot.add_cog(ModCog(bot, DB_PATH))  # <- no 'await' on constructor

    # Start the keep-alive server
    keep_alive()

    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable not set")

    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down")

