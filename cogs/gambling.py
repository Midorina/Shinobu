import random

import discord
from discord.ext import commands

from db import db_funcs
from services import checks, context


class GamblingError(Exception):
    pass


class Gambling(commands.Cog):
    def __init__(self, bot: commands.Bot):
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
                    "https://i.imgur.com/CDO1lBA.png"   # 0.01
                ]
            },
            "tails": {
                "aliases": ['tails', 'tail', 't'],
                "images": [
                    "https://i.imgur.com/rOxePah.png",  # 1
                    "https://i.imgur.com/C1LkEY4.png",  # 0.50
                    "https://i.imgur.com/pPDQ1xj.png",  # 0.25
                    "https://i.imgur.com/0vLHUSr.png",  # 0.10
                    "https://i.imgur.com/7BotKnp.png",  # 0.05
                    "https://i.imgur.com/bsU71r6.png"   # 0.01
                ]
            }
        }

    @commands.command()
    async def cash(self, ctx: context.Context, *, user: discord.Member = None):
        await ctx.send(f"**{user}** has **{ctx.author_db.cash}$**!")

    @commands.command()
    async def daily(self, ctx: context.Context):
        can_claim, remaining = ctx.author_db.can_claim_daily_remaining

        if not can_claim:
            return await ctx.send(
                f"You're on cooldown! Try again after **{self.bot.remaining_string(remaining)}**.")

        else:
            daily_amount = self.bot.config['daily_amount']
            await ctx.author_db.add_cash(daily_amount, daily=True)
            await ctx.send(f"You've successfully claimed your daily **{daily_amount}$**!")

    @commands.command(name="flip", aliases=['cf', 'coinflip'])
    async def coin_flip(self, ctx: context.Context, amount: int, guessed_side: str):
        actual_guessed_side = None
        for side in self.coin_sides.values():
            if guessed_side.lower() in side['aliases']:
                actual_guessed_side = side

        if not actual_guessed_side:
            raise commands.BadArgument("Incorrect coin side!")

        random_side = random.choice(list(self.coin_sides.values()))

        e = discord.Embed()
        e.set_image(url=random.choice(random_side['images']))

        if guessed_side == random_side:
            await ctx.author_db.add_cash(amount * 2)

            e.title = "Congratulations!"
            e.description = f"You flipped {random_side['aliases'][0]} and won **{amount * 2}**!"
            e.colour = self.success_color

        else:
            e.title = "I'm sorry..."
            e.description = f"You flipped {random_side['aliases'][0]} and lost **{amount}**."
            e.colour = self.fail_color

        e.set_footer(icon_url=ctx.author.avatar_url, text=f"Current cash: {ctx.author_db.cash}")

        return await ctx.send(embed=e)

    @commands.command(name="give")
    @commands.guild_only()
    async def give_cash(self, ctx: context.Context, amount: int, *, member: discord.Member):
        other_usr = await db_funcs.get_user_db(ctx.db, member.id)

        await other_usr.add_cash(amount)
        await ctx.send(f"**{ctx.author}** has just sent **{amount}$** to **{member.mention}**!")

    @checks.owner_only()
    @commands.command(name="award")
    async def add_cash(self, ctx: context.Context, amount: int, *, member: discord.Member):
        other_usr = await db_funcs.get_user_db(ctx.db, member.id)

        await other_usr.add_cash(amount)
        await member.send(f"You've been awarded **{amount}$** by the bot owner!")
        await ctx.send(f"You've successfully awarded {member} with **{amount}$**!")

    @checks.owner_only()
    @commands.command(name="punish", aliases=['withdraw'])
    async def remove_cash(self, ctx: context.Context, amount: int, *, member: discord.Member):
        other_usr = await db_funcs.get_user_db(ctx.db, member.id)

        await other_usr.remove_cash(amount)
        await ctx.send(f"You've just removed **{amount}$** from {member}.")

    @coin_flip.before_invoke
    @give_cash.before_invoke
    async def ensure_not_broke(self, ctx: context.Context):
        bet_amount = ctx.args[2]  # arg after the context is the amount.

        if bet_amount > ctx.author_db.cash:
            raise commands.BadArgument("You can't bet more than you have!")

        elif bet_amount <= 0:
            raise commands.BadArgument("The bet amount can not be less than 0!")

        else:
            await ctx.author_db.remove_cash(bet_amount)


def setup(bot):
    bot.add_cog(Gambling(bot))
