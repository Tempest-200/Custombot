import os
import asyncio
import logging
import aiosqlite
import discord
from discord.ext import commands
from keep_alive import keep_alive
from cogs.mod import ModCog

logging.basicConfig(level=logging.INFO)

PREFIX = os.getenv("PREFIX", ".")
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("MOD_DB", "data/mod.db")

# Corrected: Intents come from discord, with privileged intents enabled
intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # required for mute, warns, etc.
intents.message_content = True  # ✅ MUST be True for prefix commands

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("------")

# ✅ Test command
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# ✅ Custom help command
@bot.command(name="help")
async def custom_help(ctx):
    embed = discord.Embed(
        title="📘 Moderation Commands",
        description="Here are all available moderation commands and their usage.",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="⚠️ Warn",
        value=f"**Usage:** `{PREFIX}warn <user_id|@mention> [reason]`\nWarns a user. 2 warns = auto mute.",
        inline=False
    )
    embed.add_field(
        name="🔇 Mute",
        value=f"**Usage:** `{PREFIX}mute <user_id|@mention> [duration] [reason]`\nMute a user (e.g. `10m`, `2h`, `7d`).",
        inline=False
    )
    embed.add_field(
        name="🔊 Unmute",
        value=f"**Usage:** `{PREFIX}unmute <user_id|@mention>`\nUnmutes a user manually.",
        inline=False
    )
    embed.add_field(
        name="👢 Kick",
        value=f"**Usage:** `{PREFIX}kick <user_id|@mention> [reason]`\nKicks a user from the server.",
        inline=False
    )
    embed.add_field(
        name="🔨 Ban",
        value=f"**Usage:** `{PREFIX}ban <user_id|@mention> [reason]`\nBans a user permanently.",
        inline=False
    )
    embed.add_field(
        name="♻️ Unban",
        value=f"**Usage:** `{PREFIX}unban <user_id>`\nUnbans a user by ID.",
        inline=False
    )
    embed.add_field(
        name="⏳ Tempban",
        value=f"**Usage:** `{PREFIX}tempban <user_id|@mention> <duration> [reason]`\nBans a user temporarily (e.g. `10m`, `2h`, `7d`).",
        inline=False
    )
    embed.add_field(
        name="🏓 Ping",
        value=f"**Usage:** `{PREFIX}ping`\nChecks if the bot is alive.",
        inline=False
    )

    embed.set_footer(text="Dex Moderation Bot • Use commands responsibly ✅")

    await ctx.send(embed=embed)

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
                type TEXT NOT NULL, -- mute or tempban
                expires_at INTEGER NOT NULL
            )
        ''')
        await db.commit()

async def main():
    await ensure_db()
    await bot.add_cog(ModCog(bot, DB_PATH))
    keep_alive()

    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable not set")

    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down")


