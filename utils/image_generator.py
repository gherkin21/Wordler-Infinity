from PIL import Image, ImageDraw, ImageFont
import io
import os
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# --- Color Constants --- (No changes)
COLOR_CORRECT = (83, 141, 78)
COLOR_PRESENT = (181, 159, 59)
COLOR_ABSENT = (58, 58, 60)
COLOR_EMPTY = (18, 18, 19) # Image background / empty grid cells
COLOR_WHITE = (255, 255, 255)
COLOR_NUMBER = (200, 200, 200) # Color for row numbers
COLOR_KEY_DEFAULT_BG = (129, 131, 132)
COLOR_KEY_DEFAULT_FG = COLOR_WHITE

# --- Grid Constants ---
TILE_SIZE = 75
TILE_SPACING = 8
GRID_LETTER_SIZE_RATIO = 0.65
MAX_GRID_HEIGHT_ROWS = 10   # Max rows grid area can *ever* hold
INITIAL_DISPLAY_ROWS = 6    # Rows shown initially until surpassed
WORD_LENGTH = 5

# --- Row Number Constants --- (No changes)
NUMBER_AREA_WIDTH = 30
NUMBER_SPACING = 8
NUMBER_FONT_SIZE = 18

# Calculate Grid Section width (doesn't change)
GRID_SECTION_WIDTH = (TILE_SIZE * WORD_LENGTH) + (TILE_SPACING * (WORD_LENGTH - 1))
TOTAL_GRID_SECTION_WIDTH = NUMBER_AREA_WIDTH + NUMBER_SPACING + GRID_SECTION_WIDTH

# --- Keyboard Constants --- (No changes)
KEY_WIDTH = TILE_SIZE
KEY_HEIGHT = 50
KEY_SPACING = 6
KEY_V_SPACING = 8
KEY_FONT_SIZE = 20
KEYS_ROW1 = "QWERTYUIOP"; KEYS_ROW2 = "ASDFGHJKL"; KEYS_ROW3 = "ZXCVBNM"
KEY_ROWS = [KEYS_ROW1, KEYS_ROW2, KEYS_ROW3]
MAX_KEYS_IN_ROW = max(len(row) for row in KEY_ROWS)
KEYBOARD_WIDTH = (KEY_WIDTH * MAX_KEYS_IN_ROW) + (KEY_SPACING * (MAX_KEYS_IN_ROW - 1))
KEYBOARD_HEIGHT = (KEY_HEIGHT * len(KEY_ROWS)) + (KEY_V_SPACING * (len(KEY_ROWS) - 1))
KEYBOARD_Y_OFFSET = 20

# --- Overall Image Constants ---
BORDER_PADDING = 15
# Image width is fixed based on the wider element (grid section or keyboard)
IMAGE_WIDTH = max(TOTAL_GRID_SECTION_WIDTH, KEYBOARD_WIDTH) + (BORDER_PADDING * 2)
# IMAGE_HEIGHT will be calculated dynamically based on the number of grid rows shown

# --- Font Path --- (No changes)
FONT_DIR = "fonts"; FONT_FILENAME = "DejaVuSans-Bold.ttf"; FONT_PATH = os.path.join(FONT_DIR, FONT_FILENAME)

# --- Letter State Mapping & Key Color Function --- (No changes)
STATE_CORRECT = 3; STATE_PRESENT = 2; STATE_ABSENT = 1; STATE_UNUSED = 0
EMOJI_TO_STATE = {"🟩": STATE_CORRECT, "🟨": STATE_PRESENT, "⬜": STATE_ABSENT}
def get_key_colors(state: int) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    if state == STATE_CORRECT: return COLOR_CORRECT, COLOR_WHITE
    elif state == STATE_PRESENT: return COLOR_PRESENT, COLOR_WHITE
    elif state == STATE_ABSENT: return COLOR_ABSENT, COLOR_WHITE
    else: return COLOR_KEY_DEFAULT_BG, COLOR_KEY_DEFAULT_FG

