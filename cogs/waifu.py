import math
from typing import List

from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from midobot import MidoBot
from models.db_models import UserDB
from models.waifu_models import Item
from services.context import MidoContext
from services.converters import MidoMemberConverter, readable_bigint
from services.embed import MidoEmbed
from services.exceptions import EmbedError
from services.resources import Resources


class Waifu(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command(aliases=['waifulb'])
    async def waifuleaderboard(self, ctx: MidoContext):
        """See the global top 5 waifu list."""
        top_5 = await UserDB.get_top_expensive_waifus(5, ctx.db)

        e = MidoEmbed(self.bot)
        e.title = "Waifu Leaderboard"

        e.description = ""
        for i, user_db in enumerate(top_5, 1):
            user = self.bot.get_user(user_db.id)
            user_name = str(user) if user else user_db.discord_name

            affinity_name = self.bot.get_user_name(user_db.waifu.affinity_id)
            claimer_name = self.bot.get_user_name(user_db.waifu.claimer_id) if user_db.waifu.claimer_id else "no one."

            # if its the #1 user
            if i == 1 and user:
                e.set_thumbnail(url=user.avatar_url)

            e.description += f"`#{i}` **{user_db.waifu.price}{Resources.emotes.currency}** " \
                             f"**{user_name}** claimed by **{claimer_name}**\n"
            if not user_db.waifu.affinity_id:
                if not user_db.waifu.claimer_id:
                    e.description += "... and "
                else:
                    e.description += f"... but "

                e.description += f"{user_name}'s heart is empty :(\n"

            elif user_db.waifu.affinity_id == user_db.waifu.claimer_id:
                e.description += f"... and {user_name} likes {claimer_name} too ♥\n"

            else:
                e.description += f"... but {user_name}'s heart belongs to {affinity_name}...\n"

            e.description += "\n"

        await ctx.send(embed=e)

    @commands.command()
    async def waifureset(self, ctx: MidoContext):
        """
        Reset your waifu stats by spending some money.
        You'll get a prompt with how much you need to spend.
        This will reset everything except your waifus.
        """
        price_to_reset = ctx.user_db.waifu.get_price_to_reset()

        msg = await ctx.send_success(f"Are you sure you'd like to reset your waifu stats?\n"
                                     f"This will cost you **{price_to_reset}{Resources.emotes.currency}**.\n\n"
                                     f"*This action will reset everything **except your waifus**.*")

        yes = await MidoEmbed.yes_no(self.bot, ctx.author.id, msg)
        if yes:
            await ctx.user_db.remove_cash(price_to_reset)

            await ctx.user_db.waifu.reset_waifu_stats()

            await ctx.edit_custom(msg, "You've successfully reset your waifu stats.")

        else:
            await ctx.edit_custom(msg, "Request declined.")

    @commands.command(aliases=['waifugift'])
    async def gift(self, ctx: MidoContext, item_name: str = None, target: MidoMemberConverter() = None):
        """
        Use this command without any parameters to see the item shop.
        Specify the item name and a waifu to send a gift to them.

        Sending a gift increases the target waifu's price by half of the item's value.
        """
        if not item_name and not target:
            e = MidoEmbed(ctx.bot)

            item_blocks = []
            for item in Item.get_all():
                item_blocks.append(
                    f'**{item.emote_n_name}** -> {readable_bigint(item.price)}{Resources.emotes.currency}')

            await e.paginate(ctx, item_blocks, item_per_page=9)
        else:
            if not item_name or not target:
                raise commands.BadArgument
            elif target.id == ctx.author.id:
                raise commands.BadArgument("You can't buy gifts to yourself. This level of loneliness is no good.")

            item_obj = Item.find(item_name)
            if not item_obj:
                raise EmbedError(f"Could not find a waifu item called **\"{item_name}\"**.")

            await ctx.user_db.remove_cash(item_obj.price)

            target_db = await UserDB.get_or_create(ctx.db, target.id)
            await target_db.waifu.add_item(item_obj)

            await ctx.send_success(f"{ctx.author.mention} has just gifted "
                                   f"**{item_obj.name_n_emote}** to {target.mention}!")

    @commands.command(aliases=['waifuinfo'])
    async def waifustats(self, ctx: MidoContext, target: MidoMemberConverter() = None):
        """
        See the waifu stats of yourself or any other waifu.
        """
        if target:
            target_db = await UserDB.get_or_create(ctx.db, target.id)
        else:
            target = ctx.author
            target_db = ctx.user_db

        claimer_name = (await UserDB.get_or_create(ctx.db, target_db.waifu.claimer_id)).discord_name \
            if target_db.waifu.claimer_id else 'Nobody'
        affinity_name = (await UserDB.get_or_create(ctx.db, target_db.waifu.affinity_id)).discord_name \
            if target_db.waifu.affinity_id else 'Nobody'

        e = MidoEmbed(ctx.bot)
        e.set_author(icon_url=target.avatar_url, name=f"Waifu {target}")

        e.add_field(name="Price", value=f'{readable_bigint(target_db.waifu.price)} '
                                        f'{Resources.emotes.currency}', inline=True)
        e.add_field(name="Claimed by",
                    value=claimer_name,
                    inline=True)

        e.add_field(name="Likes",
                    value=affinity_name,
                    inline=True)

        e.add_field(name="Changes of Heart", value=str(target_db.waifu.affinity_changes), inline=True)
        e.add_field(name="Divorces", value=str(target_db.waifu.divorce_count), inline=True)

        if not target_db.waifu.items:
            gift_field_val = '-'
        else:
            items = Item.get_emotes_and_amounts(target_db.waifu.items)
            gift_field_val = ""
            for i, emote_and_count in enumerate(items, 1):
                emote, count = emote_and_count
                gift_field_val += f'{emote} x{count} '

                if i % 2 == 0:
                    gift_field_val += '\n'

        e.add_field(name="Gifts", value=gift_field_val, inline=False)

        waifus: List[UserDB] = await UserDB.get_claimed_waifus_by(target.id, ctx.db)
        e.add_field(name=f"Waifus ({len(waifus)})",
                    value="\n".join(waifu.discord_name for waifu in waifus) if waifus else '-')

        await ctx.send(embed=e)

    @commands.cooldown(rate=1, per=1800, type=BucketType.user)  # 30 minutes
    async def affinity(self, ctx: MidoContext, target: MidoMemberConverter() = None):
        """
        Sets your affinity towards someone you want to be claimed by.
        Setting affinity will reduce their `{0.prefix}claim` on you by 20%.
        Provide no parameters to clear your affinity. 30 minutes cooldown.
        """
        if ctx.user_db.waifu.affinity_id:
            if ctx.user_db.waifu.affinity_id == target.id:
                raise EmbedError(f"You already have affinity towards {target.mention}. "
                                 f"Use `{ctx.prefix}affinity` without any parameters to clear your affinity.")
        elif not target:
            raise EmbedError("Your affinity is already empty.")

        await ctx.user_db.waifu.change_affinity(target.id if target else None)

        previous_affinity = self.bot.get_user(ctx.user_db.waifu.affinity_id)

        if not target:
            await ctx.send_success("You've successfully cleared your affinity.")
        elif not previous_affinity:
            await ctx.send_success(f"You've successfully set your affinity towards **{target.display_name}**.")
        else:
            await ctx.send_success(f"**{ctx.author.display_name}** changed their affinity "
                                   f"from **{previous_affinity.display_name}** to **{target.display_name}**."
                                   f"\n\n"
                                   f"*Sometimes you just can't oppose your heart.*")

    @commands.command(name='claim', aliases=['claimwaifu'])
    async def claim_waifu(self, ctx: MidoContext, price: int, target: MidoMemberConverter()):
        """
        Claim a waifu for yourself by spending money.
        You must spend at least 10% more than their current value, unless they set `{0.prefix}affinity` towards you.
        """
        target_db = await UserDB.get_or_create(ctx.db, target.id)

        if target.id == ctx.author.id:
            raise EmbedError("Why'd you try to do that? You technically already own yourself.")
        elif target_db.waifu.claimer_id == ctx.author.id:
            raise EmbedError(f"{target.mention} is already your waifu. "
                             f"Try gifting items to them to increase their price and make them happier :)")

        required_amount = target_db.waifu.get_price_to_claim(ctx.author.id)

        if price < required_amount:
            raise EmbedError(f"You must pay at least **{readable_bigint(required_amount)}** to claim {target.mention}.")

        await ctx.user_db.remove_cash(required_amount)

        await target_db.waifu.get_claimed(ctx.author.id, price)

        base_msg = f"{ctx.author.mention} claimed {target.mention} as their waifu " \
                   f"for **{price}{Resources.emotes.currency}**!\n"

        if target_db.waifu.affinity_id == ctx.author.id:
            await ctx.send_success(base_msg +
                                   f"\n"
                                   f"🎉 Their love is fulfilled! 🎉\n"
                                   f"\n"
                                   f"{target.mention}'s new value is "
                                   f"**{target_db.waifu.price}{Resources.emotes.currency}**!")
        else:
            await ctx.send_success(base_msg)

    @commands.command(rate=1, per=21600, type=BucketType.user)  # 6 hours
    async def divorce(self, ctx: MidoContext, target: MidoMemberConverter()):
        """
        Divorce a waifu.
        - You will get half of the money you've spent back if the waifu's affinity isn't towards you.
        - If the waifu has an affinity towards you, they'll get the money instead, and their price will decrease by 25%.

        6 hours cooldown.
        """
        target_db = await UserDB.get_or_create(ctx.db, target.id)

        if target.id == ctx.author.id:
            raise EmbedError("Why'd you try to do that? "
                             "Yes, most people hate themselves, however, life is worth living.")
        elif target_db.waifu.claimer_id != ctx.author.id:
            raise EmbedError(f"{target.mention} is not your waifu!")

        amount = math.floor(target_db.waifu.price / 2)

        if target_db.waifu.affinity_id == ctx.author.id:
            await target_db.add_cash(amount)
        else:
            await ctx.user_db.add_cash(amount)

        await ctx.user_db.waifu.divorce(target_db.waifu)

        if target_db.waifu.affinity_id == ctx.author.id:
            await ctx.send_success(f"{ctx.author.mention} just has divorced a waifu who likes them. "
                                   f"Guess it was a "
                                   f"[1 sided love](https://open.spotify.com/track/39bs2V8huzcmWoeSlHKZeP).\n"
                                   f"\n"
                                   f"{target.mention} received **{amount}{Resources.emotes.currency}** "
                                   f"as compensation.")
        else:
            await ctx.send_success(f"{ctx.author.mention} has just divorced {target.mention} "
                                   f"and got **{amount}{Resources.emotes.currency}** in return.")

    @commands.command()
    async def waifutransfer(self, ctx: MidoContext, ex_waifu: MidoMemberConverter(), new_owner: MidoMemberConverter()):
        """
        Transfer the ownership of a waifu you own to another user.
        You must pay 10% of your waifu's value for this action.
        """
        ex_waifu_db = await UserDB.get_or_create(ctx.db, ex_waifu.id)
        # new_owner_db = await UserDB.get_or_create(ctx.db, new_owner.id)

        if ex_waifu_db.waifu.claimer_id != ctx.author.id:
            raise EmbedError(f'{ex_waifu.mention} is not your waifu!')

        cost = math.floor(ex_waifu_db.waifu.price / 10)

        await ctx.user_db.remove_cash(cost)

        await ex_waifu_db.waifu.change_claimer(new_owner.id)

        await ctx.send_success(f'{ctx.author.mention} successfully transferred the ownership '
                               f'of {ex_waifu.mention} to {new_owner.mention} '
                               f'using **{cost}{Resources.emotes.currency}**.')


def setup(bot):
    bot.add_cog(Waifu(bot))
