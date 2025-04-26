import discord
from discord.ext import commands
from discord import app_commands, Interaction, TextChannel
import logging

from utils import persistence # Use the updated persistence

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # No need to store config locally in cog anymore, persistence handles it

    async def cog_load(self):
        # Config is loaded on demand by persistence functions now
        logger.info("AdminCog loaded.")

    @app_commands.command(name="setchannel", description="Sets the channel for Wordle commands in this server.")
    @app_commands.describe(channel="The text channel to restrict Wordle commands to. Leave empty to unset.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only() # Ensure this command is used in a guild
    async def set_channel(self, interaction: Interaction, channel: TextChannel = None):
        """Sets or unsets the allowed channel for game commands in the current guild."""
        if not interaction.guild_id: # Should be caught by @app_commands.guild_only, but belts and suspenders
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        channel_id = channel.id if channel else None # Get ID or None if unsetting

        try:
            await persistence.set_guild_channel_id(guild_id, channel_id)

            if channel:
                await interaction.response.send_message(
                    f"✅ Wordle commands are now restricted to {channel.mention} in this server.",
                    ephemeral=True
                )
                logger.info(f"Admin {interaction.user} set allowed channel for guild {guild_id} to {channel_id}.")
            else:
                 await interaction.response.send_message(
                    f"✅ Wordle channel restriction has been removed for this server. Commands allowed anywhere.",
                    ephemeral=True
                )
                 logger.info(f"Admin {interaction.user} removed allowed channel setting for guild {guild_id}.")

            # Inform WordleGameCog if loaded? Not strictly necessary as it checks on each command.
            # It might be cleaner *not* to cross-update cogs here.

        except Exception as e:
            logger.error(f"Error setting channel for guild {guild_id}: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while saving the configuration. Please check bot logs.",
                ephemeral=True
            )

    @set_channel.error
    async def set_channel_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        """Handles errors for the set_channel command."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need `Manage Channels` permission.", ephemeral=True)
        elif isinstance(error, app_commands.NoPrivateMessage):
             await interaction.response.send_message("❌ This command only works in servers.", ephemeral=True)
        else:
            logger.error(f"Error in set_channel command: {error}")
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

async def setup(bot: commands.Bot):
    # No config loading needed here anymore
    await bot.add_cog(AdminCog(bot))