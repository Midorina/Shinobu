from __future__ import annotations

import asyncio
import json
import random
from typing import Optional, Tuple, Union

from discord.ext import commands

from models.db import MemberDB
from services import converters as cv
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import RaceError, TimedOut
from services.resources import Resources

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


class Race:
    STARTS_IN = 30
    MESSAGE_COUNTER_LIMIT = 7

    class Participant:
        def __init__(self, member_db: MemberDB, emoji: str, bet_amount: int = 0):
            self.member_db = member_db

            self.id = self.member_db.id

            self.emoji = emoji
            self.bet_amount = bet_amount

            self.progress = 0

        def add_random_progress(self):
            self.progress += random.randint(1, 10)
            if self.progress > 100:
                self.progress = 100

        def get_race_line(self):
            return f'{self.progress}%|' + '‣' * int(self.progress / 2) + self.emoji

        @property
        def has_completed(self):
            return self.progress >= 100

        def __eq__(self, other):
            return self.id == other.id

    def __init__(self, ctx: MidoContext):
        self.ctx = ctx
        self.channel_id = self.ctx.channel.id

        self.has_started = False

        self.participants = list()
        self.message_counter = 0

        self.race_loop_task = self.ctx.bot.loop.create_task(self.race_loop())

    async def give_participants_money_back(self, reason='Race cancelled.'):
        for participant in self.participants:
            if participant.bet_amount:
                await participant.member_db.user.add_cash(amount=participant.bet_amount, reason=reason)
                participant.bet_amount = 0

    async def race_loop(self):
        await asyncio.sleep(self.STARTS_IN)

        if len(self.participants) < 2:
            await self.ctx.send_error("Race could not start because there weren't enough participants.")
            await self.give_participants_money_back()
            return

        # start
        self.has_started = True
        self.ctx.bot.loop.create_task(self.count_messages())

        finished_participants = []
        e = MidoEmbed(bot=self.ctx.bot, title="Race", description='')
        msg = None
        while not self.has_ended:
            e.description = '**|**' + '🏁' * 18 + '🔚' + '**|**\n'

            for participant in self.participants:
                e.description += participant.get_race_line()

                if participant.has_completed:
                    if participant not in finished_participants:
                        finished_participants.append(participant)

                    position = finished_participants.index(participant) + 1

                    e.description += f'**#{position}**'
                    if position == 1:  # if first:
                        e.description += ' 🏆'
                e.description += '\n'

            e.description += '**|**' + '🏁' * 18 + '🔚' + '**|**\n'

            if not msg:
                msg = await self.ctx.send(embed=e)
            elif self.message_counter > self.MESSAGE_COUNTER_LIMIT:
                await msg.delete()
                msg = await self.ctx.send(embed=e)
                self.message_counter = 0
            else:
                await msg.edit(embed=e)

            if not list(filter(lambda x: not x.has_completed, self.participants)):  # if everybody finished:
                break

            for participant in self.participants:
                if participant not in finished_participants:
                    participant.add_random_progress()

            await asyncio.sleep(2.0)

        winner = finished_participants[0]
        e.description = f"The race is over!\n\n" \
                        f"The winner is: **{winner.member_db.user.discord_name}** "

        if self.prize_pool > 0:
            await winner.member_db.user.add_cash(self.prize_pool, reason="Won a race.")

            e.description += f"and they've won **{cv.readable_currency(self.prize_pool)}**!!"
        else:
            e.description += f"but they didn't get any donuts because the prize pool is empty :("

        await self.ctx.send(embed=e)  # finish

    async def count_messages(self):
        while not self.has_ended:
            m = await MidoEmbed.get_msg(bot=self.ctx.bot, ctx=self.ctx)
            if m:
                self.message_counter += 1

    def add_participant(self, member_db: MemberDB, bet_amount: int):
        p = self.get_participant(member_db.id)
        if p:
            raise RaceError(f"**You've already joined the race** as {p.emoji} "
                            f"and bet **{cv.readable_currency(p.bet_amount)}**.")

        if self.has_started:
            raise RaceError("You can't join the race as it has already started.")

        # set emoji
        used_emojis = [x.emoji for x in self.participants]
        remaining_emojis = [x for x in Resources.emotes.race_emotes if x not in used_emojis]
        if not remaining_emojis:
            raise RaceError("Race is full.")

        emoji = random.choice(remaining_emojis)

        p = self.Participant(member_db, emoji, bet_amount)
        self.participants.append(p)
        return p

    def get_participant(self, user_id: int) -> Optional[Participant]:
        try:
            return next(p for p in self.participants if p.id == user_id)
        except StopIteration:
            return None

    @property
    def prize_pool(self) -> int:
        return sum(x.bet_amount for x in self.participants)

    @property
    def has_ended(self):
        return self.race_loop_task.done()

    async def wait_until_race_finishes(self):
        await self.race_loop_task


