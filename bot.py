import discord
from discord.ext import commands
import os
import logging
import asyncio
from dotenv import load_dotenv

from utils import word_fetcher # Import to trigger loading word lists early

# --- Logging Setup ---
# Basic configuration for logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Suppress overly verbose discord logs if needed
# logging.getLogger('discord.http').setLevel(logging.WARNING)
# logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logger = logging.getLogger(__name__) # Logger for this module

# --- Environment Variables ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    logger.critical("DISCORD_TOKEN environment variable not set. Exiting.")
    exit()

# --- Bot Setup ---
# Define intents required by the bot
intents = discord.Intents.default()
intents.guilds = True # Essential for guild-specific operations
intents.members = True # Helpful for fetching member names easily
intents.message_content = True

bot = commands.Bot(command_prefix="wi!", intents=intents) # Prefix is unused for slash commands

# --- Cogs to Load ---
INITIAL_EXTENSIONS = [
    'cogs.wordle_game',
    'cogs.admin',
    'cogs.leaderboard',
    'cogs.utility',
]

# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Discord.py version: {discord.__version__}')
    logger.info('Bot is ready and online.')

    # Set status (optional)
    await bot.change_presence(activity=discord.Game(name="/wordle | /wordlehelp"))


    # Sync slash commands (important!)
    # Normally, you'd sync specific guilds for testing, then sync globally
    # For simplicity here, we sync globally. This can take up to an hour to update.
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


# --- Main Execution ---
async def main():
    """Main function to load extensions and run the bot."""
    logger.info("Starting bot...")

    # Load word lists before starting the bot fully
    logger.info("Loading word lists...")
    if not await word_fetcher.load_word_lists():
         logger.error("Failed to load initial word lists. Check network connectivity and Gist URLs.")
         # Depending on severity, you might want to exit or let the bot run degraded.
         # Let's proceed but commands needing words will fail.
         logger.warning("Proceeding without fully loaded word lists. Wordle game may not function.")
    else:
         logger.info("Word lists loaded successfully.")


    # Load cogs
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

    # Start the bot
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
        await bot.close() # Ensure cleanup

if __name__ == "__main__":
    asyncio.run(main())