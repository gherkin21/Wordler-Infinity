import discord
from discord.ext import commands
import os
import logging
import asyncio
from dotenv import load_dotenv

from utils import word_fetcher
from utils import localization


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    logger.critical("DISCORD_TOKEN environment variable not set. Exiting.")
    exit()


intents = discord.Intents.default()
intents.guilds = True
intents.members = True


bot = commands.Bot(command_prefix="wit!", intents=intents)


INITIAL_EXTENSIONS = [
    'cogs.wordle_game',
    'cogs.admin',
    'cogs.leaderboard',
    'cogs.utility',
]


@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Discord.py version: {discord.__version__}')
    logger.info('Bot is ready and online.')

    await bot.change_presence(activity=discord.Game(name="/wordle | /wordlehelp"))

    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} application commands globally.")
    except Exception as e:
        logger.exception(f"Failed to sync application commands: {e}")


@bot.event
async def on_connect():
    """Called when the bot successfully connects to Discord."""
    logger.info("Bot connected to Discord.")


@bot.event
async def on_disconnect():
    """Called when the bot loses connection to Discord."""
    logger.warning("Bot disconnected from Discord. Attempting to reconnect...")


@bot.event
async def on_guild_join(guild: discord.Guild):
    """
    Called when the bot joins a new guild.
    Sends a welcome message to the person who added the bot or the server owner.
    """
    logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")

    welcome_embed = discord.Embed(
        title=f"👋 Thanks for adding Wordler Infinity to {guild.name}!",
        description="I'm excited to bring Wordle to your server! Here's how to get started.",
        color=discord.Color.green()
    )
    welcome_embed.add_field(
        name="1. Designate a Channel",
        value="To avoid spam, I need a dedicated channel for games.\n"
              "An admin needs to use the `/setchannel` command in the channel you want to use.\n"
              "Example: `/setchannel channel:#wordle-games`",
        inline=False
    )
    welcome_embed.add_field(
        name="2. Start Playing!",
        value="Once the channel is set, members can start games using:\n"
              "- `/wordle` for a solo game.\n"
              "- `/multiplayer` to challenge friends.\n",
        inline=False
    )
    welcome_embed.add_field(
        name="3. See All Commands",
        value="Use `/wordlehelp` to see a full list of my commands, including `/leaderboard` and more!",
        inline=False
    )
    welcome_embed.set_footer(text="Have fun, and good luck with your guesses!")

    target_user = None

    try:
        if guild.me.guild_permissions.view_audit_log:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if entry.target.id == bot.user.id:
                    target_user = entry.user
                    logger.info(f"Found user who added the bot via audit log: {target_user.name}")
                    break
    except discord.Forbidden:
        logger.warning(f"Missing 'View Audit Log' permissions in {guild.name}.")
    except Exception as e:
        logger.error(f"Error checking audit log in {guild.name}: {e}")

    if not target_user:
        target_user = guild.owner
        logger.info(f"Falling back to guild owner: {target_user.name}")

    if target_user:
        try:
            await target_user.send(embed=welcome_embed)
            logger.info(f"Successfully sent welcome DM to {target_user.name} for guild {guild.name}.")
        except discord.Forbidden:
            logger.warning(f"Could not send welcome DM to {target_user.name}. They may have DMs disabled.")
        except Exception as e:
            logger.error(f"Failed to send welcome DM to {target_user.name}: {e}")



async def main():
    """Main function to load extensions and run the bot."""
    logger.info("Starting bot...")

    logger.info("Loading locales...")
    localization.load_locales()

    logger.info("Loading word lists...")
    if not await word_fetcher.load_word_lists():
         logger.error("Failed to load initial word lists. Check network connectivity and Gist URLs.")
         logger.warning("Proceeding without fully loaded word lists. Wordle game may not function.")
    else:
         logger.info("Word lists loaded successfully.")


    logger.info("Loading extensions (cogs)...")
    for extension in INITIAL_EXTENSIONS:
        try:
            await bot.load_extension(extension)
            logger.info(f"Successfully loaded extension: {extension}")
        except commands.ExtensionNotFound:
            logger.error(f"Extension not found: {extension}")
        except commands.ExtensionAlreadyLoaded:
            logger.warning(f"Extension already loaded: {extension}")
        except commands.NoEntryPointError:
            logger.error(f"Extension {extension} does not have a setup function.")
        except commands.ExtensionFailed as e:
            logger.exception(f"Extension {extension} failed to load: {e.original}")
        except Exception as e:
            logger.exception(f"An unexpected error occurred loading extension {extension}: {e}")

    logger.info("Attempting to log in and run the bot...")
    try:
        await bot.start(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("Login failed: Invalid Discord token provided.")
    except discord.PrivilegedIntentsRequired:
         logger.critical("Privileged Intents (like Members) are not enabled for the bot in the Developer Portal.")
    except Exception as e:
        logger.exception(f"An error occurred while running the bot: {e}")
    finally:
        logger.info("Bot process is shutting down.")
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())