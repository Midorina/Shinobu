from discord.ext import commands
import discord
import random
from services import db_funcs, checks


class GamblingError(Exception):
    pass


class Gambling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # general gambling variables
        self.success_color = 0x00ff00
        self.fail_color = 0xff0000

        # roulette variables
        self.roulette_colors = {
            'black': 0x000000,
            'red': 0xff0000,
            'green': 0x00ff00
        }

        # coin variables
        self.heads_aliases = ['h', 'heads', 'head']
        self.tails_aliases = ['t', 'tails', 'tail']
        self.proper_coin_sides = ['heads', 'tails']

        self.coin_images = {
            1: {
                "heads": "https://i.imgur.com/gA7NWyL.png",
                "tails": "https://i.imgur.com/rOxePah.png"
            },

            0.5: {
                "heads": "https://i.imgur.com/PjnLpfk.png",
                "tails": "https://i.imgur.com/C1LkEY4.png"
            },

            0.25: {
                "heads": "https://i.imgur.com/MzP2cqs.png",
                "tails": "https://i.imgur.com/pPDQ1xj.png"
            },

            0.10: {
                "heads": "https://i.imgur.com/3JfgyEP.png",
                "tails": "https://i.imgur.com/0vLHUSr.png"
            },

            0.05: {
                "heads": "https://i.imgur.com/x7krykG.png",
                "tails": "https://i.imgur.com/7BotKnp.png"
            },

            0.01: {
                "heads": "https://i.imgur.com/CDO1lBA.png",
                "tails": "https://i.imgur.com/bsU71r6.png"
            }
        }

    @commands.command()
    async def cash(self, ctx, *, user: discord.Member = None):
        user = user or ctx.author
        user_db = await db_funcs.get_user_db(self.bot.db, user.id)

        await ctx.send(f"**{user}** has **{user_db.cash}$**!")

    @commands.command()
    async def daily(self, ctx):
        user_db = await db_funcs.get_user_db(self.bot.db, ctx.author.id)
        # can_claim, remaining = await self.bot.check_cooldown(user_db, "daily")

        if user_db.daily_remaining_time > 0:
            return await ctx.send(
                f"You're on cooldown! Remaining time: **{self.bot.remaining_string(user_db.daily_remaining_time)}**"
            )

        else:
            daily_amount = self.bot.config['daily_amount']
            await db_funcs.add_cash(self.bot.db, ctx.author.id, daily_amount, daily=True)
            await ctx.send(f"You've successfully claimed your daily **{daily_amount}$**!")

    @commands.command(name="flip", aliases=['cf', 'coinflip'])
    async def coin_flip(self, ctx, amount: int, guessed_side: str):
        if guessed_side.lower() in self.heads_aliases:
            guessed_side = self.proper_coin_sides[0]
        elif guessed_side.lower() in self.tails_aliases:
            guessed_side = self.proper_coin_sides[1]
        else:
            raise commands.BadArgument("Incorrect coin side!")

        random_side = random.choice(self.proper_coin_sides)

        e = discord.Embed()
        e.set_image(url=self.coin_images[random.choice(list(self.coin_images.keys()))][random_side])

        if guessed_side == random_side:
            await db_funcs.add_cash(self.bot.db, ctx.author.id, amount * 2)

            e.title = "Congratulations!"
            e.description = f"You flipped {random_side} and won **{amount * 2}**!"
            e.colour = self.success_color

        else:
            e.title = "I'm sorry..."
            e.description = f"You flipped {random_side} and lost **{amount}**."
            e.colour = self.fail_color

        user_db = await db_funcs.get_user_db(self.bot.db, ctx.author.id)
        e.set_footer(icon_url=ctx.author.avatar_url, text=f"Current cash: {user_db.cash}")

        return await ctx.send(embed=e)

    @commands.command(aliases=['r'])
    async def roulette(self, ctx, amount: int, color):
        if color not in self.roulette_colors.keys():
            raise commands.BadArgument("Invalid color!")

        random_color = random.choice(self.roulette_colors.keys())
        e = discord.Embed(color=self.roulette_colors[random_color])

        if random_color == color.lower():
            await db_funcs.add_cash(self.bot.db, ctx.author.id, amount * 2)

            e.title = "Congratulations!"
            e.description = f"You guessed right and won **{amount * 2}**!"

        else:
            e.title = f"I'm sorry..."
            e.description = f"You guessed wrong and lost **{amount}**."

        user_db = await db_funcs.get_user_db(self.bot.db, ctx.author.id)
        e.set_footer(icon_url=ctx.author.avatar_url, text=f"Your current cash: {user_db.cash}")

        return await ctx.send(embed=e)

    @commands.command(name="give")
    @commands.guild_only()
    async def give_cash(self, ctx, amount: int, *, member: discord.Member):
        await db_funcs.add_cash(self.bot.db, member.id, amount)
        await ctx.send(f"**{ctx.author}** has just sent **{amount}$** to **{member.mention}**!")

    @checks.owner_only()
    @commands.command(name="award")
    async def add_cash(self, ctx, amount: int, *, member: discord.Member):
        await db_funcs.add_cash(self.bot.db, member.id, amount)
        await member.send(f"You've been awarded **{amount}$** by the bot owner!")
        await ctx.send(f"You've successfully awarded {member} with **{amount}$**!")

    @checks.owner_only()
    @commands.command(name="punish", aliases=['withdraw'])
    async def remove_cash(self, ctx, amount: int, *, member: discord.Member):
        await db_funcs.remove_cash(self.bot.db, member.id, amount)
        await ctx.send(f"You've just removed **{amount}$** from {member}.")

    @roulette.before_invoke
    @coin_flip.before_invoke
    @give_cash.before_invoke
    async def ensure_not_broke(self, ctx):
        user_db = await db_funcs.get_user_db(self.bot.db, ctx.author.id)
        bet_amount = None

        for i in range(len(ctx.args)):
            if isinstance(ctx.args[i], commands.Context):
                bet_amount = ctx.args[i+1]  # arg after the context is the amount.
                break

        if bet_amount > user_db.cash:
            raise commands.BadArgument("You can't bet more than you have!")

        elif bet_amount <= 0:
            raise commands.BadArgument("The bet amount can not be less than 0!")

        else:
            await db_funcs.remove_cash(self.bot.db, ctx.author.id, bet_amount)


def setup(bot):
    bot.add_cog(Gambling(bot))
