import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.app_commands import Choice # For scope parameter
import logging
from typing import Literal # For scope type hint

# Use updated persistence
from utils import persistence

logger = logging.getLogger(__name__)

MAX_LEADERBOARD_ENTRIES = 15

class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # No local config needed

    async def cog_load(self):
        logger.info("LeaderboardCog loaded.")

    # Use the same guild/channel check as WordleGameCog for consistency
    # Or decide if leaderboard should be allowed anywhere? Let's restrict it.
    def check_guild_and_channel():
        async def predicate(interaction: discord.Interaction) -> bool:
            if not interaction.guild:
                await interaction.response.send_message("This command only works in a server.", ephemeral=True)
                return False
            guild_id = interaction.guild_id
            allowed_channel_id = await persistence.get_guild_channel_id(guild_id)
            if allowed_channel_id is None: return True # Allow if no channel set for this guild
            if interaction.channel_id == allowed_channel_id: return True
            # Deny otherwise, send error message
            try:
                channel = interaction.guild.get_channel(allowed_channel_id) or await interaction.guild.fetch_channel(allowed_channel_id)
                channel_name = channel.mention if channel else f"ID: {allowed_channel_id}"
                await interaction.response.send_message(
                    f"❌ Please use `/leaderboard` in the designated Wordle channel for this server: {channel_name}",
                    ephemeral=True
                )
            except Exception: # Catch broad exceptions for error reporting
                 await interaction.response.send_message(
                    f"❌ Please use `/leaderboard` in the designated Wordle channel for this server.",
                    ephemeral=True
                )
            return False
        return app_commands.check(predicate)


    @app_commands.command(name="leaderboard", description="Shows Wordle rankings by total points.")
    @app_commands.describe(scope="Choose whether to view the leaderboard for this server or globally.")
    @check_guild_and_channel() # Apply the check
    async def show_leaderboard(self, interaction: Interaction, scope: Literal['Guild', 'Global'] = 'Guild'):
        """Displays the guild or global leaderboard."""
        # Guild check done by decorator
        guild_id = interaction.guild_id # We know this exists due to decorator

        leaderboard_data = await persistence.load_leaderboard()

        scores = []
        title = ""
        data_source = {}

        # --- Select Data Source and Title ---
        if scope == 'Guild':
            title = f"🏆 Wordle Leaderboard (Server: {interaction.guild.name}) 🏆"
            guild_id_str = str(guild_id)
            # Safely get the guild's data, default to empty dict if not found
            data_source = leaderboard_data.get("guilds", {}).get(guild_id_str, {})
            if not data_source:
                 await interaction.response.send_message(f"No leaderboard data found for this server (`{interaction.guild.name}`).", ephemeral=True)
                 return

        elif scope == 'Global':
            title = "🏆 Wordle Leaderboard (Global) 🏆"
            data_source = leaderboard_data.get("global", {})
            if not data_source:
                 await interaction.response.send_message("The global leaderboard is currently empty.", ephemeral=True)
                 return

        # --- Process Scores ---
        for user_id_str, data in data_source.items():
            if not isinstance(data, dict): continue # Skip malformed entries

            total_points = data.get("total_points", 0)
            games_played = data.get("games_played", 0)

            if games_played <= 0: continue # Skip users who haven't played

            # Fetch username - prioritize guild member if possible for Guild scope
            username = f"Unknown User ({user_id_str})"
            user_id_int = None
            try:
                 user_id_int = int(user_id_str)
            except ValueError:
                 logger.warning(f"Invalid user ID format in {scope} leaderboard: {user_id_str}")
                 continue

            try:
                member = None
                if scope == 'Guild' and interaction.guild:
                    member = interaction.guild.get_member(user_id_int) # Check cache first
                if member:
                    username = member.display_name # Use server nickname/display name
                else:
                    # Fetch user globally if not found in guild cache or for Global scope
                    user = await self.bot.fetch_user(user_id_int)
                    username = user.display_name # Use global display name
            except discord.NotFound:
                logger.warning(f"User ID {user_id_str} not found for {scope} leaderboard.")
            except discord.HTTPException:
                logger.warning(f"HTTP error fetching user {user_id_str} for {scope} leaderboard.")

            scores.append({
                "name": username,
                "total_points": total_points,
                "games_played": games_played,
            })

        # --- Sort and Format ---
        scores.sort(key=lambda x: (x["total_points"], -x["games_played"]), reverse=True)

        embed = discord.Embed(title=title, color=discord.Color.gold())
        description = ""
        if not scores:
            description = "No scores recorded yet for this scope."
        else:
            for i, score in enumerate(scores[:MAX_LEADERBOARD_ENTRIES]):
                rank = i + 1
                description += (
                    f"`{rank}.` **{score['name']}**: {score['total_points']} Points "
                    f"({score['games_played']} games)\n"
                )

        embed.description = description
        footer_text=f"Top {min(len(scores), MAX_LEADERBOARD_ENTRIES)} players shown."
        if len(scores) > MAX_LEADERBOARD_ENTRIES: footer_text += f" ({len(scores)} total)"
        embed.set_footer(text=footer_text)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    # No config needed here
    await bot.add_cog(LeaderboardCog(bot))