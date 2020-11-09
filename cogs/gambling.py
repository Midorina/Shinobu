import math
import random
from typing import Union

import dbl
import discord
from discord.ext import commands

from midobot import MidoBot
from models.db import UserDB
from services import checks
from services.context import MidoContext
from services.converters import MidoMemberConverter
from services.embed import MidoEmbed
from services.exceptions import APIError, DidntVoteError, InsufficientCash, OnCooldownError
from services.resources import Resources

DIGIT_TO_EMOJI = {
    0: ":zero:",
    1: ":one:",
    2: ":two:",
    3: ":three:",
    4: ":four:",
    5: ":five:",
    6: ":six:",
    7: ":seven:",
    8: ":eight:",
    9: ":nine:"
}


class Gambling(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        # general gambling variables
        self.success_color = 0x00ff00
        self.fail_color = 0xff0000

        # coin variables
        self.coin_sides = {
            "heads": {
                "aliases": ['heads', 'head', 'h'],
                "images": [
                    "https://i.imgur.com/BcSMPgD.png"
                ]
            },
            "tails": {
                "aliases": ['tails', 'tail', 't'],
                "images" : [
                    "https://i.imgur.com/bt3xeCq.png"
                ]
            }
        }

        # dbl stuff
        self.dblpy = dbl.DBLClient(self.bot, **self.bot.config['dbl_credentials'])
        self.votes = set()

    def cog_unload(self):
        self.bot.loop.create_task(self.dblpy.close())

    @commands.Cog.listener()
    async def on_dbl_vote(self, data):
        self.votes.add(int(data['user']))
        self.bot.logger.info(f'Received an upvote and its been added to the set! {data}')

    @commands.Cog.listener()
    async def on_dbl_test(self, data):
        self.votes.add(int(data['user']))
        self.bot.logger.info(f'Received an upvote and its been added to the set! {data}')

    @commands.command(aliases=['$', 'money'])
    async def cash(self, ctx: MidoContext, *, user: MidoMemberConverter() = None):
        """Check how many donuts you have or someone else has."""
        if user:
            user_db = await UserDB.get_or_create(bot=ctx.bot, user_id=user.id)
        else:
            user = ctx.author
            user_db = ctx.user_db

        await ctx.send_success(f"**{user.mention}** has **{user_db.cash_readable}{Resources.emotes.currency}**!")

    @commands.command()
    async def daily(self, ctx: MidoContext):
        """
        Claim {0.bot.config[daily_amount]} {0.resources.emotes.currency} for free every 12 hours by upvoting [here]({0.resources.links.upvote}).
        """
        daily_status = ctx.user_db.daily_date_status
        daily_amount = self.bot.config['daily_amount']

        try:
            has_voted = ctx.author.id in self.votes or await self.dblpy.get_user_vote(ctx.author.id)
        except dbl.HTTPException:
            raise APIError

        if not daily_status.end_date_has_passed:
            raise OnCooldownError(f"You're on cooldown! Try again after **{daily_status.remaining_string}**.")
        elif not has_voted:
            raise DidntVoteError(f"It seems like you haven't voted yet.\n\n"
                                 f"Vote [here]({Resources.links.upvote}), "
                                 f"then use this command again to get your **{daily_amount}{Resources.emotes.currency}**!")

        else:
            try:
                self.votes.remove(ctx.author.id)
            except KeyError:
                pass

            await ctx.user_db.add_cash(daily_amount, daily=True)
            await ctx.send_success(f"You've successfully claimed "
                                   f"your daily **{daily_amount}{Resources.emotes.currency}**!")

    @commands.command(name="flip", aliases=['cf', 'coinflip', 'bf', 'betflip'])
    async def coin_flip(self, ctx: MidoContext, amount: Union[int, str], guessed_side: str):
        """A coin flip game. You'll earn the double amount of what you bet if you predict correctly.

        Sides and Aliases:
        **Heads**: `heads`, `head`, `h`
        **Tails**: `tails`, `tail`, `t`"""
        actual_guessed_side_name = None
        for side_name, properties in self.coin_sides.items():
            if guessed_side.lower() in properties['aliases']:
                actual_guessed_side_name = side_name

        if not actual_guessed_side_name:
            raise commands.BadArgument("Incorrect coin side!")

        random_side_name = random.choice(list(self.coin_sides.keys()))

        e = discord.Embed()
        e.set_image(url=random.choice(self.coin_sides[random_side_name]['images']))

        if actual_guessed_side_name == random_side_name:
            await ctx.user_db.add_cash(amount * 2)

            e.title = "Congratulations!"
            e.description = f"You flipped {random_side_name} and won **{amount * 2}{Resources.emotes.currency}**!"
            e.colour = self.success_color

        else:
            e.title = "I'm sorry..."
            e.description = f"You flipped {random_side_name} and lost **{amount}{Resources.emotes.currency}**."
            e.colour = self.fail_color

        e.set_footer(icon_url=ctx.author.avatar_url, text=f"Current cash: {ctx.user_db.cash_readable}")

        return await ctx.send(embed=e)

    @commands.command()
    async def wheel(self, ctx: MidoContext, amount: Union[int, str]):
        """Turn the wheel!"""
        possibilities_and_arrows = {
            1.5: '↖️',
            1.7: '⬆️',
            2.4: '↗️',
            0.2: '⬅️',
            1.2: '➡️',
            0.1: '↙️',
            0.3: '⬇️',
            0.5: '↘️'
        }
        empty = "⠀"

        e = MidoEmbed(bot=self.bot)

        won_multiplier, won_arrow = random.choice(list(possibilities_and_arrows.items()))
        won_cash = int(won_multiplier * amount)

        e.set_author(icon_url=ctx.author.avatar_url,
                     name=f'{ctx.author.display_name} has just won: {won_cash}{Resources.emotes.currency}')

        await ctx.user_db.add_cash(won_cash)

        e.description = ""
        for i, multiplier_and_arrow in enumerate(possibilities_and_arrows.items()):
            multiplier, arrow = multiplier_and_arrow

            if i == 4:
                e.description += empty + won_arrow + empty * 7

            e.description += f'**『{multiplier}』**{empty * 5}'

            if i in (2, 4):
                e.description += '\n\n'

        await ctx.send(embed=e)

    @commands.command(aliases=['slot'])
    async def slots(self, ctx: MidoContext, amount: Union[int, str]):
        """Play slots!

        You get;
        - **x30** -> If you get 3 {0.resources.emotes.currency}
        - **x10** -> If you get 3 same emojis
        - **x4** -> If you get 2 {0.resources.emotes.currency}
        - **x1** -> If you get 1 {0.resources.emotes.currency}
        """
        emojis = [Resources.emotes.currency, "🦋", "♥", "🐱", "🌙", "🍑"]

        slot = []
        for i in range(3):
            slot.append([])
            for j in range(3):
                slot[i].append(random.choice(emojis))

        middle = slot[1]
        if middle.count(emojis[0]) == 3:  # 3 donuts
            win_multiplier = 30
        elif middle.count(middle[0]) == 3:  # 3 of the same emoji
            win_multiplier = 10
        elif middle.count(emojis[0]) == 2:  # 2 donuts
            win_multiplier = 4
        elif middle.count(emojis[0]) == 1:  # 1 donut
            win_multiplier = 1
        else:
            win_multiplier = 0

        won = win_multiplier * amount

        await ctx.user_db.add_cash(amount=won)

        if win_multiplier >= 1:
            content = '**[ 🟢  WIN  🟢 ]**\n'
        else:
            content = '**[ 🔴 LOST 🔴 ]**\n'

        content += '**' + '-' * 19 + '**' + '\n'

        # idk why im making this compatible with all sizes ¯\_(ツ)_/¯
        for i in range(len(slot)):
            for j in range(len(slot[i])):
                if j == 0:  # if beginning
                    content += '| '

                content += slot[i][j]

                content += ' | '

            if i == math.floor(len(slot) / 2):  # if middle
                content += ' **<**'

            content += '\n'  # usual new line
            if i != len(slot) - 1:  # extra new line in between
                content += '\n'

        content += '**' + '-' * 19 + '**' + '\n\n'

        content += f'**{ctx.author}** bet **{amount} {emojis[0]}** '
        # footer
        if win_multiplier > 1:
            content += f'and earned **{won} {emojis[0]}**!! (x{win_multiplier})'
        elif win_multiplier == 1:
            content += f'got the same amount back. '
        else:
            content += f'and lost it all :('

        await ctx.send(content=content)

    @commands.command(aliases=['br'])
    async def betroll(self, ctx: MidoContext, amount: Union[int, str]):
        """Roll a random number between 1 and 100."""
        rolled = random.randint(1, 100)
        win_multip = 0

        if rolled > 66:
            color = self.success_color
            if rolled == 100:
                win_multip = 10
                msg = f"Congratulations!! You won **{win_multip * amount} {Resources.emotes.currency}** for rolling 100 🎉"
            elif rolled > 90:
                win_multip = 4
                msg = f"Congratulations! You won **{win_multip * amount} {Resources.emotes.currency}** for rolling above 90."
            else:
                win_multip = 2
                msg = f"Congratulations! You won **{win_multip * amount} {Resources.emotes.currency}** for rolling above 66."
        else:
            color = self.fail_color
            msg = f"Better luck next time 🥺"

        await ctx.user_db.add_cash(amount=amount * win_multip)

        e = MidoEmbed(bot=ctx.bot, colour=color)
        e.description = "**You rolled:** "
        rolled_str = "{:02d}".format(rolled)
        for digit in rolled_str:
            e.description += DIGIT_TO_EMOJI[int(digit)]

        e.description += '\n\n' + msg

        e.set_footer(icon_url=ctx.author.avatar_url, text=str(ctx.author))

        await ctx.send(embed=e)

    @commands.command(aliases=['lb'])
    async def leaderboard(self, ctx: MidoContext):
        """See the donut leaderboard!"""
        rich_people = await UserDB.get_rich_people(bot=ctx.bot, limit=100)

        e = MidoEmbed(bot=self.bot,
                      title=f"{Resources.emotes.currency} Leaderboard")

        blocks = []
        for i, user in enumerate(rich_people, 1):
            # if its the #1 user
            if i == 1:
                user_obj = self.bot.get_user(user.id)
                if user_obj:
                    e.set_thumbnail(url=user_obj.avatar_url)

            blocks.append(f"`#{i}` **{user.discord_name}**\n"
                          f"{user.cash_readable} {Resources.emotes.currency}")

        await e.paginate(ctx, blocks, item_per_page=10, extra_sep='\n')

    @commands.command(name="give")
    @commands.guild_only()
    async def give_cash(self, ctx: MidoContext, amount: Union[int, str], *, member: MidoMemberConverter()):
        """Give a specific amount of donut to someone else."""
        if member.id == ctx.author.id:
            raise commands.UserInputError("Why'd you send money to yourself?")

        other_usr = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)

        await other_usr.add_cash(amount)
        await ctx.send_success(f"**{ctx.author.mention}** has just sent **{amount}{Resources.emotes.currency}** "
                               f"to **{member.mention}**!")

    @checks.is_owner()
    @commands.command(name="award", aliases=['addcash'], hidden=True)
    async def add_cash(self, ctx: MidoContext, amount: Union[int, str], *, member: MidoMemberConverter()):
        other_usr = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)

        await other_usr.add_cash(amount)
        await member.send(f"You've been awarded **{amount}{Resources.emotes.currency}** by the bot owner!")
        await ctx.send_success(f"You've successfully awarded {member} with **{amount}{Resources.emotes.currency}**!")

    @checks.is_owner()
    @commands.command(name="punish", aliases=['withdraw, removecash'], hidden=True)
    async def remove_cash(self, ctx: MidoContext, amount: Union[int, str], *, member: MidoMemberConverter()):
        other_usr = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)

        await other_usr.remove_cash(amount)
        await ctx.send_success(f"You've just removed **{amount}{Resources.emotes.currency}** from {member}.")

    @wheel.before_invoke
    @betroll.before_invoke
    @slots.before_invoke
    @coin_flip.before_invoke
    @give_cash.before_invoke
    async def ensure_not_broke(self, ctx: MidoContext):
        bet_amount = ctx.args[2]  # arg after the context is the amount.

        if isinstance(bet_amount, int):
            if bet_amount > ctx.user_db.cash:
                raise InsufficientCash

            elif bet_amount <= 0:
                raise commands.BadArgument("The amount can not be less than or equal to 0!")
        else:
            if bet_amount == 'all':
                ctx.args[2] = int(ctx.user_db.cash)
            elif bet_amount == 'half':
                ctx.args[2] = int(ctx.user_db.cash / 2)
            else:
                raise commands.BadArgument("Please input a proper amount! (`all` or `half`)")

        await ctx.user_db.remove_cash(ctx.args[2])


def setup(bot):
    bot.add_cog(Gambling(bot))
