from PIL import Image, ImageDraw, ImageFont
import io
import os
import logging

logger = logging.getLogger(__name__)


IMG_WIDTH = 700
BG_COLOR = (18, 18, 19)
TEXT_COLOR = (255, 255, 255)
BAR_COLOR = (83, 141, 78)
BAR_BG_COLOR = (58, 58, 60)
FONT_DIR = "fonts"
FONT_FILENAME = "DejaVuSans-Bold.ttf"
FONT_PATH = os.path.join(FONT_DIR, FONT_FILENAME)


def generate_stats_image(user_name: str, stats_data: dict, avatar_bytes: bytes = None,
                         labels: dict = None) -> io.BytesIO | None:
    try:
        if labels is None:
            labels = {}

        header_text = labels.get("stats_header", f"STATISTICS FOR {user_name}").upper().format(user=user_name.upper())
        if "{USER}" in header_text: header_text = header_text.format(USER=user_name.upper())

        raw_dist = stats_data.get("distribution", {})
        display_dist = {i: 0 for i in range(1, 11)}

        for k, v in raw_dist.items():
            if not str(k).isdigit(): continue
            guesses = int(k)
            if guesses >= 10:
                display_dist[10] += v
            elif 1 <= guesses < 10:
                display_dist[guesses] += v

        avatar_size = 80
        avatar_padding = 20

        current_y_cursor = 20

        avatar_y = current_y_cursor
        if avatar_bytes:
            current_y_cursor += avatar_size + 10

        title_y = current_y_cursor + 15
        current_y_cursor += 50

        stats_row_y = current_y_cursor + 10
        current_y_cursor += 80

        header_height = current_y_cursor

        chart_title_height = 40
        bar_height = 24
        bar_spacing = 10
        row_height = bar_height + bar_spacing
        num_rows = 10
        chart_section_height = num_rows * row_height

        footer_height = 80
        bottom_padding = 20

        total_height = header_height + chart_title_height + chart_section_height + footer_height + bottom_padding


        image = Image.new("RGB", (IMG_WIDTH, total_height), BG_COLOR)
        draw = ImageDraw.Draw(image)

        try:
            title_font = ImageFont.truetype(FONT_PATH, 28)
            stat_num_font = ImageFont.truetype(FONT_PATH, 36)
            stat_label_font = ImageFont.truetype(FONT_PATH, 14)
            bar_font = ImageFont.truetype(FONT_PATH, 18)
            footer_font = ImageFont.truetype(FONT_PATH, 20)
            dist_title_font = ImageFont.truetype(FONT_PATH, 20)
        except IOError:
            logger.error(f"Font not found: {FONT_PATH}")
            return None

        if avatar_bytes:
            try:
                avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

                mask = Image.new('L', (avatar_size, avatar_size), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)

                avatar_x = (IMG_WIDTH - avatar_size) // 2

                image.paste(avatar_img, (avatar_x, avatar_y), mask)

            except Exception as e:
                logger.warning(f"Failed to process avatar: {e}")

        draw.text((IMG_WIDTH // 2, title_y), header_text, fill=TEXT_COLOR, font=title_font,
                  anchor="mm")

        stat_items = [
            (str(stats_data.get("played", 0)), labels.get("stats_played", "Played")),
            (f"{stats_data.get('win_pct', 0):.0f}", labels.get("stats_win_pct", "Win %")),
            (str(stats_data.get("current_streak", 0)), labels.get("stats_streak_current", "Cur Streak")),
            (str(stats_data.get("max_streak", 0)), labels.get("stats_streak_max", "Max Streak"))
        ]

        section_width = IMG_WIDTH // 4
        for i, (val, label) in enumerate(stat_items):
            center_x = (i * section_width) + (section_width // 2)
            draw.text((center_x, stats_row_y), val, fill=TEXT_COLOR, font=stat_num_font, anchor="mm")
            draw.text((center_x, stats_row_y + 30), label, fill=TEXT_COLOR, font=stat_label_font, anchor="mm")

        dist_y_start = header_height
        dist_title = labels.get("stats_distribution", "GUESS DISTRIBUTION")
        draw.text((IMG_WIDTH // 2, dist_y_start), dist_title, fill=TEXT_COLOR, font=dist_title_font,
                  anchor="mm")

        total_wins = sum(display_dist.values())
        max_freq = max(display_dist.values()) if display_dist and total_wins > 0 else 1

        bar_start_y = dist_y_start + 30
        left_margin = 80
        right_margin = 50
        max_bar_width = IMG_WIDTH - left_margin - right_margin

        current_y = bar_start_y

        for i in range(1, 11):
            count = display_dist[i]
            label_text = str(i) if i < 10 else "10+"

            draw.text((left_margin - 15, current_y + bar_height // 2), label_text, fill=TEXT_COLOR, font=bar_font,
                      anchor="rm")

            if total_wins > 0 and count > 0:
                width_ratio = count / max_freq
                bar_width = max(40, int(width_ratio * max_bar_width))
                color = BAR_COLOR
            else:
                bar_width = 40
                color = BAR_BG_COLOR

            draw.rectangle([(left_margin, current_y), (left_margin + bar_width, current_y + bar_height)], fill=color)

            if count > 0:
                draw.text((left_margin + bar_width - 5, current_y + bar_height // 2), str(count), fill=TEXT_COLOR,
                          font=bar_font, anchor="rm")

            current_y += row_height

        footer_y = current_y + 20
        fav_word = stats_data.get("fav_starter", "N/A")
        if fav_word and fav_word != "N/A":
            fav_word = fav_word.upper()

        footer_raw = labels.get("stats_favorite_starter", "MOST USED STARTING WORD: {word}")
        footer_text = footer_raw.replace("{word}", str(fav_word))

        draw.line([(50, footer_y), (IMG_WIDTH - 50, footer_y)], fill=BAR_BG_COLOR, width=2)
        draw.text((IMG_WIDTH // 2, footer_y + 40), footer_text, fill=TEXT_COLOR,
                  font=footer_font, anchor="mm")

        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr

    except Exception as e:
        logger.exception(f"Error generating stats image: {e}")
        return None