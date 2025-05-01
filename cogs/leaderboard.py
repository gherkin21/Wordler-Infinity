import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.app_commands import Choice # For scope parameter
import logging
from typing import Literal # For scope type hint

# Use updated persistence
from utils import persistence

logger = logging.getLogger(__name__)

MAX_LEADERBOARD_ENTRIES = 10

class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # No local config needed

    async def cog_load(self):
        logger.info("LeaderboardCog loaded.")

    # Use the same guild/channel check as WordleGameCog for consistency
    def check_guild_and_channel():
        async def predicate(interaction: Interaction) -> bool:
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
        guild_id = interaction.guild_id # We know this exists due to decorator

        leaderboard_data = await persistence.load_leaderboard()

        scores = []
        title = ""
        data_source = {}

        # --- Select Data Source and Title ---
        if scope == 'Guild':
            title = f"🏆 Wordle Leaderboard (Server: {interaction.guild.name}) 🏆"
            guild_id_str = str(guild_id)
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

            # --- MODIFICATION: Use mention string directly ---
            # Validate that user_id_str is numeric before creating mention
            if not user_id_str.isdigit():
                logger.warning(f"Invalid non-numeric user ID found in {scope} leaderboard: {user_id_str}")
                continue # Skip this entry

            user_mention = f"<@{user_id_str}>"
            # No need to fetch user/member object just for the name anymore
            # Discord clients will automatically render the mention as the current name
            # --- END MODIFICATION ---

            scores.append({
                "mention": user_mention, # Store the mention string
                "total_points": total_points,
                "games_played": games_played,
                # Store user_id as int for sorting if needed, though mention sort might be okay
                "user_id": int(user_id_str)
            })

        # --- Sort and Format ---
        # Sort primarily by points, then maybe games played as tie-breaker
        scores.sort(key=lambda x: (x["total_points"], -x["games_played"]), reverse=True)

        embed = discord.Embed(title=title, color=discord.Color.gold())
        description = ""
        if not scores:
            description = "No scores recorded yet for this scope."
        else:
            for i, score in enumerate(scores[:MAX_LEADERBOARD_ENTRIES]):
                rank = i + 1
                # --- MODIFICATION: Use the mention string in the output ---
                description += (
                    f"`{rank}.` {score['mention']}: {score['total_points']} Points "
                    f"({score['games_played']} games)\n"
                )
                # --- END MODIFICATION ---

        embed.description = description
        footer_text=f"Top {min(len(scores), MAX_LEADERBOARD_ENTRIES)} players shown."
        if len(scores) > MAX_LEADERBOARD_ENTRIES: footer_text += f" ({len(scores)} total)"
        embed.set_footer(text=footer_text)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="points", description="Shows your current Wordle point totals.")
    @app_commands.guild_only()  # Still needs guild context for guild points
    # No channel restriction needed for checking personal points
    async def show_points(self, interaction: Interaction):
        """Displays the user's points for the current guild and globally."""
        user_id = interaction.user.id
        user_id_str = str(user_id)
        guild_id = interaction.guild_id
        guild_id_str = str(guild_id)

        leaderboard_data = await persistence.load_leaderboard()

        guild_data = leaderboard_data.get("guilds", {}).get(guild_id_str, {}).get(user_id_str, {})  # Use {} default
        guild_points = guild_data.get("total_points", 0)
        guild_games = guild_data.get("games_played", 0)

        global_data = leaderboard_data.get("global", {}).get(user_id_str, {})  # Use {} default
        global_points = global_data.get("total_points", 0)
        global_games = global_data.get("games_played", 0)

        # <<< CHANGE: Use user mention in the title >>>
        embed = discord.Embed(
            title=f"📊 Wordle Points for {interaction.user.display_name}",  # Changed from display_name
            color=discord.Color.blue()
        )
        # <<< END CHANGE >>>

        embed.add_field(
            name=f"Server Points ({interaction.guild.name})",
            value=f"**{guild_points}** points ({guild_games} games played)",
            inline=False
        )
        embed.add_field(
            name="Global Points (All Servers)",
            value=f"**{global_points}** points ({global_games} games played)",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))