class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.success_color = 0x15a34a
        self.fail_color = 0xee281f

        # todo: move this to db cuz its too large and might cause memory issues
        with open("resources/hangman.json") as f:
            self.hangman_dict = json.load(f)

    def get_or_create_race(self, ctx: MidoContext) -> Tuple[Race, bool]:
        """Returns a race and whether it is just created or not"""
        for race in self.bot.active_races:
            if race.has_ended:
                del race
            elif race.channel_id == ctx.channel.id:
                return race, False

        new_race = Race(ctx=ctx)
        self.bot.active_races.append(new_race)

        return new_race, True

    @commands.max_concurrency(number=1, per=commands.BucketType.channel)
    @commands.command()
    async def hangman(self, ctx: MidoContext, category: str = None):
        """Play a game of hangman!

        If you use this command without categories, a list of available categories will be shown."""
        # todo: more hangman categories
        # Pokemon -> done
        # book
        # video games
        # music (songs or albums)
        # Celebrities

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

        e.title = f"Hangman Game ({category.title()})"

        extra_msg = "A new hangman game has just started! Start typing letters and try to guess the word."
        wrong_guess = 0
        guessed_letters = []
        word_censored = ""
        for c in word:
            if c == ' ':
                word_censored += ' '
            elif c.isalnum():
                word_censored += '_'
            else:
                word_censored += c

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

            user_guess: str = user_input.content

            if len(user_guess) != 1:  # tried to guess the word or a random msg
                if user_guess.lower() == word:  # found it
                    end = True
                    update = True
                continue

            if len(user_guess) == 1:  # if letter
                if not user_guess.isalnum():  # if emoji or smth
                    continue

                update = True

                if user_guess in guessed_letters:  # already guessed
                    extra_msg = f"{user_input.author.mention}, letter `{user_guess}` has already been used. " \
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
                    extra_msg = f"{user_input.author.mention} found a letter: **{user_guess}**"

                    if '_' not in word_censored:  # all solved
                        end = True
                else:
                    wrong_guess += 1
                    e.colour = self.fail_color

                    extra_msg = f"{user_input.author.mention}, letter `{user_guess}` does not exist. Try again."

    @commands.command()
    async def race(self, ctx: MidoContext, bet_amount: Union[int, str] = 0):
        """Start or join a race!

        You can bet donuts (optional) which will be added to the prize pool. The winner will get everything!
        """
        if bet_amount:
            bet_amount = await cv.ensure_not_broke_and_parse_bet(ctx, bet_amount)

        race, just_created = self.get_or_create_race(ctx)
        try:
            participant_obj = race.add_participant(member_db=ctx.member_db, bet_amount=bet_amount)
        except RaceError as e:
            if bet_amount:  # if errored and they put a bet, give it back
                await ctx.user_db.add_cash(bet_amount, reason=f"Race errored: {e}")
            raise e

        e = MidoEmbed(bot=ctx.bot, title="Race")
        if just_created:
            e.description = f"**{ctx.author}** has successfully created a new race and joined it" \
                            f" as {participant_obj.emoji}!"
        else:
            e.description = f"**{ctx.author}** has successfully joined the race" \
                            f" as {participant_obj.emoji}!"

        if bet_amount:
            e.description += f"\n\n" \
                             f"And they've bet **{cv.readable_currency(bet_amount)}**!"

        if just_created:
            e.description += f"\n\n" \
                             f"Race starts in **{Race.STARTS_IN}** seconds."

        e.set_footer(text=f"Prize Pool: {cv.readable_bigint(race.prize_pool)} Donuts")

        await ctx.send(embed=e)

    @commands.command()
    async def raffle(self, ctx: MidoContext, *, role: cv.MidoRoleConverter() = None):
        """Prints a random online user from the server, or from the online user in the specified role."""
        role = role or ctx.guild.default_role
        role_mention = role.mention if role != ctx.guild.default_role else '@everyone'  # discord.py bug

        people = [member for member in ctx.guild.members if role in member.roles]
        random_user = random.choice(people)

        e = MidoEmbed(bot=ctx.bot,
                      title=f"🎟️ Raffle")
        e.description = f"Raffled user among {role_mention}:\n" \
                        f"\n" \
                        f"{random_user.mention}"
        e.set_footer(text=f"User's ID: {random_user.id}")

        await ctx.send(embed=e)

def setup(bot):
    bot.add_cog(Games(bot))
