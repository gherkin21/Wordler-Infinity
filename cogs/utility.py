import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import logging
import datetime

import asyncio
import time
import random
import io
from typing import Dict, List, Tuple

from utils.image_generator import generate_wordle_image
from utils.image_generator import EMOJI_TO_STATE, STATE_UNUSED

logger = logging.getLogger(__name__)

def initial_letter_states() -> Dict[str, int]:
    """Creates the initial dictionary mapping 'a'-'z' to STATE_UNUSED."""
    return {chr(ord('a') + i): STATE_UNUSED for i in range(26)}

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        logger.info(f"Cog loaded: {__name__}")

    @app_commands.command(name="contact", description="Sends a message to the bot owner(s).")
    @app_commands.describe(message="The message you want to send.")
    async def contact_owner(self, interaction: Interaction, message: str):
        owner_ids = [334365988697014273]


        if not owner_ids:
            logger.error("Bot owner ID(s) not found in bot application info.")
            await interaction.response.send_message(
                "❌ Sorry, I couldn't identify the bot owner to send the message.",
                ephemeral=True
            )
            return

        embed = Embed(
            title="📬 Bot Contact Message",
            description=message,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(
            name=f"{interaction.user.name} ({interaction.user.id})",
            icon_url=interaction.user.display_avatar.url
        )

        origin = "Direct Message"
        if interaction.guild and interaction.channel:
            origin = f"Server: {interaction.guild.name} ({interaction.guild.id})\nChannel: #{interaction.channel.name} ({interaction.channel.id})"
        elif interaction.guild:
             origin = f"Server: {interaction.guild.name} ({interaction.guild.id})"

        embed.add_field(name="Origin", value=origin, inline=False)

        success_count = 0
        fail_count = 0

        for owner_id in owner_ids:
             if owner_id is None:
                 continue
             try:
                owner_user = self.bot.get_user(owner_id) or await self.bot.fetch_user(owner_id)
                if owner_user:
                    await owner_user.send(embed=embed)
                    success_count += 1
                    logger.info(f"Contact message sent to owner {owner_id} from user {interaction.user.id}")
                else:
                     logger.warning(f"Could not find owner user object for ID: {owner_id}")
                     fail_count += 1
             except discord.NotFound:
                logger.warning(f"Owner user ID {owner_id} not found.")
                fail_count += 1
             except discord.Forbidden:
                logger.warning(f"Cannot send DM to owner {owner_id} (Forbidden - DMs closed or bot blocked?).")
                fail_count += 1
             except Exception as e:
                logger.error(f"Failed to send contact message to owner {owner_id}: {e}")
                fail_count += 1

        if success_count > 0:
            await interaction.response.send_message(
                f"✅ Your message has been sent to the bot owner(s).",
                ephemeral=True
            )
        else:
             await interaction.response.send_message(
                f"❌ Sorry, I could not deliver your message to any bot owner(s). Please try again later or find another contact method.",
                ephemeral=True
            )

    @commands.command(name="simload", hidden=True)
    @commands.is_owner()
    async def simulate_load(self, ctx: commands.Context, num_tasks: int = 100):
        """Simulates concurrent processing of generate_wordle_image. Owner only."""
        if num_tasks <= 0: await ctx.send("Number of tasks must be positive."); return

        await ctx.send(f"Starting simulation: {num_tasks} concurrent image generations...")
        logger.info(f"SIMLOAD: Starting simulation for {num_tasks} tasks.")

        tasks = []
        for i in range(num_tasks):
            if i < num_tasks * 0.6:
                num_guesses = random.randint(1, 6)
            elif i < num_tasks * 0.9:
                num_guesses = random.randint(7, 10)
            else:
                num_guesses = random.randint(11, 15)
            fake_guesses = ["ARISE", "CLOUD", "PAINT", "STEAK", "BRICK", "PLUMB", "FANCY", "GHOST", "WHIRL",
                            "MAGIC", "JUMPY", "BLITZ", "VIXEN", "QUERY", "ZEBRA"][:num_guesses]
            fake_results = []
            task_letter_states = initial_letter_states()
            for r_idx in range(num_guesses):
                guess_word = fake_guesses[r_idx].lower()
                result_row = random.choices(["🟩", "🟨", "⬜"], k=5)
                if r_idx == num_guesses - 1 and random.random() < 0.1: result_row = ["🟩"] * 5
                fake_results.append(result_row)
                for c_idx, letter in enumerate(guess_word):
                    if c_idx < len(result_row):
                        new_state = EMOJI_TO_STATE.get(result_row[c_idx], STATE_UNUSED)
                        if new_state > task_letter_states.get(letter, STATE_UNUSED):
                            task_letter_states[letter] = new_state
            coro = self._run_image_generation_in_executor(fake_guesses, fake_results, task_letter_states, i)
            tasks.append(coro)

        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.perf_counter()

        total_time = (end_time - start_time) * 1000
        success_count = sum(1 for r in results if isinstance(r, io.BytesIO))
        fail_count = num_tasks - success_count
        avg_time_per_task = total_time / num_tasks if num_tasks > 0 else 0
        result_message = (
            f"Simulation complete for {num_tasks} tasks.\nTotal time: {total_time:.2f} ms ({avg_time_per_task:.2f} ms/task avg)\nSuccessful: {success_count}\nFailed: {fail_count}")
        logger.info(f"SIMLOAD: {result_message}")
        await ctx.send(result_message)
        for i, res in enumerate(results):
            if not isinstance(res, io.BytesIO): logger.error(f"SIMLOAD: Task {i} failed: {res}")

    async def _run_image_generation_in_executor(self, guesses, results, letter_states, task_id):
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, generate_wordle_image, guesses, results, letter_states)
            return result
        except Exception as e:
            logger.error(f"SIMLOAD: Exception in executor task {task_id}: {e}"); return e


async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCog(bot))