# --- Main Image Generator Function ---
def generate_wordle_image(
    guesses: List[str],
    results: List[List[str]],
    letter_states: Dict[str, int]
) -> io.BytesIO | None:
    """
    Generates Wordle image: shows 1-6 rows (fixed 6 height), grows 7-10, then scrolls last 10.
    """
    try:
        num_guesses_made = len(guesses)

        # --- Determine number of rows for grid canvas and data slice ---
        if num_guesses_made <= INITIAL_DISPLAY_ROWS:
            # Fixed height of 6 rows for guesses 1-6
            grid_canvas_rows = INITIAL_DISPLAY_ROWS
            start_guess_index = 0
            rows_to_draw_data = num_guesses_made
        elif num_guesses_made <= MAX_GRID_HEIGHT_ROWS:
            # Growing height for guesses 7-10
            grid_canvas_rows = num_guesses_made
            start_guess_index = 0
            rows_to_draw_data = num_guesses_made
        else: # num_guesses_made > MAX_GRID_HEIGHT_ROWS
            # Fixed height of 10 rows, scrolling for guesses 11+
            grid_canvas_rows = MAX_GRID_HEIGHT_ROWS
            start_guess_index = num_guesses_made - MAX_GRID_HEIGHT_ROWS
            rows_to_draw_data = MAX_GRID_HEIGHT_ROWS

        # --- Calculate Dynamic Image Height ---
        current_grid_height = (TILE_SIZE * grid_canvas_rows) + (TILE_SPACING * max(0, grid_canvas_rows - 1)) # Use max(0,...) for safety if 0 rows
        current_image_height = (BORDER_PADDING * 2) + current_grid_height + KEYBOARD_Y_OFFSET + KEYBOARD_HEIGHT

        # --- Create Image Canvas ---
        image = Image.new("RGB", (IMAGE_WIDTH, current_image_height), COLOR_EMPTY)
        draw = ImageDraw.Draw(image)

        # Load Fonts
        try:
            grid_font_size = int(TILE_SIZE * GRID_LETTER_SIZE_RATIO)
            grid_font = ImageFont.truetype(FONT_PATH, grid_font_size)
            key_font = ImageFont.truetype(FONT_PATH, KEY_FONT_SIZE)
            number_font = ImageFont.truetype(FONT_PATH, NUMBER_FONT_SIZE)
        except IOError: logger.error(f"Font not found: {FONT_PATH}"); return None

        # --- Calculate starting X position for centered grid section ---
        grid_section_start_x = BORDER_PADDING + (IMAGE_WIDTH - (BORDER_PADDING * 2) - TOTAL_GRID_SECTION_WIDTH) / 2
        number_area_start_x = grid_section_start_x
        grid_tiles_start_x = number_area_start_x + NUMBER_AREA_WIDTH + NUMBER_SPACING

        # --- Draw Wordle Grid Rows with Data ---
        for draw_row_index in range(rows_to_draw_data):
            actual_guess_index = start_guess_index + draw_row_index
            row_number = actual_guess_index + 1
            start_y = BORDER_PADDING + draw_row_index * (TILE_SIZE + TILE_SPACING)

            # Draw Row Number ...
            num_str = str(row_number)
            try: num_bbox = draw.textbbox((0, 0), num_str, font=number_font)
            except AttributeError: num_bbox = (0,0) + draw.textsize(num_str, font=number_font)
            num_width = num_bbox[2] - num_bbox[0]; num_height = num_bbox[3] - num_bbox[1]
            num_x = number_area_start_x + NUMBER_AREA_WIDTH - num_width
            num_y = start_y + (TILE_SIZE - num_height) / 2
            draw.text((num_x, num_y), num_str, fill=COLOR_NUMBER, font=number_font)

            # Draw Tiles for this row ...
            current_guess = guesses[actual_guess_index].upper()
            current_result_emojis = results[actual_guess_index]
            for c in range(WORD_LENGTH):
                tile_start_x = grid_tiles_start_x + c * (TILE_SIZE + TILE_SPACING)
                tile_rect = [(tile_start_x, start_y), (tile_start_x + TILE_SIZE, start_y + TILE_SIZE)]
                tile_color = COLOR_ABSENT
                if c < len(current_result_emojis):
                     state = EMOJI_TO_STATE.get(current_result_emojis[c], STATE_ABSENT)
                     tile_color, _ = get_key_colors(state)
                else: logger.warning(f"Result missing G{row_number} C{c}")
                draw.rectangle(tile_rect, fill=tile_color)
                if c < len(current_guess): # Draw Letter
                    letter = current_guess[c]
                    try: bbox = draw.textbbox((0, 0), letter, font=grid_font)
                    except AttributeError: bbox = (0,0) + draw.textsize(letter, font=grid_font)
                    text_width = bbox[2] - bbox[0]; text_height = bbox[3] - bbox[1]
                    text_x = tile_start_x + (TILE_SIZE - text_width) / 2
                    text_y = start_y + (TILE_SIZE - text_height) / 2 - (grid_font_size * 0.1)
                    draw.text((text_x, text_y), letter, fill=COLOR_WHITE, font=grid_font)

        # --- Draw empty grid rows ONLY if needed (guesses 1-5) ---
        empty_row_start_index = rows_to_draw_data
        # Only draw empty rows if the canvas is set to the initial fixed height (6)
        if grid_canvas_rows == INITIAL_DISPLAY_ROWS and num_guesses_made < INITIAL_DISPLAY_ROWS:
            for i in range(empty_row_start_index, grid_canvas_rows):
                 start_y = BORDER_PADDING + i * (TILE_SIZE + TILE_SPACING)
                 # Draw empty placeholder tiles
                 for c in range(WORD_LENGTH):
                     tile_start_x = grid_tiles_start_x + c * (TILE_SIZE + TILE_SPACING)
                     tile_rect = [(tile_start_x, start_y), (tile_start_x + TILE_SIZE, start_y + TILE_SIZE)]
                     draw.rectangle(tile_rect, fill=COLOR_EMPTY, outline=(50,50,52))

        # --- Draw Keyboard ---
        # Calculate Y position based on the *current* grid height
        keyboard_start_y = BORDER_PADDING + current_grid_height + KEYBOARD_Y_OFFSET
        for r, key_row_str in enumerate(KEY_ROWS):
            # ... (keyboard drawing logic is the same as before) ...
            current_y = keyboard_start_y + r * (KEY_HEIGHT + KEY_V_SPACING)
            num_keys = len(key_row_str)
            row_width = (KEY_WIDTH * num_keys) + (KEY_SPACING * (num_keys - 1))
            current_x = BORDER_PADDING + (IMAGE_WIDTH - (BORDER_PADDING * 2) - row_width) / 2
            for key_char in key_row_str:
                state = letter_states.get(key_char.lower(), STATE_UNUSED)
                key_bg, key_fg = get_key_colors(state)
                key_rect = [(current_x, current_y), (current_x + KEY_WIDTH, current_y + KEY_HEIGHT)]
                draw.rectangle(key_rect, fill=key_bg)
                try: bbox = draw.textbbox((0, 0), key_char, font=key_font)
                except AttributeError: bbox = (0,0) + draw.textsize(key_char, font=key_font)
                text_width = bbox[2] - bbox[0]; text_height = bbox[3] - bbox[1]
                text_x = current_x + (KEY_WIDTH - text_width) / 2
                text_y = current_y + (KEY_HEIGHT - text_height) / 2 - (KEY_FONT_SIZE * 0.05)
                draw.text((text_x, text_y), key_char, fill=key_fg, font=key_font)
                current_x += KEY_WIDTH + KEY_SPACING

        # Save Image
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr

    except Exception as e:
        logger.exception(f"Error generating Wordle image: {e}")
        return None