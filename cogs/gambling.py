import random
from typing import Union

import dbl
import discord
from discord.ext import commands

from midobot import MidoBot
from models.db_models import UserDB
from services import checks, context
from services.converters import MidoMemberConverter
from services.exceptions import EmbedError
from services.resources import Resources


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
                    "https://i.imgur.com/gA7NWyL.png",  # 1
                    "https://i.imgur.com/PjnLpfk.png",  # 0.50
                    "https://i.imgur.com/MzP2cqs.png",  # 0.25
                    "https://i.imgur.com/3JfgyEP.png",  # 0.10
                    "https://i.imgur.com/x7krykG.png",  # 0.05
                    "https://i.imgur.com/CDO1lBA.png"  # 0.01
                ]
            },
            "tails": {
                "aliases": ['tails', 'tail', 't'],
                "images" : [
                    "https://i.imgur.com/rOxePah.png",  # 1
                    "https://i.imgur.com/C1LkEY4.png",  # 0.50
                    "https://i.imgur.com/pPDQ1xj.png",  # 0.25
                    "https://i.imgur.com/0vLHUSr.png",  # 0.10
                    "https://i.imgur.com/7BotKnp.png",  # 0.05
                    "https://i.imgur.com/bsU71r6.png"  # 0.01
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
        self.bot.logger.info('Received an upvote and its been added to the set!\n'
                             '{}'.format(data))

    @commands.Cog.listener()
    async def on_dbl_test(self, data):
        self.votes.add(int(data['user']))
        self.bot.logger.info('Received a test and its been added to the set!\n'
                             '{}'.format(data))

    @commands.command(aliases=['$', 'money'])
    async def cash(self, ctx: context.MidoContext, *, user: MidoMemberConverter() = None):
        """Check the cash status of you or someone else."""
        if user:
            user_db = await UserDB.get_or_create(ctx.db, user.id)
        else:
            user = ctx.author
            user_db = ctx.user_db

        await ctx.send_success(f"**{user.mention}** has **{user_db.cash}{Resources.emotes.currency}**!")

    @commands.command()
    async def daily(self, ctx: context.MidoContext):
        """
        Claim {0.bot.config[daily_amount]}{0.resources.emotes.currency} for free every 12 hours by upvoting [here]({0.resources.links.upvote}).
        """
        daily_status = ctx.user_db.daily_date_status
        daily_amount = self.bot.config['daily_amount']

        has_voted = ctx.author.id in self.votes or await self.dblpy.get_user_vote(ctx.author.id)

        if not daily_status.end_date_has_passed:
            raise EmbedError(
                f"You're on cooldown! Try again after **{daily_status.remaining_string}**.")
        elif not has_voted:
            raise EmbedError(f"It seems like you haven't voted yet. "
                             f"Vote [here]({Resources.links.upvote}), then use this command again "
                             f"to get your **{daily_amount}{Resources.emotes.currency}**!")

        else:
            self.votes.remove(ctx.author.id)
            await ctx.user_db.add_cash(daily_amount, daily=True)
            await ctx.send_success(f"You've successfully claimed "
                                   f"your daily **{daily_amount}{Resources.emotes.currency}**!")

    @commands.command(name="flip", aliases=['cf', 'coinflip'])
    async def coin_flip(self, ctx: context.MidoContext, amount: Union[int, str], guessed_side: str):
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
            e.description = f"You flipped {random_side_name} and won **{amount * 2}**!"
            e.colour = self.success_color

        else:
            e.title = "I'm sorry..."
            e.description = f"You flipped {random_side_name} and lost **{amount}**."
            e.colour = self.fail_color

        e.set_footer(icon_url=ctx.author.avatar_url, text=f"Current cash: {ctx.user_db.cash}")

        return await ctx.send(embed=e)

    @commands.command(name="give")
    @commands.guild_only()
    async def give_cash(self, ctx: context.MidoContext, amount: Union[int, str], *, member: MidoMemberConverter()):
        """Give a specific amount of cash to someone else."""
        if member.id == ctx.author.id:
            raise EmbedError("Why'd you send money to yourself?")

        other_usr = await UserDB.get_or_create(ctx.db, member.id)

        await other_usr.add_cash(amount)
        await ctx.send_success(f"**{ctx.author.mention}** has just sent **{amount}{Resources.emotes.currency}** "
                               f"to **{member.mention}**!")

    @checks.owner_only()
    @commands.command(name="award", hidden=True)
    async def add_cash(self, ctx: context.MidoContext, amount: Union[int, str], *, member: MidoMemberConverter()):
        other_usr = await UserDB.get_or_create(ctx.db, member.id)

        await other_usr.add_cash(amount)
        await member.send(f"You've been awarded **{amount}{Resources.emotes.currency}** by the bot owner!")
        await ctx.send_success(f"You've successfully awarded {member} with **{amount}{Resources.emotes.currency}**!")

    @checks.owner_only()
    @commands.command(name="punish", aliases=['withdraw'], hidden=True)
    async def remove_cash(self, ctx: context.MidoContext, amount: Union[int, str], *, member: MidoMemberConverter()):
        other_usr = await UserDB.get_or_create(ctx.db, member.id)

        await other_usr.remove_cash(amount)
        await ctx.send_success(f"You've just removed **{amount}{Resources.emotes.currency}** from {member}.")

    @coin_flip.before_invoke
    @give_cash.before_invoke
    async def ensure_not_broke(self, ctx: context.MidoContext):
        if ctx.user_db.cash <= 0:
            raise EmbedError("You don't have any money.")

        bet_amount = ctx.args[2]  # arg after the context is the amount.

        if isinstance(bet_amount, int):
            if bet_amount > ctx.user_db.cash:
                raise commands.BadArgument("The amount can not be more than you have!")

            elif bet_amount <= 0:
                raise commands.BadArgument("The amount can not be less than or equal to 0!")
        else:
            if bet_amount == 'all':
                ctx.args[2] = int(ctx.user_db.cash)
            elif bet_amount == 'half':
                ctx.args[2] = int(ctx.user_db.cash / 2)
            else:
                raise commands.BadArgument("Please input a proper amount!")

        await ctx.user_db.remove_cash(ctx.args[2])


def setup(bot):
    bot.add_cog(Gambling(bot))
