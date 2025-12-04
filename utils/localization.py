import json
import os
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_UTILS_DIR)
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
DEFAULT_LANG = "en"

_LOCALE_CACHE: Dict[str, Dict[str, Any]] = {}


def load_locales():
    global _LOCALE_CACHE

    if not os.path.exists(DATA_DIR):
        logger.error(f"CRITICAL: Data directory not found at {DATA_DIR}")
        return

    try:
        contents = os.listdir(DATA_DIR)
    except Exception as e:
        logger.error(f"Error reading data folder: {e}")
        return

    loaded_count = 0

    for lang_code in contents:
        lang_folder = os.path.join(DATA_DIR, lang_code)

        if os.path.isdir(lang_folder):
            json_filename = f"{lang_code}.json"
            json_path = os.path.join(lang_folder, json_filename)

            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                        if "strings" not in data or "keyboard" not in data:
                            logger.warning(f"Skipping {json_filename}: Missing 'strings' or 'keyboard' keys.")
                            continue

                        _LOCALE_CACHE[lang_code] = data
                        loaded_count += 1
                        logger.info(f"Loaded locale: {lang_code}")
                except Exception as e:
                    logger.error(f"Failed to load locale file {json_path}: {e}")
            else:
                logger.debug(f"DEBUG: Found folder '{lang_code}' but file '{json_filename}' was missing.")

    if DEFAULT_LANG not in _LOCALE_CACHE:
        logger.warning(f"Default language '{DEFAULT_LANG}' not found in {DATA_DIR}!")
        _LOCALE_CACHE[DEFAULT_LANG] = {
            "strings": {},
            "keyboard": ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        }

    logger.info(f"Locales loading complete. Languages available: {list(_LOCALE_CACHE.keys())}")


def get_text(lang_code: str, key: str, **kwargs) -> str:
    lang_data = _LOCALE_CACHE.get(lang_code)

    if not lang_data:
        lang_data = _LOCALE_CACHE.get(DEFAULT_LANG)

    if lang_data:
        strings = lang_data.get("strings", {})
    else:
        return key

    text = strings.get(key)

    if text is None:
        default_data = _LOCALE_CACHE.get(DEFAULT_LANG, {})
        text = default_data.get("strings", {}).get(key, key)

    try:
        return text.format(**kwargs)
    except Exception:
        return text


def get_keyboard(lang_code: str) -> List[str]:
    data = _LOCALE_CACHE.get(lang_code)
    if not data:
        data = _LOCALE_CACHE.get(DEFAULT_LANG)

    if not data:
        return ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]

    return data.get("keyboard", ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"])