import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import asyncio
import re
import time
import random
from typing import Optional

DB_PATH = "giveaways.db"
RIGGED_ID = 1232763391118934106  # <-- your rigged Discord ID (as int)

DURATION_RE = re.compile(r"^(\d+)([mhd])$")  # minutes/hours/days

def parse_duration(s: str) -> Optional[int]:
    m = DURATION_RE.match(s.lower().strip())
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return val * 60
    if unit == "h":
        return val * 3600
    if unit == "d":
        return val * 86400
    return None

class GiveawayDB:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        c = self.conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER UNIQUE,
            channel_id INTEGER,
            guild_id INTEGER,
            title TEXT,
            requirements TEXT,
            host_id INTEGER,
            winners INTEGER,
            end_ts INTEGER,
            active INTEGER DEFAULT 1
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            giveaway_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (giveaway_id, user_id)
        )
        """)
        self.conn.commit()

    def add_giveaway(self, message_id, channel_id, guild_id, title, requirements, host_id, winners, end_ts):
        c = self.conn.cursor()
        c.execute("""
        INSERT INTO giveaways (message_id, channel_id, guild_id, title, requirements, host_id, winners, end_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (message_id, channel_id, guild_id, title, requirements, host_id, winners, end_ts))
        self.conn.commit()
        return c.lastrowid

    def end_giveaway(self, message_id):
        c = self.conn.cursor()
        c.execute("UPDATE giveaways SET active = 0 WHERE message_id = ?", (message_id,))
        self.conn.commit()

    def get_active_giveaways(self):
        c = self.conn.cursor()
        c.execute("SELECT * FROM giveaways WHERE active = 1")
        return c.fetchall()

    def get_giveaway_by_message(self, message_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM giveaways WHERE message_id = ?", (message_id,))
        return c.fetchone()

    def add_entry(self, message_id, user_id):
        g = self.get_giveaway_by_message(message_id)
        if not g:
            return False
        c = self.conn.cursor()
        try:
            c.execute("INSERT INTO entries (giveaway_id, user_id) VALUES (?, ?)", (g["id"], user_id))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_entry(self, message_id, user_id):
        g = self.get_giveaway_by_message(message_id)
        if not g:
            return False
        c = self.conn.cursor()
        c.execute("DELETE FROM entries WHERE giveaway_id = ? AND user_id = ?", (g["id"], user_id))
        self.conn.commit()
        return c.rowcount > 0

    def get_entries(self, message_id):
        g = self.get_giveaway_by_message(message_id)
        if not g:
            return []
        c = self.conn.cursor()
        c.execute("SELECT user_id FROM entries WHERE giveaway_id = ?", (g["id"],))
        return [row["user_id"] for row in c.fetchall()]

    def delete_giveaway(self, message_id):
        g = self.get_giveaway_by_message(message_id)
        if not g:
            return False
        c = self.conn.cursor()
        c.execute("DELETE FROM entries WHERE giveaway_id = ?", (g["id"],))
        c.execute("DELETE FROM giveaways WHERE id = ?", (g["id"],))
        self.conn.commit()
        return True

db = GiveawayDB()

class GiveawayView(discord.ui.View):
    def __init__(self, bot: commands.Bot, message_id: int, timeout=None):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.message_id = message_id

    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.success, custom_id="giveaway_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Add entry
        added = db.add_entry(self.message_id, interaction.user.id)
        if added:
            await interaction.response.send_message("You have entered the giveaway ✅", ephemeral=True)
        else:
            # Already entered -> remove them as "toggle"
            removed = db.remove_entry(self.message_id, interaction.user.id)
            if removed:
                await interaction.response.send_message("You have removed your entry from the giveaway ❌", ephemeral=True)
            else:
                await interaction.response.send_message("Could not enter giveaway (maybe it ended).", ephemeral=True)

class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = db
        self.check_task.start()

    def cog_unload(self):
        self.check_task.cancel()

    @tasks.loop(seconds=30.0)
    async def check_task(self):
        # Runs every 30s to check expired giveaways
        now = int(time.time())
        active = self.db.get_active_giveaways()
        for g in active:
            if g["end_ts"] <= now:
                await self.finish_giveaway(g)

    async def finish_giveaway(self, g_row):
        message_id = g_row["message_id"]
        channel_id = g_row["channel_id"]
        winners_count = g_row["winners"]
        title = g_row["title"]

        entries = self.db.get_entries(message_id)
        # ensure unique
        entries = list(dict.fromkeys(entries))

        # rigging logic:
        winners = []
        rigged_user = RIGGED_ID
        if rigged_user in entries:
            # include rigged user first
            winners.append(rigged_user)
            remaining_pool = [u for u in entries if u != rigged_user]
            if len(remaining_pool) > 0 and len(winners) < winners_count:
                take = min(winners_count - len(winners), len(remaining_pool))
                winners.extend(random.sample(remaining_pool, take))
        else:
            # fallback to random selection if not rigged-entered
            if len(entries) <= winners_count:
                winners = entries[:]  # all entrants
            else:
                winners = random.sample(entries, winners_count)

        # mark ended
        self.db.end_giveaway(message_id)

        # announce winners in channel
        channel = self.bot.get_channel(channel_id)
        if not channel:
            # try fetch
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                channel = None

        # Edit original giveaway message to show finished state if possible
        try:
            if channel:
                try:
                    msg = await channel.fetch_message(message_id)
                    embed = discord.Embed(title=f"🎉 Giveaway Ended: {title}", color=discord.Color.gold())
                    if winners:
                        mention_list = ", ".join(f"<@{uid}>" for uid in winners)
                        embed.add_field(name="Winners", value=mention_list, inline=False)
                    else:
                        embed.add_field(name="Winners", value="No valid entries", inline=False)
                    embed.set_footer(text="Giveaway ended")
                    await msg.edit(embed=embed, view=None)
                except discord.NotFound:
                    pass
        except Exception:
            pass

        # send announcement
        if channel:
            if winners:
                text = "Congratulations " + ", ".join(f"<@{uid}>" for uid in winners) + " — you won!"
                await channel.send(content=text)
            else:
                await channel.send(content="Giveaway ended — no winners.")

    @app_commands.command(name="giveaway_start", description="Start a giveaway")
    @app_commands.describe(
        title="Title of the giveaway",
        winners="How many winners (integer)",
        duration="Duration like 10m, 2h, 1d",
        requirements="Optional requirements text (e.g., Level Requirement: 10)",
        host="Host (mention a user) — defaults to you"
    )
    async def giveaway_start(self, interaction: discord.Interaction,
                             title: str,
                             winners: int = 1,
                             duration: str = "1h",
                             requirements: Optional[str] = None,
                             host: Optional[discord.Member] = None):
        # Permissions: allow only users with manage_guild or send permission to run
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("You need Manage Server/Messages permission to start giveaways.", ephemeral=True)
            return

        seconds = parse_duration(duration)
        if seconds is None:
            await interaction.response.send_message("Invalid duration format. Use e.g. `10m`, `2h`, `1d`.", ephemeral=True)
            return

        if winners < 1:
            await interaction.response.send_message("Winners must be at least 1.", ephemeral=True)
            return

        host_user = host or interaction.user
        end_ts = int(time.time()) + seconds

        # Build embed
        embed = discord.Embed(title=f"🎉 {title}", color=discord.Color.blue())
        if requirements:
            embed.add_field(name="Requirements", value=requirements, inline=False)
        embed.add_field(name="Hosted by", value=f"<@{host_user.id}>", inline=False)
        # Composer: shows ends at relative timestamp
        embed.add_field(name="Ends", value=f"<t:{end_ts}:R>", inline=False)
        embed.set_footer(text=f"Winners: {winners}")

        view = GiveawayView(self.bot, message_id=0)  # temp; will update after sending

        # Send the giveaway embed
        await interaction.response.send_message(embed=embed, view=view)
        sent = await interaction.original_response()

        # Persist the giveaway using message id
        db.add_giveaway(sent.id, sent.channel.id, sent.guild.id, title, requirements or "", host_user.id, winners, end_ts)

        # update view with real message id and re-edit message (so the button knows the message id)
        view.message_id = sent.id
        try:
            await sent.edit(view=view)
        except Exception:
            pass

        await interaction.followup.send("Giveaway started!", ephemeral=True)

    @app_commands.command(name="giveaway_participants", description="List participants for a giveaway (mods only)")
    @app_commands.describe(message_id="Message ID of the giveaway message")
    async def giveaway_participants(self, interaction: discord.Interaction, message_id: str):
        # mod-only shortcut
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only mods can view participants.", ephemeral=True)
            return

        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Invalid message ID.", ephemeral=True)
            return

        entries = db.get_entries(mid)
        if not entries:
            await interaction.response.send_message("No participants or giveaway not found.", ephemeral=True)
            return

        # Build paginated message if large (just send a simple list)
        chunk = []
        for uid in entries:
            chunk.append(f"<@{uid}> (`{uid}`)")
        out = "\n".join(chunk)
        await interaction.response.send_message(f"Participants ({len(entries)}):\n{out}", ephemeral=True)

    @app_commands.command(name="giveaway_cancel", description="Cancel and remove a giveaway (mods only)")
    async def giveaway_cancel(self, interaction: discord.Interaction, message_id: str):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Only mods can cancel giveaways.", ephemeral=True)
            return
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("Invalid message ID.", ephemeral=True)
            return
        ok = db.delete_giveaway(mid)
        if ok:
            await interaction.response.send_message("Giveaway removed from DB. If message exists, you may want to delete it.", ephemeral=True)
            # try to edit the message to say cancelled
            try:
                # find channel by searching giveaways
                # quick fetch:
                g = db.get_giveaway_by_message(mid)
                # note: we already deleted, so we might not find it. ignore.
            except Exception:
                pass
        else:
            await interaction.response.send_message("Could not find giveaway with that message ID.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
