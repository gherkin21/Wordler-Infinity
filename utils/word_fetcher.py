import random
import logging
import os

logger = logging.getLogger(__name__)

DATA_DIR = "data" # Define data directory
ANSWER_FILE = os.path.join(DATA_DIR, "answers.txt")
ALLOWED_FILE = os.path.join(DATA_DIR, "allowed.txt")

# --- Globals to cache word lists ---
possible_answers = []
allowed_guesses = set() # Use a set for faster lookups

def load_word_list_from_file(filepath):
    """Loads a word list from a local file."""
    try:
        # Ensure UTF-8 encoding is used, common for text files
        with open(filepath, 'r', encoding='utf-8') as f:
            # Read lines, strip whitespace, convert to lower, filter empty lines
            words = [line.strip().lower() for line in f if line.strip()]
            return words
    except FileNotFoundError:
        logger.error(f"Error: Word list file not found at {filepath}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading word list from {filepath}: {e}")
        return None

async def load_word_lists():
    """Loads both word lists from local files."""
    global possible_answers, allowed_guesses
    logger.info(f"Attempting to load word lists from {ANSWER_FILE} and {ALLOWED_FILE}...")

    # Ensure data directory exists (though persistence.py likely does this too)
    os.makedirs(DATA_DIR, exist_ok=True)

    answers = load_word_list_from_file(ANSWER_FILE)
    allowed = load_word_list_from_file(ALLOWED_FILE)

    if answers is None or allowed is None:
        logger.error("Failed to load one or both word lists from local files. Bot may not function correctly.")
        return False # Indicate failure

    possible_answers = [word for word in answers if len(word) == 5 and word.isalpha()]
    # Allowed guesses include the answers plus other valid words
    temp_allowed = set(word for word in allowed if len(word) == 5 and word.isalpha())
    allowed_guesses = temp_allowed.union(set(possible_answers)) # Ensure all answers are allowed guesses

    if not possible_answers:
        logger.error("Answer list is empty after processing. Check {ANSWER_FILE}.")
        return False
    if not allowed_guesses:
        logger.error("Allowed guesses list is empty after processing. Check {ALLOWED_FILE}.")
        return False

    logger.info(f"Loaded {len(possible_answers)} possible answers and {len(allowed_guesses)} allowed guesses from local files.")
    return True # Indicate success

# --- Rest of the functions remain the same ---

def get_random_word():
    """Returns a random word from the possible answers list."""
    if not possible_answers:
        logger.error("Attempted to get random word, but answer list is empty.")
        return None
    return random.choice(possible_answers)

def is_allowed_guess(word):
    """Checks if a word is in the allowed guesses list."""
    return word.lower() in allowed_guesses

def get_possible_answers():
    """Returns the list of possible answers."""
    return possible_answers

def get_allowed_guesses():
    """Returns the set of allowed guesses."""
    return allowed_guesses