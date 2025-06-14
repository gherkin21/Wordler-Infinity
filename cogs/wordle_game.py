# cogs/wordle_game.py

import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, User # Import User type hint
import logging
from collections import Counter
import io
import time
from typing import List, Dict, Tuple, Optional # Added Optional

# Use updated persistence
from utils import word_fetcher, persistence
# Import the image generator module itself
from utils import image_generator
# Import needed constants/helpers from image_generator for state updates
from utils.image_generator import EMOJI_TO_STATE, STATE_UNUSED

logger = logging.getLogger(__name__)

INACTIVITY_TIMEOUT = 30 * 60

CORRECT_SPOT_EMOJI = "🟩"; WRONG_SPOT_EMOJI = "🟨"; NOT_IN_WORD_EMOJI = "⬜"

# Define helper function here
def initial_letter_states() -> Dict[str, int]:
    """Creates the initial dictionary mapping 'a'-'z' to STATE_UNUSED."""
    return {chr(ord('a') + i): STATE_UNUSED for i in range(26)}

class WordleGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Unified game state: { initial_message_id: game_state_dict }
        self.all_games: Dict[int, Dict] = {}
        # Example game_state_dict:
        # {
        #     "game_type": "solo" | "multiplayer",
        #     "guild_id": int,
        #     "channel_id": int,
        #     "word": str,
        #     "players": List[int], # List of user IDs
        #     "player_mentions": List[str], # For MP display
        #     "current_turn_index": int, # Only used in MP
        #     "guesses": List[str],
        #     "results": List[List[str]],
        #     "letter_states": Dict[str, int],
        #     "initiator_id": int,
        #     # message_id is the key now, not stored inside
        # }
        try:
            self.check_inactive_games.start()  # Start the task here
            logger.info("check_inactive_games task started from __init__.")
        except RuntimeError:  # Handle case where loop might already be running (e.g., during reload)
            logger.warning("check_inactive_games task already running or failed to start immediately.")

    async def cog_load(self):
        logger.info("WordleGameCog loaded.")
        self.all_games = {} # Clear games on cog load/reload

    # --- Background Task (MODIFIED NOTIFICATION PART) ---
    @tasks.loop(minutes=1.0)  # Check every 5 minutes
    async def check_inactive_games(self):
        # logger.info(f"Inactive games check started.")
        """Periodically checks for and removes inactive games, notifying players via DM."""
        now = time.time()
        games_to_delete = []  # Store tuples of (game_id, game_state)

        # Iterate safely over a copy of the items
        current_games = list(self.all_games.items())

        for game_id, game_state in current_games:
            if not game_state: continue

            last_activity = game_state.get("last_activity_ts", now)
            idle_time = now - last_activity

            if idle_time > INACTIVITY_TIMEOUT:
                games_to_delete.append((game_id, game_state))  # Store ID and state

        # Now process deletions and notifications
        if games_to_delete:
            logger.info(f"Found {len(games_to_delete)} inactive games to delete.")

        for game_id, game_state_to_delete in games_to_delete:
            if game_id in self.all_games:
                # Remove game first to prevent race conditions if notification takes time
                del self.all_games[game_id]
                logger.info(
                    f"Auto-deleted inactive game {game_id} (Channel: {game_state_to_delete.get('channel_id')}).")

                # --- Notify Players via DM ---
                player_ids = game_state_to_delete.get("players", [])
                game_type = game_state_to_delete.get("game_type", "Wordle")
                channel_id = game_state_to_delete.get("channel_id")
                guild_id = game_state_to_delete.get("guild_id")
                channel_mention = f"<#{channel_id}>" if channel_id else "Unknown Channel"
                guild_name = "Unknown Server"
                if guild_id:
                    guild = self.bot.get_guild(guild_id)
                    if guild: guild_name = guild.name

                base_msg = f"⌛ Your {game_type} Wordle game in channel {channel_mention} on server '{guild_name}' has expired due to inactivity."

                for player_id in player_ids:
                    try:
                        user = self.bot.get_user(player_id) or await self.bot.fetch_user(player_id)
                        if user and not user.bot:  # Ensure user exists and is not a bot
                            await user.send(base_msg)
                            logger.debug(f"Sent inactivity DM to user {player_id} for game {game_id}")
                        elif user.bot:
                            logger.debug(f"Skipping inactivity DM to bot user {player_id}")
                        else:
                            logger.warning(f"Could not find user {player_id} to send inactivity DM.")
                    except discord.NotFound:
                        logger.warning(f"User {player_id} not found for inactivity DM.")
                    except discord.Forbidden:
                        logger.warning(
                            f"Cannot send inactivity DM to user {player_id} (Forbidden - DMs likely closed).")
                    except Exception as e:
                        logger.error(f"Error sending inactivity DM to user {player_id} for game {game_id}: {e}")
                # --- End Notify Players ---

    @check_inactive_games.before_loop
    async def before_check_inactive_games(self):
        await self.bot.wait_until_ready()
        logger.info("Inactive game check loop is ready.")

    @check_inactive_games.error
    async def check_inactive_games_error(self, error):
        logger.error(f"Unhandled error in check_inactive_games loop: {error}")

    # --- Guild Check Decorator ---
    def check_guild_and_channel(allow_anywhere_if_not_set: bool = False):
        """
        Checks if the command is used in a guild and respects the configured channel.
        allow_anywhere_if_not_set: If True, allows commands if no channel is configured for the guild.
        """
        async def predicate(interaction: Interaction) -> bool:
            if not interaction.guild:
                await interaction.response.send_message("This command only works in a server.", ephemeral=True)
                return False

            guild_id = interaction.guild_id
            allowed_channel_id = await persistence.get_guild_channel_id(guild_id)

            if allowed_channel_id is None:
                # Allow if no channel set for this guild
                 return True
            elif interaction.channel_id == allowed_channel_id:
                return True # Correct channel
            else:
                # Deny if a channel IS set, but it's the wrong one
                try:
                    channel = interaction.guild.get_channel(allowed_channel_id) or await interaction.guild.fetch_channel(allowed_channel_id)
                    channel_name = channel.mention if channel else f"ID: {allowed_channel_id}"
                    await interaction.response.send_message(
                        f"❌ Please use Wordle commands in the designated channel for this server: {channel_name}",
                        ephemeral=True
                    )
                except Exception:
                     await interaction.response.send_message(
                        f"❌ Please use Wordle commands in the designated channel for this server.",
                        ephemeral=True
                    )
                return False
        # Applying the actual check decorator from app_commands
        return app_commands.check(predicate)

    # --- Helper: Check if User is Busy ---
    async def _is_user_busy(self, guild_id: int, user_id: int) -> bool:
        """Checks if the user is in ANY active game in the specified guild."""
        for game_state in self.all_games.values():
            # Check if the game is in the target guild AND the user is a player
            if game_state.get("guild_id") == guild_id and \
               user_id in game_state.get("players", []):
                logger.debug(f"User {user_id} is busy in game (MsgID Key...) in guild {guild_id}.")
                return True
        return False

    # --- Helper: Find Game for User in Channel ---
    async def _find_user_game_in_channel(self, channel_id: int, user_id: int) -> Optional[Tuple[int, Dict]]:
        """Finds the game ID and state for a user in a specific channel."""
        for game_id, game_state in self.all_games.items():
            if game_state.get("channel_id") == channel_id and \
               user_id in game_state.get("players", []):
                return game_id, game_state # Return the key (message ID) and the state
        return None, None # Not found


    # --- Wordle Game Logic ---
    def generate_feedback(self, guess: str, target: str) -> list[str]:
        """Generates the feedback emojis for a guess."""
        if len(guess) != 5 or len(target) != 5: return [NOT_IN_WORD_EMOJI] * 5
        feedback = [NOT_IN_WORD_EMOJI] * 5
        target_counts = Counter(target)
        guess_list = list(guess)
        target_list = list(target)

        # First pass: Check for correct position (green)
        for i in range(5):
            if guess_list[i] == target_list[i]:
                feedback[i] = CORRECT_SPOT_EMOJI
                target_counts[guess_list[i]] -= 1
                guess_list[i] = None # Mark as checked

        # Second pass: Check for wrong position (yellow)
        for i in range(5):
            if guess_list[i] is not None and guess_list[i] in target_counts and target_counts[guess_list[i]] > 0:
                feedback[i] = WRONG_SPOT_EMOJI
                target_counts[guess_list[i]] -= 1

        return feedback

    def calculate_points(self, num_guesses: int) -> int:
        """Calculates points based on number of guesses for solo mode."""
        if num_guesses <= 0: return 0
        points = 11 - num_guesses
        return max(0, points) # Ensure non-negative points


    def create_game_embed(self, context_obj, game_state: dict, status_message: str = None, is_multiplayer: bool = False, attach_image: bool = False) -> discord.Embed:
        """Creates the embed for the current game state. Can handle an Interaction or a User/Member object."""
        # Determine if we were passed an interaction or a user/member
        if isinstance(context_obj, Interaction):
            user = context_obj.user
            channel = context_obj.channel
        else:  # Assumes it's a User or Member object
            user = context_obj
            channel = None  # We don't have channel context from just a user object

        embed = None
        if is_multiplayer:
            players = game_state.get("players", [])
            current_turn_idx = game_state.get("current_turn_index", 0)
            current_player_id = players[current_turn_idx] if players and current_turn_idx < len(players) else None
            current_player_mention = f"<@{current_player_id}>" if current_player_id else "Unknown Player"
            channel_name = channel.name if channel else "this channel"
            title = f"Multiplayer Wordle ({channel_name})"
            description = status_message if status_message else f"It's {current_player_mention}'s turn! Guess #{len(game_state.get('guesses', [])) + 1}."
            embed = discord.Embed(title=title, description=description, color=discord.Color.purple())
            player_list_str = ", ".join(game_state.get("player_mentions", ["?"]))
            embed.add_field(name="Players", value=player_list_str if player_list_str else "None", inline=False)
            embed.set_footer(text=f"Use /guess [word] or /giveup")
        else:  # Single Player
            current_guess_num = len(game_state.get("guesses", []))
            title = f"Wordle Game for {user.display_name}"
            description = status_message if status_message else f"Guess #{current_guess_num + 1}. Good luck!"
            color = discord.Color.green() if status_message and (
                        "won" in status_message.lower() or "correct" in status_message.lower()) else discord.Color.blue()
            embed = discord.Embed(title=title, description=description, color=color)
            embed.set_footer(text=f"Use /guess [word] or guess <word>")

        if attach_image and embed:
            embed.set_image(url="attachment://wordle_board.png")
        return embed

    # --- Game Start Commands (Send initial EMBED, no image) ---
    @app_commands.command(name="wordle", description="Starts a new SOLO Wordle game.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def start_solo_wordle(self, interaction: Interaction):
        guild_id = interaction.guild_id; user_id = interaction.user.id; channel_id = interaction.channel_id

        if await self._is_user_busy(guild_id, user_id):
            await interaction.response.send_message("You are already in an active game in this server.", ephemeral=True); return

        target_word = word_fetcher.get_random_word()
        if not target_word: await interaction.response.send_message("❌ Error getting word.", ephemeral=True); return

        # Use locally defined helper
        game_state = {
            "game_type": "solo", "guild_id": guild_id, "channel_id": channel_id,
            "word": target_word, "players": [user_id], "player_mentions": [],
            "current_turn_index": 0, # Not used in solo
            "guesses": [], "results": [], "letter_states": initial_letter_states(),
            "initiator_id": user_id, "last_activity_ts": time.time()
        }

        # Send initial status embed
        embed = self.create_game_embed(interaction, game_state, "Solo game started! Make your first guess.", is_multiplayer=False, attach_image=False)
        await interaction.response.send_message(embed=embed)

        # Get the message ID and store the game state
        try:
            message = await interaction.original_response()
            self.all_games[message.id] = game_state # Use message ID as key
            logger.info(f"Started SOLO game (MsgID: {message.id}) user {user_id} guild {guild_id}. Word: {target_word}")
        except (discord.HTTPException, discord.NotFound) as e:
             logger.error(f"Failed to get original response message for solo game start: {e}")
             # Game state won't be stored if this fails. User needs to restart.
             await interaction.followup.send("Error: Could not register game state properly. Please try starting again.", ephemeral=True)


    @app_commands.command(name="multiplayer", description="Starts a turn-based multiplayer Wordle game.")
    @app_commands.describe(player2="Player 2.", player3="Opt.", player4="Opt.", player5="Opt.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def start_multiplayer_wordle(self, interaction: Interaction, player2: User, player3: User = None, player4: User = None, player5: User = None):
        guild_id=interaction.guild_id; channel_id=interaction.channel_id; initiator=interaction.user

        # Check players are not busy
        potential_players=[initiator,player2,player3,player4,player5]; players_actual=[]; player_ids=set(); busy_players=[]
        for p in potential_players:
            if p is not None and not p.bot:
                if p.id not in player_ids:
                    if await self._is_user_busy(guild_id,p.id): busy_players.append(p.mention)
                    else: players_actual.append(p); player_ids.add(p.id)
        if busy_players: await interaction.response.send_message(f"Cannot start: {', '.join(busy_players)} busy.", ephemeral=True); return
        if len(players_actual)<2: await interaction.response.send_message("Need >=2 humans.", ephemeral=True); return

        target_word=word_fetcher.get_random_word()
        if not target_word: await interaction.response.send_message("❌ Error word.", ephemeral=True); return

        # Use locally defined helper
        player_mentions = [p.mention for p in players_actual]
        game_state={
            "game_type": "multiplayer", "guild_id":guild_id,"channel_id": channel_id,
            "word":target_word,"players":[p.id for p in players_actual],
            "player_mentions": player_mentions, "current_turn_index":0,
            "guesses":[],"results":[], "letter_states":initial_letter_states(),
            "initiator_id":initiator.id, "last_activity_ts": time.time()
        }

        # Send initial status embed
        initial_status = f"Multiplayer game started by {initiator.mention}!"
        embed = self.create_game_embed(interaction, game_state, initial_status, is_multiplayer=True, attach_image=False)
        await interaction.response.send_message(embed=embed)

        # Get message ID and store game state
        try:
            message = await interaction.original_response()
            self.all_games[message.id] = game_state # Use message ID as key
            logger.info(f"Started MP game (MsgID: {message.id}) channel {channel_id} guild {guild_id}. Players: {', '.join(player_mentions)}. Word: {target_word}")
        except (discord.HTTPException, discord.NotFound) as e:
            logger.error(f"Failed to get original response message for MP game start: {e}")
            await interaction.followup.send("Error: Could not register game state properly. Please try starting again.", ephemeral=True)


    # --- Combined GUESS Command (Send Embed + File) ---
    @app_commands.command(name="guess", description="Make a guess in your active Wordle game.")
    @app_commands.describe(word="Your 5-letter guess")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def guess_wordle(self, interaction: Interaction, word: str):
        guild_id=interaction.guild_id; user_id=interaction.user.id; channel_id=interaction.channel_id

        # --- Find the user's game in this channel ---
        game_id, game_state = await self._find_user_game_in_channel(channel_id, user_id)
        if not game_state:
            await interaction.response.send_message("No active game found for you in this channel.", ephemeral=True); return

        game_type = game_state["game_type"]

        # Multiplayer turn check
        if game_type == 'multiplayer':
            current_player_id = game_state["players"][game_state["current_turn_index"]]
            if user_id != current_player_id:
                await interaction.response.send_message(f"Not your turn! Wait for <@{current_player_id}>.", ephemeral=True); return

        # Validate guess...
        guess=word.lower().strip()
        if len(guess)!=5: await interaction.response.send_message("❌ 5 letters.", ephemeral=True); return
        if not guess.isalpha(): await interaction.response.send_message("❌ Letters.", ephemeral=True); return
        if not word_fetcher.is_allowed_guess(guess): await interaction.response.send_message(f"❌ '{word.upper()}' invalid.", ephemeral=True); return
        if guess in game_state.get("guesses",[]): await interaction.response.send_message(f"❌ '{word.upper()}' guessed.", ephemeral=True); return

        await interaction.response.defer()

        # Process Guess & Update States...
        target_word = game_state["word"]; feedback = self.generate_feedback(guess, target_word)
        game_state["guesses"].append(guess); game_state["results"].append(feedback)
        current_letter_states = game_state.get("letter_states", initial_letter_states())
        for i, letter in enumerate(guess):
            if letter.isalpha():
                # Need EMOJI_TO_STATE from image_generator for this part
                new_state = EMOJI_TO_STATE.get(feedback[i], STATE_UNUSED)
                if new_state > current_letter_states.get(letter, STATE_UNUSED):
                    current_letter_states[letter] = new_state
        # No need to save back to game_state here, current_letter_states is the dict from game_state
        game_state["last_activity_ts"] = time.time()
        num_guesses_total = len(game_state["guesses"])
        status_message = ""; game_over = False; points = 0; img_buffer = None

        # Check Win/Loss & Set Status Message...
        if guess == target_word:
            game_over = True
            if game_type == 'solo':
                points = self.calculate_points(num_guesses_total)
                status_message = f"🎉 **Correct!** {interaction.user.mention} guessed `{target_word.upper()}` in {num_guesses_total} tries! Scored **{points} points**."
                await persistence.update_leaderboard(guild_id, user_id, points_earned=points)
            else: # Multiplayer win
                winner = interaction.user.mention; players = ", ".join(game_state.get("player_mentions", ["?"]))
                status_message = f"🎉 **{winner} got `{target_word.upper()}`!** Team ({players}) won in {num_guesses_total} turns!"
        else: # Game continues
            if game_type == 'solo': status_message = f"Guess #{num_guesses_total + 1}. Keep going!"
            else:
                num_players = len(game_state.get("players", [])); next_player_mention = "Next player"
                if num_players > 0:
                    game_state["current_turn_index"] = (game_state.get("current_turn_index", 0) + 1) % num_players
                    next_player_id = game_state["players"][game_state["current_turn_index"]]
                    next_player_mention = f"<@{next_player_id}>"
                status_message = f"Guess #{num_guesses_total} by {interaction.user.mention}. Now it's {next_player_mention}'s turn."

        # --- Generate Image ---
        img_buffer = image_generator.generate_wordle_image(
            game_state["guesses"],
            game_state["results"],
            game_state["letter_states"]
        )
        file = None
        if img_buffer:
            file = discord.File(fp=img_buffer, filename="wordle_board.png")
        else:
            status_message += "\n(❌ Error generating image!)"

        # --- Create Embed and Send ---
        embed = self.create_game_embed(interaction, game_state, status_message, is_multiplayer=(game_type == 'multiplayer'), attach_image=(file is not None))
        await interaction.followup.send(embed=embed, file=file)

        # Clean up if game over (use the found game_id)
        if game_over:
            if game_id in self.all_games:
                del self.all_games[game_id]
                logger.info(f"Game {game_id} ended and removed.")
            else: # Should not happen if found earlier
                 logger.warning(f"Attempted to remove ended game {game_id}, but it was already gone.")


    # --- Combined GIVEUP Command (Find game first) ---
    @app_commands.command(name="giveup", description="Forfeit your current Wordle game.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True)
    async def giveup_wordle(self, interaction: Interaction):
        guild_id = interaction.guild_id; user_id = interaction.user.id; channel_id = interaction.channel_id

        # --- Find the user's game in this channel ---
        game_id, game_state = await self._find_user_game_in_channel(channel_id, user_id)
        if not game_state:
            await interaction.response.send_message("No active game found for you in this channel to give up.", ephemeral=True); return

        game_type = game_state["game_type"]
        target_word = game_state.get("word", "UNKNOWN")

        await interaction.response.defer()

        # Remove the game from the central dictionary using its ID
        if game_id in self.all_games:
            del self.all_games[game_id]
            logger.info(f"Game {game_id} ended via giveup by user {user_id}.")
        else:
             await interaction.followup.send("Error: Could not find the game state to remove.", ephemeral=True); return

        # Process giveup message and leaderboard update
        if game_type == 'solo':
            await persistence.update_leaderboard(guild_id, user_id, points_earned=0)
            await interaction.followup.send(f"Solo game ended by {interaction.user.mention}. Word: `{target_word.upper()}`. Scored 0 points.", ephemeral=False)
        else: # Multiplayer giveup
            giver = interaction.user.mention; players = ", ".join(game_state.get("player_mentions", ["?"]))
            await interaction.followup.send(f"{giver} ended the MP game for team ({players}). Word: `{target_word.upper()}`.", ephemeral=False)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        # 2. Check if a Wordle channel is configured for this server
        allowed_channel_id = await persistence.get_guild_channel_id(message.guild.id)
        if allowed_channel_id is None:
            return  # A channel must be set for prefix-less commands to work

        # 3. Check if the message is in the designated Wordle channel
        if message.channel.id != allowed_channel_id:
            return

        # 4. Process the command
        content = message.content.lower().strip()

        # --- Handle "new wordle" ---
        if content == "new wordle" or content == "New Wordle" or content == "New wordle":
            if await self._is_user_busy(message.guild.id, message.author.id):
                await message.channel.send(f"{message.author.mention}, you are already in a game.", delete_after=10)
                return

            target_word = word_fetcher.get_random_word()
            game_state = {
                "game_type": "solo", "guild_id": message.guild.id, "channel_id": message.channel.id,
                "word": target_word, "players": [message.author.id], "guesses": [], "results": [],
                "letter_states": initial_letter_states(), "last_activity_ts": time.time()
            }
            embed = self.create_game_embed(message.author, game_state, "Solo game started! Guess with `guess <word>`.")
            response_msg = await message.channel.send(embed=embed)
            self.all_games[response_msg.id] = game_state
            logger.info(
                f"Started SOLO game (MsgID: {response_msg.id}) for user {message.author.id} via on_message. Word: {target_word}")

        # --- Handle "guess <word>" ---
        elif content.startswith("guess "):
            game_id, game_state = await self._find_user_game_in_channel(message.channel.id, message.author.id)
            if not game_state:
                await message.channel.send(f"{message.author.mention}, no active game found for you.", delete_after=10)
                return

            guess = content[6:].strip()  # Get the word after "guess "
            if len(guess) != 5 or not guess.isalpha() or not word_fetcher.is_allowed_guess(guess) or guess in \
                    game_state["guesses"]:
                await message.channel.send(f"{message.author.mention}, that's an invalid guess.", delete_after=10)
                return

            # Process the guess
            target_word = game_state["word"]
            feedback = self.generate_feedback(guess, target_word)
            game_state["guesses"].append(guess);
            game_state["results"].append(feedback)
            for i, letter in enumerate(guess):
                new_state = EMOJI_TO_STATE.get(feedback[i], STATE_UNUSED)
                if new_state > game_state["letter_states"].get(letter, STATE_UNUSED):
                    game_state["letter_states"][letter] = new_state
            game_state["last_activity_ts"] = time.time()

            num_guesses = len(game_state["guesses"])
            game_over = False;
            status_message = ""
            if guess == target_word:
                game_over = True
                points = self.calculate_points(num_guesses)
                status_message = f"🎉 **Correct!** {message.author.mention} guessed `{target_word.upper()}` in {num_guesses} tries! Scored **{points} points**."
                await persistence.update_leaderboard(message.guild.id, message.author.id, points)
            else:
                status_message = f"Guess #{num_guesses + 1}. Keep going!"

            img_buffer = image_generator.generate_wordle_image(game_state["guesses"], game_state["results"],
                                                               game_state["letter_states"])
            file = discord.File(fp=img_buffer, filename="wordle_board.png") if img_buffer else None
            embed = self.create_game_embed(message.author, game_state, status_message, attach_image=(file is not None))
            await message.channel.send(embed=embed, file=file)

            if game_over:
                if game_id in self.all_games:
                    del self.all_games[game_id]
                    logger.info(f"Game {game_id} ended and removed via on_message.")

    # --- HELP Command (No changes needed) ---
    @app_commands.command(name="wordlehelp", description="Shows instructions for the Wordle bot.")
    @app_commands.guild_only()
    async def wordle_help(self, interaction: Interaction):
        embed = discord.Embed(title="Wordle Bot Help", description="Play Solo or Multiplayer Wordle!", color=discord.Color.blue())
        embed.add_field(name="`/wordle`", value="Starts a new **Solo** game.", inline=False)
        embed.add_field(name="`/multiplayer player2 [player3...]`", value="Starts a **Multiplayer** game.", inline=False)
        embed.add_field(name="`/guess [word]`", value="Make a guess in your active game. Shows image with last 10 guesses (scrolls after 10), row numbers & keyboard.", inline=False) # Updated help text slightly
        embed.add_field(name="`/giveup`", value="Forfeit your current game.", inline=False)
        embed.add_field(name="`/leaderboard [scope]`", value="Shows Solo game rankings (Guild or Global).", inline=False)
        embed.add_field(name="Solo Scoring", value=("1 Guess: 10 Points\n...\n11+ Guesses: 0 Points"), inline=False)
        embed.add_field(name="Board Colors / Keyboard", value=("🟩 Correct spot\n🟨 Wrong spot\n⬛ Not in word\nKeyboard shows used letter status."), inline=False)
        if interaction.user.guild_permissions.manage_channels:
             embed.add_field(name="`/setchannel [channel]` (Admin Only)", value="Sets/unsets the channel for Wordle commands in this server.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(WordleGameCog(bot))