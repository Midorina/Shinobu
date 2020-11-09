import json
import random

from discord.ext import commands

from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import TimedOut

HANGMAN_STAGES = [
    """. ┌─────┐
.┃...............┋
.┃...............┋
.┃
.┃
.┃
/-\\""",
    """. ┌─────┐
    .┃...............┋
    .┃...............┋
    .┃..............:astonished:
    .┃
    .┃
    /-\\""",
    """. ┌─────┐
    .┃...............┋
    .┃...............┋
    .┃..............:astonished:
    .┃............./
    .┃
    /-\\""",
    """. ┌─────┐
.┃...............┋
.┃...............┋
.┃..............:astonished:
.┃............./ |
.┃
/-\\""",
    """. ┌─────┐
.┃...............┋
.┃...............┋
.┃..............:astonished:
.┃............./ | \\
.┃
/-\\""",
    """. ┌─────┐
.┃...............┋
.┃...............┋
.┃..............:astonished:
.┃............./ | \\
.┃............../
/-\\""",
    """. ┌─────┐
.┃...............┋
.┃...............┋
.┃..............:astonished:
.┃............./ | \\
.┃............../ \\
/-\\""",
    """"""
]


class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.success_color = 0x15a34a
        self.fail_color = 0xee281f

        # todo: move this to db cuz its too large and might cause memory issues
        with open("resources/hangman.json") as f:
            self.hangman_dict = json.load(f)

    @commands.max_concurrency(number=1, per=commands.BucketType.channel)
    @commands.command()
    async def hangman(self, ctx: MidoContext, category: str = None):
        """Play a game of hangman!

        If you use this command without categories, a list of available categories will be shown."""
        # todo: more hangman categories

        e = MidoEmbed(bot=ctx.bot)

        if not category:
            e.title = "Hangman Categories"

            e.description = ""
            for category, words in self.hangman_dict.items():
                e.description += f"- **{category.title()}** (**{len(words)}** Words)\n"

            e.description += f"\nType `{ctx.prefix}hangman <category_name>` to start a Hangman game.\n" \
                             f"Type `{ctx.prefix}hangman random` to start a Hangman game with a random category."

            return await ctx.send(embed=e)

        category = category.lower()
        if category not in self.hangman_dict.keys() and category != 'random':
            raise commands.BadArgument("Invalid Hangman category!")

        if category == 'random':
            category = random.choice(list(self.hangman_dict.keys()))

        word: str = random.choice(self.hangman_dict[category]).lower()

        print(word)

        e.title = f"Hangman Game ({category.title()})"

        extra_msg = "A new hangman game has just started! Start typing letters and try to guess the word."
        wrong_guess = 0
        guessed_letters = []
        word_censored = ''.join('_' if c.isalnum() else ' ' for c in word)

        end = False

        update = True
        while True:
            if wrong_guess >= 6:  # if the man is hung
                extra_msg = f"Game over. You lost. It was: **{word.title()}**"
                e.colour = self.fail_color
                update = True
                end = True
            else:
                if end is True:  # if not hung but end is requested = won
                    extra_msg = f"Congratulations!! You found the word: **{word.title()}**"
                    word_censored = word
                    e.colour = self.success_color
                    update = True

            if update is True:
                update = False
                e.description = f"{extra_msg}\n" \
                                f"\n" \
                                f"`{' '.join(word_censored)}`\n" \
                                f"{HANGMAN_STAGES[wrong_guess]}"

                e.set_footer(text=" ".join(guessed_letters))

                await ctx.send(embed=e)
                if end is True:
                    return

            user_input = await MidoEmbed.get_msg(bot=ctx.bot,
                                                 ctx=ctx,
                                                 author_id=None,  # everyone
                                                 timeout=180)
            if not user_input:
                raise TimedOut(f"No one tried to solve the last Hangman game, so its shut down."
                               f"You can start a new game by typing `{ctx.prefix}hangman`.")

            user_guess = user_input.content

            if len(user_guess) != 1:  # tried to guess the word or a random msg
                if user_guess.lower() == word:  # found it
                    end = True
                    update = True
                continue

            if len(user_guess) == 1:  # if letter
                update = True

                if user_guess in guessed_letters:  # already guessed
                    extra_msg = f"{ctx.author.mention}, letter `{user_guess}` has already been used. " \
                                f"Try a different letter."
                    e.colour = self.fail_color
                    update = True
                    continue

                guessed_letters.append(user_guess)

                if user_guess in word:
                    for i, c in enumerate(word):  # update the censored word
                        if c == user_guess:
                            word_censored = word_censored[:i] + c + word_censored[i + 1:]

                    e.colour = self.success_color
                    extra_msg = f"{ctx.author.mention} found a letter: **{user_guess}**"

                    if '_' not in word_censored:  # all solved
                        end = True
                else:
                    wrong_guess += 1
                    e.colour = self.fail_color

                    extra_msg = f"{ctx.author.mention}, letter `{user_guess}` does not exist. Try again."


def setup(bot):
    bot.add_cog(Games(bot))
