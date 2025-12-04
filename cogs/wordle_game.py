import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, User, ui
import logging
from collections import Counter
import io
import time
import random
from typing import List, Dict, Tuple, Optional

from utils import word_fetcher, persistence, localization, image_generator
from utils.image_generator import EMOJI_TO_STATE, STATE_UNUSED

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT = 30 * 60

CORRECT_SPOT_EMOJI = "🟩";
WRONG_SPOT_EMOJI = "🟨";
NOT_IN_WORD_EMOJI = "⬜"


def initial_letter_states() -> Dict[str, int]:
    """Creates the initial dictionary mapping 'a'-'z' to STATE_UNUSED."""
    return {chr(ord('a') + i): STATE_UNUSED for i in range(26)}


class WordleGuessModal(ui.Modal):
    guess_input = ui.TextInput(
        label="5-Letter Word",
        style=discord.TextStyle.short,
        placeholder="your 5-letter word",
        required=True,
        min_length=5,
        max_length=5
    )

    def __init__(self, cog, game_id: int, lang: str = "en"):
        super().__init__(title=localization.get_text(lang, "modal_title"))
        self.cog = cog
        self.game_id = game_id
        self.lang = lang


        self.guess_input.label = localization.get_text(lang, "modal_label")
        self.guess_input.placeholder = localization.get_text(lang, "modal_placeholder")

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer()

        guess = self.guess_input.value.lower().strip()

        await self.cog.handle_ui_guess(interaction, self.game_id, guess)


