import discord
from discord.ext import commands
import time
import asyncio
import aiosqlite
from datetime import datetime, timedelta

DATE_FMT = "%B %d, %Y at %I:%M %p"
LOG_CHANNEL_ID = 1417097768744517753  # logging channel

class ModCog(commands.Cog):
    def __init__(self, bot: commands.Bot, db_path: str):
        self.bot = bot
        self.db_path = db_path

    async def setup_hook(self):
        asyncio.create_task(self._restore_punishments())

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
        return None

    async def _send_dm_and_log(self, member, ctx, action, reason, duration=None, expires_at=None, warns=None):
        """Helper for punishment embeds"""
        embed = discord.Embed(
            title=f"You have been {action} in/from Dex Server",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        if duration:
            embed.add_field(name="Duration", value=duration, inline=False)
        if warns is not None:
            embed.add_field(name="Warn Count", value=f"{warns} active warns", inline=False)
        if expires_at:
            embed.add_field(name="Expires", value=expires_at.strftime(DATE_FMT), inline=False)
        embed.add_field(name="Responsible Moderator", value=ctx.author.mention, inline=False)

        try:
            await member.send(embed=embed)
        except Exception:
            pass

        log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            log_embed = discord.Embed(
                title=f"Moderation Action: {action.title()}",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            log_embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            log_embed.add_field(name="Reason", value=reason, inline=False)
            if duration:
                log_embed.add_field(name="Duration", value=duration, inline=False)
            if warns is not None:
                log_embed.add_field(name="Warn Count", value=f"{warns} active warns", inline=False)
            if expires_at:
                log_embed.add_field(name="Expires", value=expires_at.strftime(DATE_FMT), inline=False)
            log_embed.add_field(name="Responsible Moderator", value=ctx.author.mention, inline=False)
            await log_channel.send(embed=log_embed)

    # ---------------- COMMANDS ---------------- #

    @commands.command()
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        """Warn a user (2 warns = mute)."""
        await self._add_warn(ctx.guild.id, member.id, ctx.author.id, reason, permanent=False)
        warns = await self._count_unexpired_warns(ctx.guild.id, member.id)

        # Chat confirmation
        await ctx.send(f"⚠️ {member.mention} has been warned.")

        expires_at = datetime.utcnow() + timedelta(days=60)
        await self._send_dm_and_log(member, ctx, "warned", reason, expires_at=expires_at, warns=warns)

        if warns >= 2:  # auto-mute
            role = await self._ensure_muted_role(ctx.guild)
            await member.add_roles(role, reason="Auto-mute after 2 warns")
            await ctx.send(f"🔇 {member.mention} has been auto-muted for accumulating 2 warns.")
            await self._send_dm_and_log(member, ctx, "muted (auto)", "Reached 2 warns")

    @commands.command()
    async def mute(self, ctx, member: discord.Member, duration: str = None, *, reason: str = "No reason"):
        """Mute a user (supports duration like 10m, 2h, 7d)."""
        role = await self._ensure_muted_role(ctx.guild)
        await member.add_roles(role, reason=reason)
        await ctx.send(f"🔇 {member.mention} has been muted.")

        delta = self._parse_duration(duration)
        if delta:
            expires_at = datetime.utcnow() + delta
            await self._send_dm_and_log(member, ctx, "muted", reason, duration, expires_at)
            await asyncio.sleep(delta.total_seconds())
            await member.remove_roles(role, reason="Temporary mute expired")
            await ctx.send(f"🔊 {member.mention} has been unmuted (mute expired).")
        else:
            await self._send_dm_and_log(member, ctx, "muted", reason)

    @commands.command()
    async def unmute(self, ctx, member: discord.Member):
        """Unmute a user manually."""
        role = await self._ensure_muted_role(ctx.guild)
        if role in member.roles:
            await member.remove_roles(role, reason="Manual unmute")
            await ctx.send(f"🔊 {member.mention} has been unmuted.")
            await self._send_dm_and_log(member, ctx, "unmuted", "Manual unmute")
        else:
            await ctx.send("That user is not muted.")

    @commands.command()
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        """Kick a user."""
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member} has been kicked.")
        await self._send_dm_and_log(member, ctx, "kicked", reason)

    @commands.command()
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason"):
        """Ban a user."""
        await member.ban(reason=reason)
        await ctx.send(f"🔨 {member} has been banned.")
        await self._send_dm_and_log(member, ctx, "banned", reason)

    @commands.command()
    async def unban(self, ctx, user_id: int):
        """Unban a user by ID."""
        user = await self.bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"♻️ {user} has been unbanned.")
        # Send only to logs, can't DM banned user
        log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(
                title="Moderation Action: Unban",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
            embed.add_field(name="Responsible Moderator", value=ctx.author.mention, inline=False)
            await log_channel.send(embed=embed)

    @commands.command()
    async def tempban(self, ctx, member: discord.Member, duration: str, *, reason: str = "No reason"):
        """Temporarily ban a user."""
        delta = self._parse_duration(duration)
        if not delta:
            return await ctx.send("Invalid duration. Use format like `10m`, `2h`, `7d`.")
        await member.ban(reason=reason)
        await ctx.send(f"⏳ {member} has been temp-banned for {duration}.")
        expires_at = datetime.utcnow() + delta
        await self._send_dm_and_log(member, ctx, "temp-banned", reason, duration, expires_at)
        await asyncio.sleep(delta.total_seconds())
        await ctx.guild.unban(member)
        await ctx.send(f"♻️ {member} has been unbanned (tempban expired).")

    # ---------------- TASKS ---------------- #

    async def _restore_punishments(self):
        """Future: restore mutes/tempbans from DB if you add persistence."""
        pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCog(bot, db_path="mod.db"))
