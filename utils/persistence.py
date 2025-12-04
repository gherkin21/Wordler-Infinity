import json
import logging
import os
import asyncio

logger = logging.getLogger(__name__)

DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LEADERBOARD_FILE = os.path.join(DATA_DIR, "leaderboard.json")

config_lock = asyncio.Lock()
leaderboard_lock = asyncio.Lock()

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


async def load_config():
    ensure_data_dir()
    default_structure = {
        "guild_configs": {},
        "chatter_enabled": {},
        "chatter_opt_out": []
    }
    async with config_lock:
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            if "guild_configs" not in config_data: config_data["guild_configs"] = {}
            if "chatter_enabled" not in config_data: config_data["chatter_enabled"] = {}
            if "chatter_opt_out" not in config_data: config_data["chatter_opt_out"] = []
            return config_data
        except FileNotFoundError:
            return default_structure
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {CONFIG_FILE}. Returning default structure.")
            return default_structure

async def save_config(config_data):
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
    config = await load_config()
    guild_id_str = str(guild_id)
    return config.get("guild_configs", {}).get(guild_id_str, None)

async def set_guild_channel_id(guild_id: int, channel_id: int | None):
    config = await load_config()
    guild_id_str = str(guild_id)

    if "guild_configs" not in config:
        config["guild_configs"] = {}

    if channel_id is None:
        config["guild_configs"].pop(guild_id_str, None)
        logger.info(f"Removed Wordle channel setting for guild {guild_id}.")
    else:
        config["guild_configs"][guild_id_str] = channel_id
        logger.info(f"Set Wordle channel for guild {guild_id} to {channel_id}.")

    await save_config(config)

async def load_leaderboard():
    """Loads guild-specific and global leaderboard data."""
    ensure_data_dir()
    default_structure = {"guilds": {}, "global": {}}
    async with leaderboard_lock:
        try:
            with open(LEADERBOARD_FILE, 'r', encoding='utf-8') as f:
                leaderboard_data = json.load(f)

            migrated = False
            if not isinstance(leaderboard_data, dict) or \
               "guilds" not in leaderboard_data or \
               "global" not in leaderboard_data or \
               not isinstance(leaderboard_data.get("guilds"), dict) or \
               not isinstance(leaderboard_data.get("global"), dict):
                logger.warning(f"Leaderboard file '{LEADERBOARD_FILE}' has incorrect structure. Resetting.")
                leaderboard_data = default_structure
                migrated = True


            logger.info(f"Leaderboard loaded successfully from {LEADERBOARD_FILE}.")

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
    leaderboard_data = await load_leaderboard()
    guild_id_str = str(guild_id)
    user_id_str = str(user_id)

    if guild_id_str not in leaderboard_data["guilds"]:
        leaderboard_data["guilds"][guild_id_str] = {}
    if user_id_str not in leaderboard_data["guilds"][guild_id_str]:
        leaderboard_data["guilds"][guild_id_str][user_id_str] = {"total_points": 0, "games_played": 0}
    guild_user_data = leaderboard_data["guilds"][guild_id_str][user_id_str]
    if "total_points" not in guild_user_data: guild_user_data["total_points"] = 0
    if "games_played" not in guild_user_data: guild_user_data["games_played"] = 0

    guild_user_data["games_played"] += 1
    guild_user_data["total_points"] += points_earned

    if user_id_str not in leaderboard_data["global"]:
        leaderboard_data["global"][user_id_str] = {"total_points": 0, "games_played": 0}
    global_user_data = leaderboard_data["global"][user_id_str]
    if "total_points" not in global_user_data: global_user_data["total_points"] = 0
    if "games_played" not in global_user_data: global_user_data["games_played"] = 0

    global_user_data["games_played"] += 1
    global_user_data["total_points"] += points_earned

    await save_leaderboard(leaderboard_data)
    logger.info(f"Updated leaderboards for user {user_id} in guild {guild_id}. Points: {points_earned}. Guild Total: {guild_user_data['total_points']}. Global Total: {global_user_data['total_points']}")

async def get_guild_language(guild_id: int) -> str:
    config = await load_config()
    return config.get("guild_languages", {}).get(str(guild_id), "en")

async def set_guild_language(guild_id: int, lang_code: str):
    config = await load_config()
    if "guild_languages" not in config:
        config["guild_languages"] = {}

    config["guild_languages"][str(guild_id)] = lang_code
    await save_config(config)
    logger.info(f"Set language for guild {guild_id} to {lang_code}.")


async def update_detailed_stats(user_id: int, is_win: bool, num_guesses: int, starting_word: str):
    leaderboard_data = await load_leaderboard()
    user_id_str = str(user_id)

    if user_id_str not in leaderboard_data["global"]:
        leaderboard_data["global"][user_id_str] = {"total_points": 0, "games_played": 0}

    user_data = leaderboard_data["global"][user_id_str]

    if "stats" not in user_data:
        user_data["stats"] = {
            "wins": 0,
            "losses": 0,
            "current_streak": 0,
            "max_streak": 0,
            "distribution": {},
            "starting_words": {}
        }

    stats = user_data["stats"]

    if is_win:
        stats["wins"] += 1
        stats["current_streak"] += 1
        if stats["current_streak"] > stats.get("max_streak", 0):
            stats["max_streak"] = stats["current_streak"]

        str_guesses = str(num_guesses)
        stats["distribution"][str_guesses] = stats["distribution"].get(str_guesses, 0) + 1
    else:
        stats["losses"] += 1
        stats["current_streak"] = 0

    if starting_word:
        w = starting_word.lower()
        stats["starting_words"][w] = stats["starting_words"].get(w, 0) + 1

    await save_leaderboard(leaderboard_data)
    logger.info(f"Updated detailed stats for user {user_id}. Win: {is_win}")