class WordleGameView(ui.View):
    def __init__(self, cog, game_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id

    @ui.button(label="Make Guess", style=discord.ButtonStyle.success, emoji="📝")
    async def guess_button(self, interaction: Interaction, button: ui.Button):
        if self.game_id not in self.cog.all_games:
            lang = "en"
            if interaction.guild_id:
                lang = await persistence.get_guild_language(interaction.guild_id)

            await interaction.response.send_message(localization.get_text(lang, "game_ended_expired"), ephemeral=True)
            return

        game_state = self.cog.all_games[self.game_id]
        lang = game_state.get("language", "en")

        if game_state["game_type"] == "multiplayer":
            current_player = game_state["players"][game_state["current_turn_index"]]
            if interaction.user.id != current_player:
                msg = localization.get_text(lang, "not_your_turn", player=current_player)
                await interaction.response.send_message(msg, ephemeral=True)
                return
        elif interaction.user.id not in game_state["players"]:
            await interaction.response.send_message(localization.get_text(lang, "not_in_game"), ephemeral=True)
            return

        await interaction.response.send_modal(WordleGuessModal(self.cog, self.game_id, lang=lang))

    @ui.button(label="Give Up", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def giveup_button(self, interaction: Interaction, button: ui.Button):
        if self.game_id not in self.cog.all_games:
            lang = "en"
            if interaction.guild_id:
                lang = await persistence.get_guild_language(interaction.guild_id)
            await interaction.response.send_message(localization.get_text(lang, "game_ended_expired"), ephemeral=True)
            return

        game_state = self.cog.all_games[self.game_id]
        lang = game_state.get("language", "en")

        if interaction.user.id not in game_state["players"]:
            await interaction.response.send_message(localization.get_text(lang, "not_in_game"), ephemeral=True)
            return

        await interaction.response.defer()
        await self.cog.handle_ui_giveup(interaction, self.game_id)


class WordleGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.chatter_delay = 5 * 60
        self.chatter_cooldowns: Dict[int, float] = {}
        self.all_games: Dict[int, Dict] = {}
        try:
            self.check_inactive_games.start()
        except RuntimeError:
            logger.warning("check_inactive_games task already running or failed to start immediately.")

    async def cog_load(self):
        logger.info("WordleGameCog loaded.")
        self.all_games = {}


    @tasks.loop(minutes=1.0)
    async def check_inactive_games(self):
        """Periodically checks for and removes inactive games, notifying players via DM."""
        now = time.time()
        games_to_delete = []

        current_games = list(self.all_games.items())

        for game_id, game_state in current_games:
            if not game_state: continue

            last_activity = game_state.get("last_activity_ts", now)
            idle_time = now - last_activity

            if idle_time > INACTIVITY_TIMEOUT:
                games_to_delete.append((game_id, game_state))

        if games_to_delete:
            logger.info(f"Found {len(games_to_delete)} inactive games to delete.")

        for game_id, game_state_to_delete in games_to_delete:
            if game_id in self.all_games:
                del self.all_games[game_id]

                lang = game_state_to_delete.get("language", "en")

                channel_id = game_state_to_delete.get("channel_id")
                if channel_id:
                    try:
                        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                        if channel:
                            msg = await channel.fetch_message(game_id)
                            expired_text = localization.get_text(lang, "game_expired_msg")
                            await msg.edit(view=None, content=expired_text)
                    except Exception:
                        pass

                player_ids = game_state_to_delete.get("players", [])
                game_type = game_state_to_delete.get("game_type", "Wordle")
                guild_id = game_state_to_delete.get("guild_id")
                guild_name = "Unknown Server"
                if guild_id:
                    guild = self.bot.get_guild(guild_id)
                    if guild: guild_name = guild.name

                base_msg = localization.get_text(lang, "game_expired_dm", game_type=game_type, guild_name=guild_name)

                for player_id in player_ids:
                    try:
                        user = self.bot.get_user(player_id) or await self.bot.fetch_user(player_id)
                        if user and not user.bot:
                            await user.send(base_msg)
                    except Exception:
                        pass

    @check_inactive_games.before_loop
    async def before_check_inactive_games(self):
        await self.bot.wait_until_ready()

    def check_guild_and_channel(allow_anywhere_if_not_set: bool = False):
        async def predicate(interaction: Interaction) -> bool:
            if not interaction.guild:
                await interaction.response.send_message("This command only works in a server.", ephemeral=True)
                return False

            guild_id = interaction.guild_id
            lang = await persistence.get_guild_language(guild_id)

            allowed_channel_id = await persistence.get_guild_channel_id(guild_id)

            if allowed_channel_id is None:
                return True
            elif interaction.channel_id == allowed_channel_id:
                return True
            else:
                try:
                    channel = interaction.guild.get_channel(
                        allowed_channel_id) or await interaction.guild.fetch_channel(allowed_channel_id)
                    channel_name = channel.mention if channel else f"ID: {allowed_channel_id}"

                    msg = localization.get_text(lang, "wrong_channel", channel=channel_name)
                    await interaction.response.send_message(msg, ephemeral=True)
                except Exception:
                    msg = localization.get_text(lang, "wrong_channel", channel="the designated channel")
                    await interaction.response.send_message(msg, ephemeral=True)
                return False

        return app_commands.check(predicate)

    async def _is_user_busy(self, guild_id: int, user_id: int) -> bool:
        """Checks if the user is in ANY active game in the specified guild."""
        for game_state in self.all_games.values():
            if game_state.get("guild_id") == guild_id and \
                    user_id in game_state.get("players", []):
                return True
        return False

    async def _find_user_game_in_channel(self, channel_id: int, user_id: int) -> Optional[Tuple[int, Dict]]:
        """Finds the game ID and state for a user in a specific channel."""
        for game_id, game_state in self.all_games.items():
            if game_state.get("channel_id") == channel_id and \
                    user_id in game_state.get("players", []):
                return game_id, game_state
        return None, None

    def generate_feedback(self, guess: str, target: str) -> list[str]:
        """Generates the feedback emojis for a guess."""
        if len(guess) != 5 or len(target) != 5: return [NOT_IN_WORD_EMOJI] * 5
        feedback = [NOT_IN_WORD_EMOJI] * 5
        target_counts = Counter(target)
        guess_list = list(guess)
        target_list = list(target)

        for i in range(5):
            if guess_list[i] == target_list[i]:
                feedback[i] = CORRECT_SPOT_EMOJI
                target_counts[guess_list[i]] -= 1
                guess_list[i] = None

        for i in range(5):
            if guess_list[i] is not None and guess_list[i] in target_counts and target_counts[guess_list[i]] > 0:
                feedback[i] = WRONG_SPOT_EMOJI
                target_counts[guess_list[i]] -= 1

        return feedback

    def calculate_points(self, num_guesses: int) -> int:
        """Calculates points based on number of guesses for solo mode."""
        if num_guesses <= 0: return 0
        return max(0, 11 - num_guesses)

    def create_game_embed(self, context_obj, game_state: dict, status_message: str = None, is_multiplayer: bool = False,
                          attach_image: bool = False) -> discord.Embed:
        """Creates the embed for the current game state."""
        if isinstance(context_obj, Interaction):
            user = context_obj.user
            channel = context_obj.channel
        else:
            user = context_obj
            channel = None

        lang = game_state.get("language", "en")
        embed = None

        if is_multiplayer:
            players = game_state.get("players", [])
            current_turn_idx = game_state.get("current_turn_index", 0)
            current_player_id = players[current_turn_idx] if players and current_turn_idx < len(players) else None
            current_player_mention = f"<@{current_player_id}>" if current_player_id else "Unknown Player"

            title = f"Multiplayer Wordle"

            if status_message:
                description = status_message
            else:
                description = localization.get_text(lang, "multiplayer_description", user=current_player_mention,
                                                    guess_num=len(game_state.get('guesses', [])) + 1)

            embed = discord.Embed(title=title, description=description, color=discord.Color.purple())
            player_list_str = ", ".join(game_state.get("player_mentions", ["?"]))
            embed.add_field(name=localization.get_text(lang, "footer_players"),
                            value=player_list_str if player_list_str else "None", inline=False)
            embed.set_footer(text=localization.get_text(lang, "footer_play"))
        else:
            current_guess_num = len(game_state.get("guesses", []))
            title = f"Wordle: {user.display_name}"

            if status_message:
                description = status_message
            else:
                description = localization.get_text(lang, "start_solo", guess_num=current_guess_num + 1)

            color = discord.Color.blue()

            embed = discord.Embed(title=title, description=description, color=color)
            embed.set_footer(text=localization.get_text(lang, "footer_play"))

        if attach_image and embed:
            embed.set_image(url="attachment://wordle_board.png")
        return embed

    async def _process_core_guess_logic(self, game_state: dict, guess: str, user):
        target_word = game_state["word"]
        lang = game_state.get("language", "en")

        feedback = self.generate_feedback(guess, target_word)
        game_state["guesses"].append(guess)
        game_state["results"].append(feedback)

        current_letter_states = game_state.get("letter_states", initial_letter_states())
        for i, letter in enumerate(guess):
            if letter.isalpha():
                new_state = EMOJI_TO_STATE.get(feedback[i], STATE_UNUSED)
                if new_state > current_letter_states.get(letter, STATE_UNUSED):
                    current_letter_states[letter] = new_state

        game_state["last_activity_ts"] = time.time()
        num_guesses_total = len(game_state["guesses"])

        game_type = game_state["game_type"]
        status_message = ""
        game_over = False
        points = 0

        if guess == target_word:
            game_over = True
            if game_type == 'solo':
                points = self.calculate_points(num_guesses_total)
                status_message = localization.get_text(lang, "win_solo", user=user.mention, word=target_word.upper(),
                                                       tries=num_guesses_total, points=points)

                await persistence.update_leaderboard(game_state["guild_id"], user.id, points_earned=points)
                await persistence.update_detailed_stats(
                    user_id=user.id,
                    is_win=True,
                    num_guesses=num_guesses_total,
                    starting_word=game_state["guesses"][0] if game_state["guesses"] else None
                )
            else:
                players = ", ".join(game_state.get("player_mentions", ["?"]))
                status_message = localization.get_text(lang, "win_multiplayer", user=user.mention,
                                                       word=target_word.upper(), players=players,
                                                       tries=num_guesses_total)
        else:
            if game_type == 'solo':
                status_message = localization.get_text(lang, "guess_continue_solo", guess_num=num_guesses_total + 1)
            else:
                num_players = len(game_state.get("players", []))
                game_state["current_turn_index"] = (game_state.get("current_turn_index", 0) + 1) % num_players
                next_player_id = game_state["players"][game_state["current_turn_index"]]
                status_message = localization.get_text(lang, "guess_continue_multiplayer", guess_num=num_guesses_total,
                                                       user=user.mention, next_player=next_player_id)

        kb_layout = localization.get_keyboard(lang)
        img_buffer = image_generator.generate_wordle_image(
            game_state["guesses"],
            game_state["results"],
            game_state["letter_states"],
            keyboard_layout=kb_layout
        )

        file = discord.File(fp=img_buffer, filename="wordle_board.png") if img_buffer else None

        embed = self.create_game_embed(user, game_state, status_message, is_multiplayer=(game_type == 'multiplayer'),
                                       attach_image=(file is not None))

        if game_over:
            embed.color = discord.Color.green()

        return embed, file, game_over


    async def handle_ui_guess(self, interaction: Interaction, game_id: int, guess: str):
        if game_id not in self.all_games:
            lang = "en"
            if interaction.guild_id: lang = await persistence.get_guild_language(interaction.guild_id)
            await interaction.followup.send(localization.get_text(lang, "game_not_found"), ephemeral=True)
            return

        game_state = self.all_games[game_id]
        lang = game_state.get("language", "en")

        if len(guess) != 5:
            await interaction.followup.send(localization.get_text(lang, "guess_length_error"), ephemeral=True);
            return
        if not guess.isalpha():
            await interaction.followup.send(localization.get_text(lang, "guess_letters_error"), ephemeral=True);
            return
        if not word_fetcher.is_allowed_guess(guess, lang=lang):
            await interaction.followup.send(localization.get_text(lang, "guess_dictionary_error", word=guess.upper()),
                                            ephemeral=True);
            return
        if guess in game_state.get("guesses", []):
            await interaction.followup.send(localization.get_text(lang, "guess_already_guessed", word=guess.upper()),
                                            ephemeral=True);
            return

        embed, file, game_over = await self._process_core_guess_logic(game_state, guess, interaction.user)

        view = None if game_over else WordleGameView(self, game_id)

        try:
            await interaction.message.edit(embed=embed, attachments=[file] if file else [], view=view)

            if game_over:
                del self.all_games[game_id]
        except Exception as e:
            logger.error(f"Failed to update UI game: {e}")
            await interaction.followup.send(localization.get_text(lang, "error_update_ui"), ephemeral=True)

    async def handle_ui_giveup(self, interaction: Interaction, game_id: int):
        if game_id in self.all_games:
            game_state = self.all_games[game_id]
            lang = game_state.get("language", "en")
            target = game_state["word"]

            if game_state["game_type"] == 'solo':
                await persistence.update_detailed_stats(
                    user_id=interaction.user.id,
                    is_win=False,
                    num_guesses=len(game_state["guesses"]),
                    starting_word=game_state["guesses"][0] if game_state["guesses"] else None
                )

            del self.all_games[game_id]

            embed = discord.Embed(title=localization.get_text(lang, "game_over_title"),
                                  description=localization.get_text(lang, "game_given_up",
                                                                    user=interaction.user.mention, word=target.upper()),
                                  color=discord.Color.red())

            try:
                await interaction.message.edit(embed=embed, view=None, attachments=[])
            except:
                await interaction.followup.send(localization.get_text(lang, "game_over_loss_msg", word=target.upper()))



    @app_commands.command(name="wordle", description="Starts a new SOLO Wordle game.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def start_solo_wordle(self, interaction: Interaction):
        guild_id = interaction.guild_id;
        lang = await persistence.get_guild_language(guild_id)
        user_id = interaction.user.id;
        channel_id = interaction.channel_id
        if await self._is_user_busy(interaction.guild_id, interaction.user.id):
            await interaction.response.send_message(localization.get_text(lang, "user_busy"),
                                                    ephemeral=True);
            return

        target_word = word_fetcher.get_random_word(lang)
        if not target_word:
            await interaction.response.send_message(localization.get_text(lang, "error_getting_word"), ephemeral=True);
            return

        game_state = {
            "language": lang,
            "game_type": "solo", "guild_id": interaction.guild_id, "channel_id": interaction.channel_id,
            "word": target_word, "players": [interaction.user.id], "player_mentions": [],
            "current_turn_index": 0,
            "guesses": [], "results": [], "letter_states": initial_letter_states(),
            "initiator_id": interaction.user.id, "last_activity_ts": time.time()
        }

        msg = localization.get_text(lang, "start_solo", guess_num=1)
        embed = self.create_game_embed(interaction, game_state, status_message=msg,
                                       is_multiplayer=False, attach_image=False)

        await interaction.response.send_message(embed=embed)
        try:
            message = await interaction.original_response()
            self.all_games[message.id] = game_state

            view = WordleGameView(self, message.id)
            await message.edit(view=view)

            logger.info(f"Started SOLO game (MsgID: {message.id}) user {user_id} guild {guild_id}. Word: {target_word}")
        except Exception as e:
            logger.error(f"Error starting solo game: {e}")

    @app_commands.command(name="multiplayer", description="Starts a turn-based multiplayer Wordle game.")
    @app_commands.describe(player2="Player 2.", player3="Opt.", player4="Opt.", player5="Opt.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def start_multiplayer_wordle(self, interaction: Interaction, player2: User, player3: User = None,
                                       player4: User = None, player5: User = None):
        guild_id = interaction.guild_id;
        channel_id = interaction.channel_id;
        initiator = interaction.user
        lang = await persistence.get_guild_language(guild_id)

        potential_players = [initiator, player2, player3, player4, player5];
        players_actual = [];
        player_ids = set();
        busy_players = []
        for p in potential_players:
            if p is not None and not p.bot:
                if p.id not in player_ids:
                    if await self._is_user_busy(guild_id, p.id):
                        busy_players.append(p.mention)
                    else:
                        players_actual.append(p);
                        player_ids.add(p.id)

        if busy_players:
            await interaction.response.send_message(
                localization.get_text(lang, "multiplayer_busy", busy_users=', '.join(busy_players)), ephemeral=True);
            return
        if len(players_actual) < 2:
            await interaction.response.send_message(localization.get_text(lang, "need_more_players"), ephemeral=True);
            return

        target_word = word_fetcher.get_random_word(lang)
        if not target_word:
            await interaction.response.send_message(localization.get_text(lang, "error_getting_word"), ephemeral=True);
            return

        player_mentions = [p.mention for p in players_actual]
        game_state = {
            "language": lang,
            "game_type": "multiplayer", "guild_id": guild_id, "channel_id": channel_id,
            "word": target_word, "players": [p.id for p in players_actual],
            "player_mentions": player_mentions, "current_turn_index": 0,
            "guesses": [], "results": [], "letter_states": initial_letter_states(),
            "initiator_id": initiator.id, "last_activity_ts": time.time()
        }

        start_msg = localization.get_text(lang, "start_multiplayer", user=initiator.mention)
        embed = self.create_game_embed(interaction, game_state, start_msg,
                                       is_multiplayer=True, attach_image=False)

        await interaction.response.send_message(embed=embed)
        try:
            message = await interaction.original_response()
            self.all_games[message.id] = game_state

            view = WordleGameView(self, message.id)
            await message.edit(view=view)

            logger.info(f"Started MP game (MsgID: {message.id}).")
        except Exception as e:
            logger.error(f"Error starting MP game: {e}")

    @app_commands.command(name="guess", description="Make a guess (Legacy Command).")
    @app_commands.describe(word="Your 5-letter guess")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def guess_wordle(self, interaction: Interaction, word: str):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        channel_id = interaction.channel_id

        lang = await persistence.get_guild_language(guild_id)

        game_id, game_state = await self._find_user_game_in_channel(channel_id, user_id)
        if not game_state:
            await interaction.response.send_message(localization.get_text(lang, "game_not_found"), ephemeral=True)
            return

        lang = game_state.get("language", lang)

        if game_state["game_type"] == 'multiplayer':
            current_player_id = game_state["players"][game_state["current_turn_index"]]
            if user_id != current_player_id:
                await interaction.response.send_message(
                    localization.get_text(lang, "not_your_turn", player=current_player_id),
                    ephemeral=True)
                return

        guess = word.lower().strip()
        if len(guess) != 5:
            await interaction.response.send_message(localization.get_text(lang, "guess_length_error"), ephemeral=True)
            return
        if not guess.isalpha():
            await interaction.response.send_message(localization.get_text(lang, "guess_letters_error"), ephemeral=True)
            return
        if not word_fetcher.is_allowed_guess(guess, lang=lang):
            await interaction.response.send_message(
                localization.get_text(lang, "guess_dictionary_error", word=guess.upper()), ephemeral=True)
            return
        if guess in game_state.get("guesses", []):
            await interaction.response.send_message(
                localization.get_text(lang, "guess_already_guessed", word=guess.upper()), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed, file, game_over = await self._process_core_guess_logic(game_state, guess, interaction.user)

        try:
            message = await interaction.channel.fetch_message(game_id)
            view = None if game_over else WordleGameView(self, game_id)

            await message.edit(embed=embed, attachments=[file] if file else [], view=view)

            if game_over:
                del self.all_games[game_id]
                await interaction.followup.send(
                    localization.get_text(lang, "game_over_loss_msg", word=game_state['word'].upper()),
                    ephemeral=True)
            else:
                await interaction.followup.send(localization.get_text(lang, "guessed_msg", word=guess.upper()),
                                                ephemeral=True)

        except discord.NotFound:
            await interaction.followup.send(embed=embed, file=file)
            if game_over and game_id in self.all_games:
                del self.all_games[game_id]
        except Exception as e:
            logger.error(f"Error updating game from slash guess: {e}")
            await interaction.followup.send(localization.get_text(lang, "error_update_ui"), ephemeral=True)

    @app_commands.command(name="giveup", description="Forfeit your current Wordle game.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def giveup_wordle(self, interaction: Interaction):
        guild_id = interaction.guild_id
        lang = await persistence.get_guild_language(guild_id)

        game_id, game_state = await self._find_user_game_in_channel(interaction.channel_id, interaction.user.id)
        if not game_state:
            await interaction.response.send_message(localization.get_text(lang, "game_not_found"), ephemeral=True);
            return

        await interaction.response.defer()

        target = game_state["word"]
        lang = game_state.get("language", lang)

        if game_state["game_type"] == 'solo':
            await persistence.update_detailed_stats(
                user_id=interaction.user.id,
                is_win=False,
                num_guesses=len(game_state["guesses"]),
                starting_word=game_state["guesses"][0] if game_state["guesses"] else None
            )
        del self.all_games[game_id]

        embed = discord.Embed(title=localization.get_text(lang, "game_over_title"),
                              description=localization.get_text(lang, "game_given_up", user=interaction.user.mention,
                                                                word=target.upper()),
                              color=discord.Color.red())

        try:
            msg = await interaction.channel.fetch_message(game_id)
            await msg.edit(embed=embed, view=None, attachments=[])
            await interaction.followup.send(localization.get_text(lang, "game_forfeited"), ephemeral=True)
        except:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="wordlehelp", description="Shows instructions for the Wordle bot.")
    @app_commands.guild_only()
    async def wordle_help(self, interaction: Interaction):
        lang = await persistence.get_guild_language(interaction.guild_id)

        embed = discord.Embed(title=localization.get_text(lang, "help_title"),
                              description=localization.get_text(lang, "help_desc"),
                              color=discord.Color.blue())

        embed.add_field(name=localization.get_text(lang, "help_how_play_title"),
                        value=localization.get_text(lang, "help_how_play_val"), inline=False)

        embed.add_field(name=localization.get_text(lang, "help_commands_title"),
                        value=localization.get_text(lang, "help_commands_val"), inline=False)

        embed.add_field(name=localization.get_text(lang, "help_scoring_title"),
                        value=localization.get_text(lang, "help_scoring_val"), inline=False)

        embed.add_field(name=localization.get_text(lang, "help_colors_title"),
                        value=localization.get_text(lang, "help_colors_val"), inline=False)

        if interaction.user.guild_permissions.manage_channels:
            embed.add_field(name=localization.get_text(lang, "help_admin_title"),
                            value=localization.get_text(lang, "help_admin_val"),
                            inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WordleGameCog(bot))