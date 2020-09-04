from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from main import MidoBot
from models.db_models import UserDB
from services.context import MidoContext
from services.converters import MidoMemberConverter
from services.exceptions import EmbedError


class Waifu(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command()
    async def show_gifts(self, ctx: MidoContext):
        await ctx.send("".join(x.emote for x in ctx.user_db.waifu.items))

    @commands.command(name='affinity')
    @commands.cooldown(rate=1, per=1800, type=BucketType.user)  # 30 minutes
    async def _change_affinity(self, ctx: MidoContext, target: MidoMemberConverter() = None):
        """
        Sets your affinity towards someone you want to be claimed by.
        Setting affinity will reduce their `{0.prefix}claim` on you by 20%.
        Provide no parameters to clear your affinity. 30 minutes cooldown.
        """
        previous_affinity = self.bot.get_user(ctx.user_db.waifu.affinity_id)

        await ctx.user_db.waifu.change_affinity(target.id if target else None)

        if not target:
            await ctx.send_success("You've successfully cleared your affinity.")
        elif not previous_affinity:
            await ctx.send_success(f"You've successfully set your affinity towards **{target.display_name}**.")
        else:
            await ctx.send_success(f"**{ctx.author.display_name}** changed their affinity "
                                   f"from **{previous_affinity.display_name}** to **{target.display_name}**."
                                   f"\n\n"
                                   f"*Sometimes you just can't oppose your heart.*")

    @commands.command(name='claimwaifu', aliases=['claim'])
    async def claim_waifu(self, ctx: MidoContext, price: int, target: MidoMemberConverter()):
        """
        Claim a waifu for yourself by spending money.
        You must spend at least 10% more than their current value, unless they set `{0.prefix}affinity` towards you.
        """
        if target.id == ctx.author.id:
            raise EmbedError("Why'd you try to do that? You technically already own yourself.")

        target_db = await UserDB.get_or_create(ctx.db, target.id)

        required_amount = target_db.waifu.get_price_to_claim(ctx.author.id)

        if price < required_amount:
            raise EmbedError(f"You must pay at least **{required_amount}** to claim {target.mention}.")

        await ctx.user_db.remove_cash(required_amount)

        await target_db.waifu.get_claimed(ctx.author.id, price)

        if target_db.waifu.affinity_id == ctx.author.id:
            await ctx.send_success(f"{ctx.author.mention} claimed {target.mention} as their waifu for **{price}$**!\n"
                                   f"\n"
                                   f"🎉 Their love is fulfilled! 🎉\n"
                                   f"\n"
                                   f"{target.mention}'s new value is {target_db.waifu.price}$!")
        else:
            await ctx.send_success(f"{ctx.author.mention} claimed {target.mention} as their waifu for **{price}$**!")

    # @commands.command(rate=1, per=21600, type=BucketType.user)  # 6 hours
    # async def divorce(self, ctx: MidoContext, target: MidoMemberConverter()):
    #     """
    #     Divorce a waifu.
    #     You will get half of the money you've spent back.
    #     If that waifu has an affinity towards you, there will be an additional -25% penalty.
    #     6 hours cooldown.
    #     """
    #     if target.id == ctx.author.id:
    #         raise EmbedError("Why'd you try to do that? "
    #                          "Yes, most people hate themselves, however, life is worth living.")
    #
    #     target_db = await UserDB.get_or_create(ctx.db, target.id)
    #
    #     if target_db.waifu.owner_id != ctx.author.id:
    #         raise EmbedError(f"{target.mention} is not your waifu!")
    #
    #     amount = target_db.waifu.get_divorce_price(ctx.author.id)
    #
    #     await ctx.user_db.add_cash(amount)
    #
    #     await target_db.waifu.get_claimed(ctx.author.id, price)
    #
    #     if target_db.waifu.affinity_id == ctx.author.id:
    #         await ctx.send_success(f"{ctx.author.mention} claimed {target.mention} as their waifu for **{price}$**!\n"
    #                                f"\n"
    #                                f"🎉 Their love is fulfilled! 🎉\n"
    #                                f"\n"
    #                                f"{target.mention}'s new value is {target_db.waifu.price}$!")
    #     else:
    #         await ctx.send_success(f"{ctx.author.mention} claimed {target.mention} as their waifu for **{price}$**!")


def setup(bot):
    bot.add_cog(Waifu(bot))
