from __future__ import annotations

import asyncio
import json
import random
from typing import Optional, Tuple, Union

from discord.ext import commands

import mido_utils
from models.db import HangmanWord, MemberDB

# TODO: move this to hangman.json and convert to .yml because JSON doesnt support multiline strings
HANGMAN_STAGES = ["""
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃           
 ┃          
 ┃          
╱-╲""", """
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃        😲
 ┃          
 ┃          
╱-╲""", """
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃        😲
 ┃       ╱
 ┃         
╱-╲""", """
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃        😲
 ┃       ╱┃
 ┃          
╱-╲""", """
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃        😲
 ┃       ╱┃╲
 ┃          
╱-╲""", """
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃        😲
 ┃       ╱┃╲
 ┃       ╱ 
╱-╲""", """
 ┏━━━━━━━━┓
 ┃        ╋
 ┃        ┋
 ┃        😵
 ┃       ╱┃╲
 ┃       ╱ ╲
╱-╲"""
                  ]


class Race:
    STARTS_IN = 30
    MESSAGE_COUNTER_LIMIT = 7

    class Participant:
        def __init__(self, member_db: MemberDB, emoji: str, bet_amount: int = 0):
            self.member_db = member_db

            self.id = self.member_db.id

            self.emoji = emoji

            self._bet_amount = bet_amount
            self.previous_bet = bet_amount

            self.progress = 0

        @property
        def bet_amount(self):
            return self._bet_amount

        @bet_amount.setter
        def bet_amount(self, value: int):
            self.previous_bet = self._bet_amount
            self._bet_amount = value

        def add_random_progress(self):
            self.progress += random.randint(3, 10)
            if self.progress > 100:
                self.progress = 100

        def get_race_line(self):
            return f'{self.progress}%|' + '‣' * int(self.progress / 2) + self.emoji

        @property
        def has_completed(self):
            return self.progress >= 100

        def __eq__(self, other):
            return self.id == other.id

    def __init__(self, ctx: mido_utils.Context):
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
        e = mido_utils.Embed(bot=self.ctx.bot, title="Race", description='')
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

            e.description += f"and they've won **{mido_utils.readable_currency(self.prize_pool)}**!!"
        else:
            e.description += f"but they didn't get any donuts because the prize pool is empty :("

        await self.ctx.send(embed=e)  # finish

    async def count_messages(self):
        while not self.has_ended:
            m = await mido_utils.Embed.get_msg(bot=self.ctx.bot, ctx=self.ctx)
            if m:
                self.message_counter += 1

    def add_participant(self, member_db: MemberDB, bet_amount: int) -> Tuple[Participant, bool]:
        """Add a participant to the race and returns whether the participant just increased bet or not."""
        p = self.get_participant(member_db.id)
        if p:
            # if they entered the same or less amount
            if bet_amount <= p.bet_amount:
                raise mido_utils.RaceError(
                    f"{p.emoji} **You can only increase your bet.** "
                    f"Your current bet amount is **{mido_utils.readable_currency(p.bet_amount)}**.")

            p.bet_amount = bet_amount

            return p, True
        else:
            if self.has_started:
                raise mido_utils.RaceError("You can't join the race as it has already started.")

            # set emoji
            used_emojis = [x.emoji for x in self.participants]
            remaining_emojis = [x for x in mido_utils.emotes.race_emotes if x not in used_emojis]
            if not remaining_emojis:
                raise mido_utils.RaceError("Race is full.")

            emoji = random.choice(remaining_emojis)

            p = self.Participant(member_db, emoji, bet_amount)
            self.participants.append(p)

            return p, False

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


