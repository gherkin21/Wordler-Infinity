from PIL import Image, ImageDraw, ImageFont
import io
import os
import logging

logger = logging.getLogger(__name__)

# --- Constants ---
COLOR_CORRECT = (83, 141, 78)
COLOR_PRESENT = (181, 159, 59)
COLOR_ABSENT = (58, 58, 60)
COLOR_EMPTY = (18, 18, 19) # Background for image/unused tiles
COLOR_WHITE = (255, 255, 255)

TILE_SIZE = 70
TILE_SPACING = 8
BORDER_PADDING = 10
LETTER_SIZE_RATIO = 0.7

# NEW: Define max rows to SHOW in the image
DISPLAY_ROWS = 10 # Show the last 10 guesses, or fewer if less than 10 made
WORD_LENGTH = 5

# Image dimensions now based on DISPLAY_ROWS
IMAGE_WIDTH = (TILE_SIZE * WORD_LENGTH) + (TILE_SPACING * (WORD_LENGTH - 1)) + (BORDER_PADDING * 2)
IMAGE_HEIGHT = (TILE_SIZE * DISPLAY_ROWS) + (TILE_SPACING * (DISPLAY_ROWS - 1)) + (BORDER_PADDING * 2)

FONT_DIR = "fonts"
FONT_FILENAME = "DejaVuSans-Bold.ttf"
FONT_PATH = os.path.join(FONT_DIR, FONT_FILENAME)

CORRECT_SPOT_EMOJI = "🟩"
WRONG_SPOT_EMOJI = "🟨"
NOT_IN_WORD_EMOJI = "⬜"

def get_color_for_result(result_emoji: str) -> tuple:
    if result_emoji == CORRECT_SPOT_EMOJI: return COLOR_CORRECT
    if result_emoji == WRONG_SPOT_EMOJI: return COLOR_PRESENT
    if result_emoji == NOT_IN_WORD_EMOJI: return COLOR_ABSENT
    return COLOR_EMPTY

def generate_wordle_image(guesses: list[str], results: list[list[str]]) -> io.BytesIO | None:
    """
    Generates a Wordle board image, showing up to DISPLAY_ROWS (most recent).
    """
    try:
        image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), COLOR_EMPTY)
        draw = ImageDraw.Draw(image)

        font_size = int(TILE_SIZE * LETTER_SIZE_RATIO)
        try:
            font = ImageFont.truetype(FONT_PATH, font_size)
        except IOError:
            logger.error(f"Font not found at {FONT_PATH}. Using default.")
            try: font = ImageFont.load_default()
            except IOError: logger.error("Default font failed."); return None

        # --- Determine which guesses/results to display ---
        num_guesses_made = len(guesses)
        rows_to_draw = min(num_guesses_made, DISPLAY_ROWS)

        # Get the slice of guesses/results to display (the last ones)
        start_index = num_guesses_made - rows_to_draw
        display_guesses = guesses[start_index:]
        display_results = results[start_index:]

        # --- Draw the visible tiles ---
        for r in range(rows_to_draw): # Loop only through the rows we want to draw
            start_y = BORDER_PADDING + r * (TILE_SIZE + TILE_SPACING)
            current_guess = display_guesses[r].upper()
            current_result_emojis = display_results[r]

            for c in range(WORD_LENGTH):
                start_x = BORDER_PADDING + c * (TILE_SIZE + TILE_SPACING)
                tile_rect = [(start_x, start_y), (start_x + TILE_SIZE, start_y + TILE_SIZE)]

                tile_color = COLOR_ABSENT # Default to absent if something is wrong
                if c < len(current_result_emojis):
                    tile_color = get_color_for_result(current_result_emojis[c])
                else:
                     logger.warning(f"Result missing for guess index {start_index + r}, char {c}")


                draw.rectangle(tile_rect, fill=tile_color)

                if current_guess and c < len(current_guess):
                    letter = current_guess[c]
                    try:
                        bbox = draw.textbbox((0, 0), letter, font=font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                    except AttributeError:
                         text_width, text_height = draw.textsize(letter, font=font)

                    text_x = start_x + (TILE_SIZE - text_width) / 2
                    text_y = start_y + (TILE_SIZE - text_height) / 2 - (font_size * 0.1)
                    draw.text((text_x, text_y), letter, fill=COLOR_WHITE, font=font)

        # --- Optional: Draw empty rows below the guesses if less than DISPLAY_ROWS were made ---
        # This keeps the image height consistent
        for r in range(rows_to_draw, DISPLAY_ROWS):
             start_y = BORDER_PADDING + r * (TILE_SIZE + TILE_SPACING)
             for c in range(WORD_LENGTH):
                 start_x = BORDER_PADDING + c * (TILE_SIZE + TILE_SPACING)
                 tile_rect = [(start_x, start_y), (start_x + TILE_SIZE, start_y + TILE_SIZE)]
                 # Use a slightly different empty color? Or same as background? Let's use background.
                 draw.rectangle(tile_rect, fill=COLOR_EMPTY, outline=(50,50,52)) # Slight outline maybe


        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr

    except Exception as e:
        logger.exception(f"Error generating Wordle image: {e}")
        return None