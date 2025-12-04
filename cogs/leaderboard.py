import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.app_commands import Choice
import logging
from typing import Literal

from utils import persistence, stats_generator, localization

logger = logging.getLogger(__name__)

MAX_LEADERBOARD_ENTRIES = 10


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        logger.info("LeaderboardCog loaded.")

    def check_guild_and_channel():
        async def predicate(interaction: Interaction) -> bool:
            if not interaction.guild:
                await interaction.response.send_message("This command only works in a server.", ephemeral=True)
                return False
            guild_id = interaction.guild_id
            allowed_channel_id = await persistence.get_guild_channel_id(guild_id)
            if allowed_channel_id is None: return True
            if interaction.channel_id == allowed_channel_id: return True

            try:
                channel = interaction.guild.get_channel(allowed_channel_id) or await interaction.guild.fetch_channel(
                    allowed_channel_id)
                channel_name = channel.mention if channel else f"ID: {allowed_channel_id}"

                lang = await persistence.get_guild_language(guild_id)
                msg = localization.get_text(lang, "wrong_channel", channel=channel_name)

                await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                await interaction.response.send_message(
                    f"❌ Please use `/leaderboard` in the designated Wordle channel for this server.",
                    ephemeral=True
                )
            return False

        return app_commands.check(predicate)

    @app_commands.command(name="leaderboard", description="Shows Wordle rankings by total points.")
    @app_commands.describe(scope="Choose whether to view the leaderboard for this server or globally.")
    @check_guild_and_channel()
    async def show_leaderboard(self, interaction: Interaction, scope: Literal['Guild', 'Global'] = 'Guild'):
        """Displays the guild or global leaderboard."""
        guild_id = interaction.guild_id
        lang = await persistence.get_guild_language(guild_id)

        leaderboard_data = await persistence.load_leaderboard()

        scores = []
        title = ""
        data_source = {}

        if scope == 'Guild':
            title = localization.get_text(lang, "lb_title_server", guild=interaction.guild.name)
            guild_id_str = str(guild_id)
            data_source = leaderboard_data.get("guilds", {}).get(guild_id_str, {})
            if not data_source:
                msg = localization.get_text(lang, "lb_empty_server", guild=interaction.guild.name)
                await interaction.response.send_message(msg, ephemeral=True)
                return

        elif scope == 'Global':
            title = localization.get_text(lang, "lb_title_global")
            data_source = leaderboard_data.get("global", {})
            if not data_source:
                msg = localization.get_text(lang, "lb_empty_global")
                await interaction.response.send_message(msg, ephemeral=True)
                return

        for user_id_str, data in data_source.items():
            if not isinstance(data, dict): continue

            total_points = data.get("total_points", 0)
            games_played = data.get("games_played", 0)

            if games_played <= 0: continue

            if not user_id_str.isdigit():
                logger.warning(f"Invalid non-numeric user ID found in {scope} leaderboard: {user_id_str}")
                continue

            user_mention = f"<@{user_id_str}>"


            scores.append({
                "mention": user_mention,
                "total_points": total_points,
                "games_played": games_played,
                "user_id": int(user_id_str)
            })

        scores.sort(key=lambda x: (x["total_points"], -x["games_played"]), reverse=True)

        embed = discord.Embed(title=title, color=discord.Color.gold())
        description = ""
        if not scores:
            description = localization.get_text(lang, "lb_no_scores")
        else:
            for i, score in enumerate(scores[:MAX_LEADERBOARD_ENTRIES]):
                rank = i + 1
                description += (
                    f"`{rank}.` {score['mention']}: {score['total_points']} "
                    f"({score['games_played']})\n"
                )


        embed.description = description

        count_shown = min(len(scores), MAX_LEADERBOARD_ENTRIES)
        footer_text = localization.get_text(lang, "lb_footer", count=count_shown)

        if len(scores) > MAX_LEADERBOARD_ENTRIES:
            footer_text += localization.get_text(lang, "lb_footer_total", total=len(scores))

        embed.set_footer(text=footer_text)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="points", description="Shows your current Wordle point totals.")
    @app_commands.guild_only()
    async def show_points(self, interaction: Interaction):
        user_id = interaction.user.id
        user_id_str = str(user_id)
        guild_id = interaction.guild_id
        guild_id_str = str(guild_id)
        lang = await persistence.get_guild_language(guild_id)

        leaderboard_data = await persistence.load_leaderboard()

        guild_data = leaderboard_data.get("guilds", {}).get(guild_id_str, {}).get(user_id_str, {})  # Use {} default
        guild_points = guild_data.get("total_points", 0)
        guild_games = guild_data.get("games_played", 0)

        global_data = leaderboard_data.get("global", {}).get(user_id_str, {})  # Use {} default
        global_points = global_data.get("total_points", 0)
        global_games = global_data.get("games_played", 0)

        title = localization.get_text(lang, "pts_title", user=interaction.user.display_name)
        embed = discord.Embed(
            title=title,
            color=discord.Color.blue()
        )

        field_server = localization.get_text(lang, "pts_server", guild=interaction.guild.name)
        value_server = localization.get_text(lang, "pts_details", points=guild_points, games=guild_games)

        embed.add_field(
            name=field_server,
            value=value_server,
            inline=False
        )

        field_global = localization.get_text(lang, "pts_global")
        value_global = localization.get_text(lang, "pts_details", points=global_points, games=global_games)

        embed.add_field(
            name=field_global,
            value=value_global,
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="Displays detailed Wordle statistics for a user.")
    @app_commands.describe(user="The user to view stats for (defaults to yourself).")
    async def show_stats(self, interaction: Interaction, user: discord.User = None):
        target_user = user or interaction.user
        user_id_str = str(target_user.id)

        lang = "en"
        if interaction.guild_id:
            lang = await persistence.get_guild_language(interaction.guild_id)

        await interaction.response.defer()

        data = await persistence.load_leaderboard()
        user_entry = data.get("global", {}).get(user_id_str, {})
        stats_raw = user_entry.get("stats", {})

        wins = stats_raw.get("wins", 0)
        losses = stats_raw.get("losses", 0)
        played = wins + losses
        win_pct = (wins / played * 100) if played > 0 else 0

        starting_words = stats_raw.get("starting_words", {})
        fav_starter = max(starting_words, key=starting_words.get) if starting_words else "N/A"

        stats_data = {
            "played": played,
            "win_pct": win_pct,
            "current_streak": stats_raw.get("current_streak", 0),
            "max_streak": stats_raw.get("max_streak", 0),
            "distribution": stats_raw.get("distribution", {}),
            "fav_starter": fav_starter
        }

        avatar_bytes = None
        try:
            if target_user.display_avatar:
                avatar_bytes = await target_user.display_avatar.read()
        except Exception as e:
            logger.warning(f"Failed to fetch avatar for {target_user.id}: {e}")

        labels = {
            "stats_header": localization.get_text(lang, "stats_header", user=target_user.name),
            "stats_played": localization.get_text(lang, "stats_played"),
            "stats_win_pct": localization.get_text(lang, "stats_win_pct"),
            "stats_streak_current": localization.get_text(lang, "stats_streak_current"),
            "stats_streak_max": localization.get_text(lang, "stats_streak_max"),
            "stats_distribution": localization.get_text(lang, "stats_distribution"),
            "stats_favorite_starter": localization.get_text(lang, "stats_favorite_starter", word="{word}")
        }

        img_buffer = await self.bot.loop.run_in_executor(
            None,
            stats_generator.generate_stats_image,
            target_user.name,
            stats_data,
            avatar_bytes,
            labels
        )

        if img_buffer:
            file = discord.File(fp=img_buffer, filename="stats.png")
            embed_title = localization.get_text(lang, "stats_embed_title", user=target_user.display_name)
            embed = discord.Embed(title=embed_title, color=discord.Color.gold())
            embed.set_image(url="attachment://stats.png")
            await interaction.followup.send(embed=embed, file=file)
        else:
            msg = localization.get_text(lang, "stats_error")
            await interaction.followup.send(msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))