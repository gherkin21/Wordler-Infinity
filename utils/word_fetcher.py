import random
import logging
import os

logger = logging.getLogger(__name__)

DATA_DIR = "data"
WORD_DATA = {}


def load_word_list_from_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return [line.strip().lower() for line in f if line.strip()]
    except FileNotFoundError:
        return None


async def load_word_lists():
    """Loads word lists for all found language subdirectories."""
    global WORD_DATA
    logger.info("Loading word lists for all languages...")

    os.makedirs(DATA_DIR, exist_ok=True)

    found_langs = 0
    for item in os.listdir(DATA_DIR):
        lang_path = os.path.join(DATA_DIR, item)
        if os.path.isdir(lang_path):
            answers_path = os.path.join(lang_path, "answers.txt")
            allowed_path = os.path.join(lang_path, "allowed.txt")

            answers = load_word_list_from_file(answers_path)
            allowed = load_word_list_from_file(allowed_path)

            if answers and allowed:
                valid_answers = [w for w in answers if len(w) == 5 and w.isalpha()]
                temp_allowed = set(w for w in allowed if len(w) == 5 and w.isalpha())
                full_allowed = temp_allowed.union(set(valid_answers))

                WORD_DATA[item] = {
                    "answers": valid_answers,
                    "allowed": full_allowed
                }
                logger.info(f"Loaded language '{item}': {len(valid_answers)} answers.")
                found_langs += 1
            else:
                logger.warning(f"Skipping '{item}': Missing answers.txt or allowed.txt")

    if found_langs == 0:
        logger.error("No valid word lists found in data/ subdirectories!")
        return False

    return True


def get_random_word(lang="en"):
    data = WORD_DATA.get(lang, WORD_DATA.get("en"))
    if not data or not data["answers"]: return None
    return random.choice(data["answers"])


def is_allowed_guess(word, lang="en"):
    data = WORD_DATA.get(lang, WORD_DATA.get("en"))
    if not data: return False
    return word.lower() in data["allowed"]
