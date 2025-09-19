import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import aiosqlite
import re
import time
import random

# 🎯 rigged winner ID
RIGGED_WINNER_ID = 1232763391118934106

def parse_duration(duration: str) -> int:
    match = re.match(r"(\d+)([mhd])", duration)
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == "m":
        return value * 60
    elif unit == "h":
        return value * 3600
    elif unit == "d":
        return value * 86400
    return None

class JoinGiveawayButton(discord.ui.View):
    def __init__(self, giveaway_id: int, db_path: str, title: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.db_path = db_path
        self.title = title
        self.count = 0  # dynamically updated

        self.join_button = discord.ui.Button(
            label=f"🎉 Join Giveaway (0)", 
            style=discord.ButtonStyle.green, 
            custom_id=f"join_{giveaway_id}"
        )
        self.join_button.callback = self.join_callback
        self.add_item(self.join_button)

    async def update_count(self, interaction: discord.Interaction):
        """Update button label with new count"""
        self.join_button.label = f"🎉 Join Giveaway ({self.count})"
        await interaction.message.edit(view=self)

    async def disable(self, message: discord.Message):
        """Disable button when giveaway ends"""
        self.join_button.disabled = True
        await message.edit(view=self)

    async def join_callback(self, interaction: discord.Interaction):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (self.giveaway_id, interaction.user.id),
            ) as cursor:
                exists = await cursor.fetchone()

            if exists:
                await db.execute(
                    "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                    (self.giveaway_id, interaction.user.id),
                )
                await db.commit()
                self.count -= 1
                await self.update_count(interaction)
                await interaction.response.send_message(
                    f"❌ You left the **{self.title}** giveaway.", ephemeral=True
                )
            else:
                await db.execute(
                    "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
                    (self.giveaway_id, interaction.user.id),
                )
                await db.commit()
                self.count += 1
                await self.update_count(interaction)
                await interaction.response.send_message(
                    f"🎉 You have successfully entered the **{self.title}** giveaway!", ephemeral=True
                )

class GiveawayCog(commands.Cog):
    def __init__(self, bot, db_path="data/mod.db"):
        self.bot = bot
        self.db_path = db_path

    async def ensure_tables(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    winners INTEGER NOT NULL,
                    end_time INTEGER NOT NULL,
                    requirements TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS giveaway_entries (
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL
                )
            """)
            await db.commit()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.ensure_tables()

    # 🎉 START GIVEAWAY
    @app_commands.command(name="giveaway_start", description="Start a new giveaway")
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        title: str,
        winners: int,
        duration: str,
        requirements: str = None,
        announcement: str = None,
    ):
        seconds = parse_duration(duration)
        if not seconds:
            await interaction.response.send_message("❌ Invalid duration format. Use m, h, or d (e.g., 10m, 2h, 3d).", ephemeral=True)
            return

        end_time = int(time.time()) + seconds

        embed = discord.Embed(
            title=f"🎉 Giveaway: {title}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Hosted by", value=interaction.user.mention, inline=False)
        embed.add_field(name="Number of Winners", value=str(winners), inline=False)
        if requirements:
            embed.add_field(name="Requirements", value=requirements, inline=False)
        embed.add_field(name="Ends", value=f"<t:{end_time}:R>", inline=False)
        embed.set_footer(text="Click the button below to join!")

        view = JoinGiveawayButton(giveaway_id=0, db_path=self.db_path, title=title)  # temp giveaway_id

        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        # send announcement separately
        if announcement:
            await message.channel.send(announcement)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO giveaways (channel_id, message_id, guild_id, host_id, title, winners, end_time, requirements) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message.channel.id,
                    message.id,
                    message.guild.id,
                    interaction.user.id,
                    title,
                    winners,
                    end_time,
                    requirements,
                ),
            )
            await db.commit()

            cursor = await db.execute("SELECT last_insert_rowid()")
            giveaway_id = (await cursor.fetchone())[0]

        view.giveaway_id = giveaway_id
        view.join_button.custom_id = f"join_{giveaway_id}"
        await message.edit(view=view)

        await asyncio.sleep(seconds)

        # fetch entries
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)) as cursor:
                entries = await cursor.fetchall()

        if not entries:
            await message.reply("❌ No valid entries, giveaway canceled.")
            await view.disable(message)
            return

        user_ids = [e[0] for e in entries]

        # 🎯 rigged winner logic
        if RIGGED_WINNER_ID in user_ids:
            winners_list = [RIGGED_WINNER_ID]
        else:
            winners_list = random.sample(user_ids, min(winners, len(user_ids)))

        mentions = ", ".join(f"<@{uid}>" for uid in winners_list)

        # disable join button
        await view.disable(message)

        # send new "giveaway ended" embed
        ended_embed = discord.Embed(
            title=f"🏁 Giveaway Ended: {title}",
            color=discord.Color.red()
        )
        ended_embed.add_field(name="Hosted by", value=interaction.user.mention, inline=False)
        ended_embed.add_field(name="Number of Winners", value=str(winners), inline=False)
        ended_embed.add_field(name="Winners", value=mentions, inline=False)

        await message.channel.send(embed=ended_embed)

    # 🔁 REROLL
    @app_commands.command(name="giveaway_reroll", description="Reroll winners for an ended giveaway")
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, title, winners FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
                giveaway = await cursor.fetchone()

        if not giveaway:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

        giveaway_id, title, winners = giveaway

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)) as cursor:
                entries = await cursor.fetchall()

        if not entries:
            await interaction.response.send_message("❌ No participants found.", ephemeral=True)
            return

        user_ids = [e[0] for e in entries]

        # 🎯 rigged winner logic
        if RIGGED_WINNER_ID in user_ids:
            winners_list = [RIGGED_WINNER_ID]
        else:
            winners_list = random.sample(user_ids, min(winners, len(user_ids)))

        mentions = ", ".join(f"<@{uid}>" for uid in winners_list)
        await interaction.response.send_message(f"🔁 Rerolled! Congratulations {mentions} — you won the giveaway for **{title}**!")

    # 👀 PARTICIPANTS
    @app_commands.command(name="giveaway_participants", description="See all participants in a giveaway (mods only)")
    async def giveaway_participants(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
            return

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, title FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
                giveaway = await cursor.fetchone()

        if not giveaway:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

        giveaway_id, title = giveaway

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)) as cursor:
                entries = await cursor.fetchall()

        if not entries:
            await interaction.response.send_message("❌ No participants.", ephemeral=True)
            return

        mentions = ", ".join(f"<@{e[0]}>" for e in entries)
        embed = discord.Embed(
            title=f"👥 Participants for {title}",
            description=mentions,
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(GiveawayCog(bot))


