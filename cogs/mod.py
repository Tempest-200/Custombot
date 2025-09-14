import discord
from discord.ext import commands
import time
import asyncio
import aiosqlite
from datetime import datetime, timedelta

DATE_FMT = "%B %d, %Y at %I:%M %p"

class ModCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db_path: str):
        self.bot = bot
        self.db_path = db_path
        self.bot.loop.create_task(self._restore_punishments())

    @staticmethod
    def _timestamp(dt: datetime) -> str:
        return dt.strftime(DATE_FMT)

    # ---------------- WARN SYSTEM ---------------- #

    async def _add_warn(self, guild_id: int, user_id: int, mod_id: int, reason: str, permanent: bool):
        created = int(time.time())
        expires = None
        if not permanent:
            expires = int((datetime.utcfromtimestamp(created) + timedelta(days=60)).timestamp())
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO warns (guild_id, user_id, mod_id, reason, created_at, expires_at, permanent) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, mod_id, reason, created, expires, 1 if permanent else 0)
            )
            await db.commit()

    async def _count_unexpired_warns(self, guild_id: int, user_id: int) -> int:
        now = int(time.time())
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=? AND (permanent=1 OR expires_at IS NULL OR expires_at>?)",
                (guild_id, user_id, now)
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    # ---------------- UTILS ---------------- #

    async def _ensure_muted_role(self, guild: discord.Guild) -> discord.Role:
        role = discord.utils.get(guild.roles, name="Muted")
        if role is None:
            role = await guild.create_role(name="Muted", reason="Create Muted role for moderation bot")
            for ch in guild.channels:
                try:
                    if isinstance(ch, discord.abc.GuildChannel):
                        await ch.set_permissions(role, send_messages=False, speak=False, add_reactions=False)
                except Exception:
                    pass
        return role

    def _parse_duration(self, s: str):
        if not s:
            return None
        unit = s[-1].lower()
        try:
            num = int(s[:-1])
        except Exception:
            return None
        if unit == 'm':
            return timedelta(minutes=num)
        if unit == 'h':
            return timedelta(hours=num)
        if unit == 'd':
            return timedelta(days=num)

