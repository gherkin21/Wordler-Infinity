import json
import logging
import os
import asyncio
from collections import defaultdict

logger = logging.getLogger(__name__)

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LEADERBOARD_FILE = os.path.join(DATA_DIR, "leaderboard.json")

config_lock = asyncio.Lock()
leaderboard_lock = asyncio.Lock()

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

# --- Config Persistence (Guild-Aware) ---

async def load_config():
    """Loads the bot configuration (guild-specific settings)."""
    ensure_data_dir()
    async with config_lock:
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            # Basic validation: Ensure top-level key exists
            if "guild_configs" not in config_data:
                 logger.warning(f"'{CONFIG_FILE}' missing 'guild_configs' key. Initializing.")
                 config_data = {"guild_configs": {}}
            # Further validation: ensure guild_configs is a dict
            elif not isinstance(config_data.get("guild_configs"), dict):
                 logger.error(f"'guild_configs' in '{CONFIG_FILE}' is not a dictionary. Resetting.")
                 config_data = {"guild_configs": {}}

            logger.info(f"Configuration loaded successfully from {CONFIG_FILE}.")
            return config_data
        except FileNotFoundError:
            logger.warning(f"{CONFIG_FILE} not found. Returning default empty config.")
            # Default structure: dictionary containing guild-specific configs
            return {"guild_configs": {}}
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {CONFIG_FILE}. Returning default empty config.")
            return {"guild_configs": {}}
        except Exception as e:
            logger.error(f"Unexpected error loading config: {e}")
            return {"guild_configs": {}}

async def save_config(config_data):
    """Saves the bot configuration."""
    ensure_data_dir()
    async with config_lock:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4)
            logger.info(f"Configuration saved successfully to {CONFIG_FILE}.")
            return True
        except IOError as e:
            logger.error(f"Could not write config to {CONFIG_FILE}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving config: {e}")
            return False

async def get_guild_channel_id(guild_id: int) -> int | None:
    """Gets the configured Wordle channel ID for a specific guild."""
    config = await load_config()
    guild_id_str = str(guild_id)
    return config.get("guild_configs", {}).get(guild_id_str, None)

async def set_guild_channel_id(guild_id: int, channel_id: int | None):
    """Sets the Wordle channel ID for a specific guild."""
    config = await load_config()
    guild_id_str = str(guild_id)

    # Ensure the main structure exists
    if "guild_configs" not in config:
        config["guild_configs"] = {}

    if channel_id is None:
        # Remove the setting for the guild if channel_id is None
        config["guild_configs"].pop(guild_id_str, None)
        logger.info(f"Removed Wordle channel setting for guild {guild_id}.")
    else:
        config["guild_configs"][guild_id_str] = channel_id
        logger.info(f"Set Wordle channel for guild {guild_id} to {channel_id}.")

    await save_config(config)


# --- Leaderboard Persistence (Guild + Global) ---

async def load_leaderboard():
    """Loads guild-specific and global leaderboard data."""
    ensure_data_dir()
    default_structure = {"guilds": {}, "global": {}}
    async with leaderboard_lock:
        try:
            with open(LEADERBOARD_FILE, 'r', encoding='utf-8') as f:
                leaderboard_data = json.load(f)

            # --- Validation and Migration ---
            migrated = False
            if not isinstance(leaderboard_data, dict) or \
               "guilds" not in leaderboard_data or \
               "global" not in leaderboard_data or \
               not isinstance(leaderboard_data.get("guilds"), dict) or \
               not isinstance(leaderboard_data.get("global"), dict):
                logger.warning(f"Leaderboard file '{LEADERBOARD_FILE}' has incorrect structure. Resetting.")
                leaderboard_data = default_structure
                migrated = True # Mark for potential immediate save if needed

            # Optional: Further validation within guild/global structures if needed

            logger.info(f"Leaderboard loaded successfully from {LEADERBOARD_FILE}.")
            # if migrated: await save_leaderboard(leaderboard_data) # Save immediately if structure was fixed
            return leaderboard_data

        except FileNotFoundError:
            logger.warning(f"{LEADERBOARD_FILE} not found. Returning empty structure.")
            return default_structure
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {LEADERBOARD_FILE}. Returning empty structure.")
            return default_structure
        except Exception as e:
            logger.error(f"Unexpected error loading leaderboard: {e}")
            return default_structure


async def save_leaderboard(leaderboard_data):
    """Saves the combined leaderboard data."""
    ensure_data_dir()
    async with leaderboard_lock:
        try:
            with open(LEADERBOARD_FILE, 'w', encoding='utf-8') as f:
                json.dump(leaderboard_data, f, indent=4)
            logger.info(f"Leaderboard saved successfully to {LEADERBOARD_FILE}.")
            return True
        except IOError as e:
            logger.error(f"Could not write leaderboard to {LEADERBOARD_FILE}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving leaderboard: {e}")
            return False

async def update_leaderboard(guild_id: int, user_id: int, points_earned: int):
    """Updates both guild and global leaderboards for a user."""
    leaderboard_data = await load_leaderboard()
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)

    # --- Update Guild Leaderboard ---
    if guild_id_str not in leaderboard_data["guilds"]:
        leaderboard_data["guilds"][guild_id_str] = {}
    if user_id_str not in leaderboard_data["guilds"][guild_id_str]:
        leaderboard_data["guilds"][guild_id_str][user_id_str] = {"total_points": 0, "games_played": 0}
    # Ensure keys exist (handle potential previous corruption)
    guild_user_data = leaderboard_data["guilds"][guild_id_str][user_id_str]
    if "total_points" not in guild_user_data: guild_user_data["total_points"] = 0
    if "games_played" not in guild_user_data: guild_user_data["games_played"] = 0

    guild_user_data["games_played"] += 1
    guild_user_data["total_points"] += points_earned

    # --- Update Global Leaderboard ---
    if user_id_str not in leaderboard_data["global"]:
        leaderboard_data["global"][user_id_str] = {"total_points": 0, "games_played": 0}
    # Ensure keys exist
    global_user_data = leaderboard_data["global"][user_id_str]
    if "total_points" not in global_user_data: global_user_data["total_points"] = 0
    if "games_played" not in global_user_data: global_user_data["games_played"] = 0

    global_user_data["games_played"] += 1
    global_user_data["total_points"] += points_earned

    await save_leaderboard(leaderboard_data)
    logger.info(f"Updated leaderboards for user {user_id} in guild {guild_id}. Points: {points_earned}. Guild Total: {guild_user_data['total_points']}. Global Total: {global_user_data['total_points']}")