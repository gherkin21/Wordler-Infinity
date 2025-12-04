import discord
from discord.ext import commands
from discord import app_commands, Interaction, TextChannel
from discord.app_commands import Choice
import logging
import math

from utils import persistence
from utils import localization

logger = logging.getLogger(__name__)


class SimplePaginator(discord.ui.View):
    def __init__(self, author_id: int, embeds: list[discord.Embed]):
        super().__init__(timeout=120.0)
        self.author_id = author_id
        self.embeds = embeds
        self.current_page = 0

        self._update_footer()

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            return False
        return True

    def _update_footer(self):
        self.embeds[self.current_page].set_footer(text=f"Page {self.current_page + 1} of {len(self.embeds)}")

    @discord.ui.button(label="<< First", style=discord.ButtonStyle.secondary, row=1)
    async def first_page(self, interaction: Interaction, button: discord.ui.Button):
        self.current_page = 0
        self._update_footer()
        await interaction.response.edit_message(embed=self.embeds[self.current_page])

    @discord.ui.button(label="< Previous", style=discord.ButtonStyle.primary, row=1)
    async def prev_page(self, interaction: Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self._update_footer()
        await interaction.response.edit_message(embed=self.embeds[self.current_page])

    @discord.ui.button(label="Next >", style=discord.ButtonStyle.primary, row=1)
    async def next_page(self, interaction: Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self._update_footer()
        await interaction.response.edit_message(embed=self.embeds[self.current_page])

    @discord.ui.button(label="Last >>", style=discord.ButtonStyle.secondary, row=1)
    async def last_page(self, interaction: Interaction, button: discord.ui.Button):
        self.current_page = len(self.embeds) - 1
        self._update_footer()
        await interaction.response.edit_message(embed=self.embeds[self.current_page])


class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=60.0)
        self.value = None
        self.author_id = author_id

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You cannot use this button.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Send", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        for item in self.children:
            item.disabled = True

        if interaction.message:
            await interaction.message.edit(content="✅ Confirmed. Sending messages...", view=self)
        else:
            await interaction.response.edit_message(content="✅ Confirmed. Sending messages...", view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        for item in self.children:
            item.disabled = True
        if interaction.message:
            await interaction.message.edit(content="❌ Operation cancelled.", view=self)
        else:
            await interaction.response.edit_message(content="❌ Operation cancelled.", view=self)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


    async def cog_load(self):

        logger.info("AdminCog loaded.")

    @app_commands.command(name="setchannel", description="Sets the channel for Wordle commands in this server.")
    @app_commands.describe(channel="The text channel to restrict Wordle commands to. Leave empty to unset.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only() # Ensure this command is used in a guild
    async def set_channel(self, interaction: Interaction, channel: TextChannel = None):
        """Sets or unsets the allowed channel for game commands in the current guild."""
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        channel_id = channel.id if channel else None

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


        except Exception as e:
            logger.error(f"Error setting channel for guild {guild_id}: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while saving the configuration. Please check bot logs.",
                ephemeral=True
            )

    @app_commands.command(name="setlanguage", description="Sets the game language for this server.")
    @app_commands.describe(language="The language to use.")
    @app_commands.choices(language=[
        Choice(name="English", value="en")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_language(self, interaction: Interaction, language: Choice[str]):
        await persistence.set_guild_language(interaction.guild_id, language.value)


        msg = localization.get_text(language.value, "set_lang", lang=language.name)
        await interaction.response.send_message(msg)

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

    @commands.command(name="massmessage", aliases=["mm"])
    @commands.is_owner()
    async def mass_message_prefix(self, ctx: commands.Context, *, message: str):
        """[Owner Only] Sends a message to all configured Wordle channels."""


        config = await persistence.load_config()
        guild_configs = config.get("guild_configs", {})
        target_channels = {int(guild_id): channel_id for guild_id, channel_id in guild_configs.items() if
                           channel_id is not None}

        if not target_channels:
            await ctx.author.send("No servers have a Wordle channel configured. Nothing to send.")
            return


        num_servers = len(target_channels)
        confirmation_embed = discord.Embed(
            title="Confirm Mass Message",
            description=f"You are about to send the following message to **{num_servers}** server(s).",
            color=discord.Color.orange()
        )
        confirmation_embed.add_field(name="Message Preview", value=message, inline=False)

        view = ConfirmView(author_id=ctx.author.id)

        try:
            confirm_msg = await ctx.author.send(embed=confirmation_embed, view=view)
            await ctx.message.add_reaction('📬')
        except discord.Forbidden:
            await ctx.send("❌ I cannot DM you. Please enable DMs from server members to use this command.")
            return

        await view.wait()

        if view.value is None:
            await confirm_msg.edit(content="Timed out. Mass message cancelled.", view=None, embed=None)
            return
        if view.value is False:
            await confirm_msg.edit(content="❌ Operation cancelled.", view=None, embed=None)
            return

        # 3. Proceed with sending
        await confirm_msg.edit(content=f"✅ Sending messages to {num_servers} servers...", view=None, embed=None)
        logger.info(f"Owner {ctx.author} initiated mass message to {num_servers} servers.")
        success_count = 0
        fail_count = 0

        for guild_id, channel_id in target_channels.items():
            try:
                channel = await self.bot.fetch_channel(channel_id)
                await channel.send(message)
                success_count += 1
            except discord.NotFound:
                logger.warning(f"Failed to send mass message: Channel {channel_id} in Guild {guild_id} not found.")
                fail_count += 1
            except discord.Forbidden:
                logger.warning(
                    f"Failed to send mass message: No permissions for Channel {channel_id} in Guild {guild_id}.")
                fail_count += 1
            except Exception as e:
                logger.error(f"An unexpected error occurred sending to Channel {channel_id} in Guild {guild_id}: {e}")
                fail_count += 1


        result_message = f"**Mass Message Report**\n\n✅ Successfully sent to **{success_count}** server(s).\n❌ Failed to send to **{fail_count}** server(s)."
        await ctx.author.send(result_message)
        logger.info(f"Mass message complete. Success: {success_count}, Failed: {fail_count}.")

    @commands.command(name="servers", aliases=["serverlist"])
    @commands.is_owner()
    async def servers_list(self, ctx: commands.Context):
        """[Owner Only] DMs a list of all servers the bot is in."""
        await ctx.message.add_reaction('📬')

        guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())


        embeds = []
        entries_per_page = 5
        num_pages = math.ceil(len(guilds) / entries_per_page)

        for page_num in range(num_pages):
            embed = discord.Embed(
                title=f"Server List ({len(guilds)} total)",
                color=discord.Color.blurple()
            )
            start_index = page_num * entries_per_page
            end_index = start_index + entries_per_page

            description = ""
            for guild in guilds[start_index:end_index]:
                description += f"**{guild.name}**\n"
                description += f"- ID: `{guild.id}`\n"
                description += f"- Members: `{guild.member_count}`\n\n"

            embed.description = description
            embeds.append(embed)

        if not embeds:
            await ctx.author.send("The bot is not in any servers.")
            return


        view = SimplePaginator(author_id=ctx.author.id, embeds=embeds)
        try:
            await ctx.author.send(embed=view.embeds[0], view=view)
        except discord.Forbidden:
            await ctx.send("❌ I cannot DM you. Please enable DMs.")

    @mass_message_prefix.error
    @servers_list.error
    async def owner_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.NotOwner):
            logger.warning(f"Non-owner {ctx.author} tried to use owner command: {ctx.message.content}")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"You are missing a required argument. Usage: `{ctx.prefix}{ctx.command.name} <your message>`")
        else:
            logger.error(f"An unexpected error occurred in an admin command: {error}")
            await ctx.send("An unexpected error occurred.")



async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))