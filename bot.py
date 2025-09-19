import os
import asyncio
import logging
import aiosqlite
import discord
from discord.ext import commands
from discord import app_commands
from keep_alive import keep_alive
from cogs.mod import ModCog

logging.basicConfig(level=logging.INFO)

PREFIX = os.getenv("PREFIX", ".")
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("MOD_DB", "data/mod.db")

# ✅ Intents
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# -------- SLASH COMMAND SYNC --------
@bot.event
async def on_ready():
    await bot.tree.sync()   # 🔑 syncs slash commands
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("Slash commands synced ✅")
    logging.info("------")

# ✅ Owner-only say command
@bot.command(name="say")
@commands.is_owner()
async def say(ctx, *, message: str):
    await ctx.message.delete()  # delete your command message (optional)
    await ctx.send(message)

# ✅ Database setup
async def ensure_db():
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
                type TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
        ''')
        await db.commit()

# ✅ Main loop
async def main():
    await ensure_db()
    await bot.add_cog(ModCog(bot, DB_PATH))

    # 👇 Load your giveaway cog too
    await bot.load_extension("cogs.giveaway_cog")

    keep_alive()

    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable not set")

    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down")

