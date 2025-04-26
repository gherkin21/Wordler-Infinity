# cogs/wordle_game.py

import discord
from discord.ext import commands
from discord import app_commands, Interaction, User # Import User type hint
import logging
from collections import Counter
import io
from typing import List # For type hinting user list

# Use updated persistence
from utils import word_fetcher, persistence, image_generator

logger = logging.getLogger(__name__)

# Emojis - Remain the same
CORRECT_SPOT_EMOJI = "🟩"
WRONG_SPOT_EMOJI = "🟨"
NOT_IN_WORD_EMOJI = "⬜"

class WordleGameCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Single-player games: { (guild_id, user_id): state }
        self.active_games = {}
        # Multiplayer games: { channel_id: state } - Simplification: 1 MP game per channel
        self.multiplayer_games = {}
        # No local config storage needed

    async def cog_load(self):
        logger.info("WordleGameCog loaded.")
        # Clean up any potentially stale multiplayer games on load? Or assume they died with the bot process.
        self.multiplayer_games = {}

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
                # Allow if no channel is set for this guild (based on allow_anywhere_if_not_set flag)
                 return allow_anywhere_if_not_set # True if allowed anywhere when not set, False otherwise
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
        """Checks if the user is in any active game (solo or MP) in the specified guild."""
        # Check solo games
        solo_key = (guild_id, user_id)
        if solo_key in self.active_games:
            logger.debug(f"User {user_id} is busy in a solo game in guild {guild_id}.")
            return True

        # Check multiplayer games in this guild
        for channel_id, mp_game_state in self.multiplayer_games.items():
            # Check if this MP game belongs to the target guild
            if mp_game_state.get("guild_id") == guild_id:
                # Check if the user is a player in this game
                if user_id in mp_game_state.get("players", []):
                    logger.debug(f"User {user_id} is busy in a multiplayer game (Channel {channel_id}) in guild {guild_id}.")
                    return True

        # User is not found in any active game in this guild
        return False

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

    # --- Embed Creation ---
    def create_game_embed(self, interaction: Interaction, game_state: dict, status_message: str = None, is_multiplayer: bool = False) -> discord.Embed:
        """Creates the embed for the current game state."""
        if is_multiplayer:
            players = game_state.get("players", [])
            current_turn_idx = game_state.get("current_turn_index", 0)
            current_player_id = players[current_turn_idx] if players and current_turn_idx < len(players) else None
            current_player_mention = f"<@{current_player_id}>" if current_player_id else "Unknown Player"
            channel_name = interaction.channel.name if interaction.channel else "this channel"

            title = f"Multiplayer Wordle Game! ({channel_name})"
            description = status_message if status_message else f"It's {current_player_mention}'s turn! Guess #{len(game_state.get('guesses', [])) + 1}."
            embed = discord.Embed(title=title, description=description, color=discord.Color.purple())
            player_list_str = ", ".join([f"<@{pid}>" for pid in players])
            embed.add_field(name="Players", value=player_list_str if player_list_str else "None", inline=False)
            embed.set_footer(text=f"Type /guess [word] when it's your turn, or /giveup to end.")

        else: # Single Player
            user = interaction.user
            current_guess_num = len(game_state.get("guesses", []))
            title = f"Wordle Game for {user.display_name}"
            description = status_message if status_message else f"Guess #{current_guess_num + 1}. Good luck!"
            embed = discord.Embed(
                title=title, description=description,
                color=discord.Color.green() if status_message and ("won" in status_message.lower() or "congratulations" in status_message.lower()) else discord.Color.blue()
            )
            embed.set_footer(text=f"Current Guess: #{current_guess_num + 1} | Type /guess [word] or /giveup")

        # Common part: Attach the image reference
        embed.set_image(url="attachment://wordle_board.png")
        return embed

    # --- Commands ---

    # SOLO Game Start
    @app_commands.command(name="wordle", description="Starts a new SOLO Wordle game.")
    @check_guild_and_channel(allow_anywhere_if_not_set=True) # Allow starting SP anywhere if channel not set
    async def start_solo_wordle(self, interaction: Interaction):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        game_key = (guild_id, user_id)
        channel_id = interaction.channel_id # For checking multiplayer game

        # Check if user is busy in ANY game in this guild
        if await self._is_user_busy(guild_id, user_id):
            await interaction.response.send_message("You are already in an active Wordle game (Solo or Multiplayer) in this server. Finish or `/giveup` first.", ephemeral=True)
            return

        # Original check for MP game in the specific channel (still useful to prevent direct channel conflict)
        if channel_id in self.multiplayer_games:
             await interaction.response.send_message("A multiplayer game is active in this channel. Cannot start a solo game here.", ephemeral=True); return

        target_word = word_fetcher.get_random_word()
        if not target_word: await interaction.response.send_message("❌ Error getting word.", ephemeral=True); return

        game_state = {"word": target_word, "guesses": [], "results": []}
        self.active_games[game_key] = game_state

        img_buffer = image_generator.generate_wordle_image([], [])
        if not img_buffer:
            await interaction.response.send_message("❌ Error generating board image.", ephemeral=True)
            if game_key in self.active_games: del self.active_games[game_key]
            return

        file = discord.File(fp=img_buffer, filename="wordle_board.png")
        embed = self.create_game_embed(interaction, game_state, "Solo game started!", is_multiplayer=False)
        await interaction.response.send_message(embed=embed, file=file)
        logger.info(f"Started SOLO Wordle game for user {user_id} in guild {guild_id}. Word: {target_word}")

    # MULTIPLAYER Game Start
    @app_commands.command(name="multiplayer", description="Starts a turn-based multiplayer Wordle game.")
    @app_commands.describe(player2="The second player.", player3="The third player (optional).", player4="The fourth player (optional).", player5="The fifth player (optional).")
    @check_guild_and_channel(allow_anywhere_if_not_set=True) # Allow starting MP anywhere if channel not set
    async def start_multiplayer_wordle(self, interaction: Interaction, player2: User, player3: User = None, player4: User = None, player5: User = None):
        guild_id = interaction.guild_id
        channel_id = interaction.channel_id
        initiator = interaction.user

        # --- Validation ---
        if channel_id in self.multiplayer_games:
            await interaction.response.send_message("A multiplayer Wordle game is already running in this channel.", ephemeral=True); return

        potential_players = [initiator, player2, player3, player4, player5]
        players_actual = []
        player_ids = set()
        busy_players = [] # Keep track of players who are already busy

        # Check potential players
        for p in potential_players:
            if p is not None and not p.bot:
                if p.id not in player_ids: # Check for duplicate *before* busy check
                    # Check if this player is busy in this guild
                    if await self._is_user_busy(guild_id, p.id):
                        busy_players.append(p.mention)
                    else:
                        # Only add if not busy and not already added
                        players_actual.append(p)
                        player_ids.add(p.id)
                # If duplicate, we just ignore them silently

        # Report if any players were busy
        if busy_players:
            is_are = "is" if len(busy_players) == 1 else "are"
            busy_list_str = ", ".join(busy_players)
            await interaction.response.send_message(f"Cannot start game: {busy_list_str} {is_are} already in another Wordle game in this server.", ephemeral=True)
            return

        if len(players_actual) < 2:
            await interaction.response.send_message("You need at least two unique, available human players.", ephemeral=True); return

        # --- Setup Game ---
        target_word = word_fetcher.get_random_word()
        if not target_word: await interaction.response.send_message("❌ Error getting word.", ephemeral=True); return

        game_state = {
            "guild_id": guild_id, # Store guild ID for busy check context
            "word": target_word,
            "players": [p.id for p in players_actual], # Store IDs
            "player_mentions": [p.mention for p in players_actual], # For display
            "current_turn_index": 0,
            "guesses": [],
            "results": [],
            "message_id": None, # Store the message ID to potentially edit or refer to
            "initiator_id": initiator.id
        }
        self.multiplayer_games[channel_id] = game_state

        # --- Send Initial Message ---
        img_buffer = image_generator.generate_wordle_image([], [])
        if not img_buffer:
            await interaction.response.send_message("❌ Error generating board image.", ephemeral=True)
            if channel_id in self.multiplayer_games: del self.multiplayer_games[channel_id]
            return

        file = discord.File(fp=img_buffer, filename="wordle_board.png")
        initial_status = f"Multiplayer game started by {initiator.mention}!"
        embed = self.create_game_embed(interaction, game_state, initial_status, is_multiplayer=True)

        await interaction.response.send_message(embed=embed, file=file)
        try:
            message = await interaction.original_response()
            self.multiplayer_games[channel_id]["message_id"] = message.id # Store message ID
        except (discord.HTTPException, discord.NotFound) as e:
             logger.warning(f"Could not get original response message for MP game in {channel_id}: {e}")


        player_mentions_str = ", ".join(game_state["player_mentions"])
        logger.info(f"Started MULTIPLAYER Wordle game in channel {channel_id} (Guild {guild_id}). Players: {player_mentions_str}. Word: {target_word}")

    # Combined GUESS Command
    @app_commands.command(name="guess", description="Make a guess in your active Wordle game (Solo or Multiplayer).")
    @app_commands.describe(word="Your 5-letter guess")
    @check_guild_and_channel(allow_anywhere_if_not_set=True) # Allow guess if channel not set (game must exist though)
    async def guess_wordle(self, interaction: Interaction, word: str):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        channel_id = interaction.channel_id
        solo_game_key = (guild_id, user_id)

        game_state = None
        game_type = None # 'solo' or 'multiplayer'

        # --- Determine Game Type and State ---
        if solo_game_key in self.active_games:
            # Check if a MP game isn't ALSO running in this channel (avoid confusion)
            if channel_id in self.multiplayer_games:
                 await interaction.response.send_message("A multiplayer game is active in this channel. Cannot guess in your solo game here.", ephemeral=True); return
            game_state = self.active_games[solo_game_key]
            game_type = 'solo'
        elif channel_id in self.multiplayer_games:
            game_state = self.multiplayer_games[channel_id]
            game_type = 'multiplayer'
            # Check if user is part of this MP game
            if user_id not in game_state["players"]:
                 await interaction.response.send_message("You are not part of the multiplayer game in this channel.", ephemeral=True); return
            # Check if it's the user's turn
            current_player_id = game_state["players"][game_state["current_turn_index"]]
            if user_id != current_player_id:
                 await interaction.response.send_message(f"It's not your turn! Wait for <@{current_player_id}>.", ephemeral=True); return
        else:
            await interaction.response.send_message("No active Wordle game found for you (Solo or Multiplayer in this channel). Use `/wordle` or `/multiplayer`.", ephemeral=True); return

        # --- Input Validation ---
        guess = word.lower().strip()
        if len(guess) != 5: await interaction.response.send_message(f"❌ Guess must be 5 letters.", ephemeral=True); return
        if not guess.isalpha(): await interaction.response.send_message(f"❌ Guess must be letters only.", ephemeral=True); return
        if not word_fetcher.is_allowed_guess(guess): await interaction.response.send_message(f"❌ '{word.upper()}' not in word list.", ephemeral=True); return
        # Check guesses within the specific game state
        if guess in game_state.get("guesses", []):
            await interaction.response.send_message(f"❌ '{word.upper()}' was already guessed in this game.", ephemeral=True); return

        # --- Process Guess ---
        target_word = game_state["word"]
        feedback = self.generate_feedback(guess, target_word)
        game_state["guesses"].append(guess)
        game_state["results"].append(feedback)

        num_guesses_total = len(game_state["guesses"]) # Total guesses in the game
        status_message = ""
        game_over = False
        points = 0

        # --- Check Win Condition ---
        if guess == target_word:
            game_over = True
            if game_type == 'solo':
                points = self.calculate_points(num_guesses_total)
                status_message = f"🎉 Congratulations! You guessed `{target_word.upper()}` in {num_guesses_total} tries! Scored {points} points."
                await persistence.update_leaderboard(guild_id, user_id, points_earned=points)
                logger.info(f"User {user_id} in guild {guild_id} won SOLO. Guesses: {num_guesses_total}, Points: {points}")
            else: # Multiplayer win
                winner_mention = interaction.user.mention
                player_mentions = ", ".join([f"<@{pid}>" for pid in game_state.get("players", [])])
                status_message = f"🎉 {winner_mention} guessed the word `{target_word.upper()}`! The team ({player_mentions}) won in {num_guesses_total} total turns!"
                # No leaderboard update for multiplayer wins in this version
                logger.info(f"MULTIPLAYER game in channel {channel_id} won by user {user_id}. Total Guesses: {num_guesses_total}")
        else:
            # Game continues
            if game_type == 'solo':
                 status_message = f"Guess #{num_guesses_total + 1}. Keep going!"
            else: # Multiplayer turn change
                # Advance turn safely
                num_players = len(game_state.get("players", []))
                if num_players > 0:
                    game_state["current_turn_index"] = (game_state.get("current_turn_index", 0) + 1) % num_players
                    next_player_id = game_state["players"][game_state["current_turn_index"]]
                    status_message = f"Nice guess! Now it's <@{next_player_id}>'s turn (Guess #{num_guesses_total + 1})."
                else: # Should not happen if game started correctly
                    status_message = "Error: No players found in multiplayer game."
                    logger.error(f"Multiplayer game in channel {channel_id} has no players during turn advance.")

        # --- Generate and Send Updated Image ---
        img_buffer = image_generator.generate_wordle_image(game_state["guesses"], game_state["results"])
        file = None
        if img_buffer:
            file = discord.File(fp=img_buffer, filename="wordle_board.png")
        else:
            status_message += " (Image failed to generate)" # Append error if image fails

        embed = self.create_game_embed(interaction, game_state, status_message, is_multiplayer=(game_type == 'multiplayer'))

        # Respond to the interaction - sends a *new* message
        await interaction.response.send_message(embed=embed, file=file)

        # --- Clean up game state if over ---
        if game_over:
            if game_type == 'solo':
                if solo_game_key in self.active_games: del self.active_games[solo_game_key]
            else: # Multiplayer
                if channel_id in self.multiplayer_games: del self.multiplayer_games[channel_id]

    # Combined GIVEUP Command
    @app_commands.command(name="giveup", description="Forfeit your current Wordle game (Solo or Multiplayer).")
    @check_guild_and_channel(allow_anywhere_if_not_set=True) # Allow giveup if channel not set
    async def giveup_wordle(self, interaction: Interaction):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        channel_id = interaction.channel_id
        solo_game_key = (guild_id, user_id)

        game_state = None
        game_type = None

        # --- Find Game ---
        if solo_game_key in self.active_games:
            if channel_id in self.multiplayer_games: # Prevent conflict
                 await interaction.response.send_message("A multiplayer game is active in this channel. Cannot give up solo game here.", ephemeral=True); return
            game_state = self.active_games[solo_game_key]
            game_type = 'solo'
        elif channel_id in self.multiplayer_games:
            game_state = self.multiplayer_games[channel_id]
            game_type = 'multiplayer'
            # Check if user is part of this MP game
            if user_id not in game_state.get("players", []):
                 await interaction.response.send_message("You are not part of the multiplayer game in this channel.", ephemeral=True); return
        else:
            await interaction.response.send_message("No active Wordle game found to give up.", ephemeral=True); return

        target_word = game_state.get("word", "UNKNOWN") # Safely get word

        # --- Process Giveup ---
        if game_type == 'solo':
            # Update leaderboard: game played, 0 points
            await persistence.update_leaderboard(guild_id, user_id, points_earned=0)
            del self.active_games[solo_game_key]
            logger.info(f"User {user_id} in guild {guild_id} gave up SOLO game. Word: {target_word}")
            await interaction.response.send_message(f"Solo game ended. The word was `{target_word.upper()}`. Scored 0 points.", ephemeral=False)
        else: # Multiplayer giveup
            giver_upper_mention = interaction.user.mention
            player_mentions = ", ".join([f"<@{pid}>" for pid in game_state.get("players", [])])
            # Remove the game state
            if channel_id in self.multiplayer_games:
                del self.multiplayer_games[channel_id]
            else: # Should not happen if check above passed, but good practice
                 logger.warning(f"Attempted to give up MP game in channel {channel_id}, but it was already gone.")
                 await interaction.response.send_message("The multiplayer game seems to have already ended.", ephemeral=True)
                 return

            logger.info(f"User {user_id} gave up MULTIPLAYER game in channel {channel_id}. Word: {target_word}")
            await interaction.response.send_message(f"{giver_upper_mention} ended the multiplayer game for the team ({player_mentions}). The word was `{target_word.upper()}`.", ephemeral=False)

    # HELP Command
    @app_commands.command(name="wordlehelp", description="Shows instructions for the Wordle bot.")
    @app_commands.guild_only() # Help probably only makes sense in a guild context anyway
    async def wordle_help(self, interaction: Interaction):
        embed = discord.Embed(title="Wordle Bot Help", description="Play Solo or Multiplayer Wordle!", color=discord.Color.blue())
        embed.add_field(name="`/wordle`", value="Starts a new **Solo** game.", inline=False)
        embed.add_field(name="`/multiplayer player2 [player3...]`", value="Starts a **Multiplayer** game with mentioned users (up to 5 total).", inline=False)
        embed.add_field(name="`/guess [word]`", value="Make a 5-letter guess in your active game (works for both modes).", inline=False)
        embed.add_field(name="`/giveup`", value="Forfeit your current game (ends the game for everyone in Multiplayer).", inline=False)
        embed.add_field(name="`/leaderboard [scope]`", value="Shows Solo game rankings (Guild or Global). MP games don't affect score yet.", inline=False)
        embed.add_field(name="Solo Scoring", value=("1 Guess: 10 Points\n...\n10 Guesses: 1 Point\n11+ Guesses: 0 Points"), inline=False)
        embed.add_field(name="Board Colors", value=("🟩 Correct spot\n🟨 Wrong spot\n⬛ Not in word"), inline=False)
        # Add admin command info if user has perms in this guild
        if interaction.user.guild_permissions.manage_channels:
             embed.add_field(name="`/setchannel [channel]` (Admin Only)", value="Sets/unsets the specific channel for Wordle commands in *this* server.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    # No config needed here, handled by persistence module
    await bot.add_cog(WordleGameCog(bot))