class Games(commands.Cog, description="Play race with friends (with bets if you want) or Hangman."):
    def __init__(self, bot):
        self.bot = bot

        if not hasattr(self.bot, 'active_races'):
            self.bot.active_races = list()

        self.hangman_categories_and_word_counts = None

        self.bot.loop.create_task(self.assign_hangman_variable())

    async def assign_hangman_variable(self):
        time = mido_utils.Time()

        while not self.hangman_categories_and_word_counts:
            self.hangman_categories_and_word_counts = await HangmanWord.get_categories_and_counts(self.bot)

            if sum(x for x in self.hangman_categories_and_word_counts.values()) == 0:
                # if we dont have any words, it means the table is freshly created
                # in that case, insert from hangman.json
                await self._insert_from_json()
                self.hangman_categories_and_word_counts = None

        self.bot.logger.debug("Assigning hangman variables took:\t" + time.passed_seconds_in_float_formatted)

    async def _insert_from_json(self):
        self.bot.logger.info("Hangman words were not in our database. Inserting from hangman.json...")

        with open('resources/hangman.json', encoding='utf8') as f:
            words = json.load(f)

            for category, words in words.items():
                await HangmanWord.add_words(self.bot, category, words)

    def get_or_create_race(self, ctx: mido_utils.Context) -> Tuple[Race, bool]:
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
    async def hangman(self, ctx: mido_utils.Context, category: str = None):
        """Play a game of hangman!

        If you use this command without categories, a list of available categories will be shown."""
        # todo: more hangman categories
        # Pokemon -> done
        # book
        # video games
        # music (songs or albums)
        # Celebrities

        e = mido_utils.Embed(bot=ctx.bot)

        if not category:
            e.title = "Hangman Categories"
            e.description = ""
            for category, word_count in self.hangman_categories_and_word_counts.items():
                e.description += f"- **{category.title()}** (**{word_count}** Words)\n"

            e.description += f"\nType `{ctx.prefix}hangman <category_name>` to start a Hangman game.\n" \
                             f"Type `{ctx.prefix}hangman random` to start a Hangman game with a random category."

            return await ctx.send(embed=e)

        category = category.lower()
        if category not in self.hangman_categories_and_word_counts.keys() and category != 'random':
            raise commands.BadArgument("Invalid Hangman category!")

        if category == 'random':
            category = random.choice(list(self.hangman_categories_and_word_counts.keys()))

        word: str = (await HangmanWord.get_random_word(bot=ctx.bot, category=category)).word

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
                e.colour = mido_utils.Color.fail()
                update = True
                end = True
            else:
                if end is True:  # if not hung but end is requested = won
                    extra_msg = f"Congratulations!! You found the word: **{word.title()}**"
                    word_censored = word
                    e.colour = mido_utils.Color.success()
                    update = True

            if update is True:
                update = False
                e.description = f"{extra_msg}\n" \
                                f"\n" \
                                f"`{' '.join(word_censored)}`\n\n" \
                                f"```{HANGMAN_STAGES[wrong_guess]}```"

                e.set_footer(text=" ".join(guessed_letters))

                await ctx.send(embed=e)
                if end is True:
                    return

            user_input = await mido_utils.Embed.get_msg(bot=ctx.bot,
                                                        ctx=ctx,
                                                        author_id=None,  # everyone
                                                        timeout=180)
            if not user_input:
                raise mido_utils.TimedOut(f"No one tried to solve the last Hangman game, so its shut down. "
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
                    e.colour = mido_utils.Color.fail()
                    update = True
                    continue

                guessed_letters.append(user_guess)

                if user_guess in word:
                    for i, c in enumerate(word):  # update the censored word
                        if c == user_guess:
                            word_censored = word_censored[:i] + c + word_censored[i + 1:]

                    e.colour = mido_utils.Color.success()
                    extra_msg = f"{user_input.author.mention} found a letter: **{user_guess}**"

                    if '_' not in word_censored:  # all solved
                        end = True
                else:
                    wrong_guess += 1
                    e.colour = mido_utils.Color.fail()

                    extra_msg = f"{user_input.author.mention}, letter `{user_guess}` does not exist. Try again."

    @commands.command()
    @commands.guild_only()
    async def race(self, ctx: mido_utils.Context, bet_amount: Union[mido_utils.Int64, str] = 0):
        """Start or join a race!

        You can bet donuts (optional) which will be added to the prize pool. The winner will get everything!
        """
        if bet_amount:
            bet_amount = await mido_utils.ensure_not_broke_and_parse_bet(ctx, bet_amount)

        race, just_created = self.get_or_create_race(ctx)

        try:
            participant_obj, increased_bet = race.add_participant(member_db=ctx.member_db, bet_amount=bet_amount)
        except mido_utils.RaceError as e:
            if bet_amount:  # if errored and they put a bet, give it back
                await ctx.user_db.add_cash(bet_amount, reason=f"Race errored: {e}")
            raise e

        e = mido_utils.Embed(bot=ctx.bot, title="Race")

        if increased_bet:
            # give back their previous bet
            await ctx.user_db.add_cash(participant_obj.previous_bet, reason="Giving back the previous bet on the race.")

            e.description = f"**{participant_obj.emoji} {ctx.author}** increased their bet " \
                            f"from **{mido_utils.readable_currency(participant_obj.previous_bet)}** " \
                            f"to **{mido_utils.readable_currency(bet_amount)}**!"
        else:
            if just_created:
                e.description = f"**{ctx.author}** has successfully created a new race and joined it" \
                                f" as {participant_obj.emoji}!"
            else:
                e.description = f"**{ctx.author}** has successfully joined the race" \
                                f" as {participant_obj.emoji}!"

            if bet_amount:
                e.description += f"\n\n" \
                                 f"And they've bet **{mido_utils.readable_currency(bet_amount)}**!"

            if just_created:
                e.description += f"\n\n" \
                                 f"Race starts in **{Race.STARTS_IN}** seconds.\n\n" \
                                 f"*You can join this race by typing `{ctx.prefix}race [bet_amount]`*"

        e.set_footer(text=f"Prize Pool: {mido_utils.readable_bigint(race.prize_pool)} Donuts")

        await ctx.send(embed=e)

    @commands.command()
    @commands.guild_only()
    async def raffle(self, ctx: mido_utils.Context, *, role: mido_utils.RoleConverter() = None):
        """Prints a random online user from the server, or from the online user in the specified role."""
        role = role or ctx.guild.default_role
        role_mention = role.mention if role != ctx.guild.default_role else '@everyone'  # discord.py bug

        people = [member for member in ctx.guild.members if role in member.roles]
        random_user = random.choice(people)

        e = mido_utils.Embed(bot=ctx.bot,
                             title=f"🎟️ Raffle")
        e.description = f"Raffled user among {role_mention}:\n" \
                        f"\n" \
                        f"{random_user.mention}"
        e.set_footer(text=f"User's ID: {random_user.id}")

        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(Games(bot))
