import json
from datetime import datetime

import discord
from discord import ShardInfo
from discord.ext import commands

import mido_utils


class NotDict(Exception):
    pass


# case-insensitive object searches
# and dummy discord object to unban/ban someone we don't see
class MemberConverter(commands.MemberConverter):
    async def convert(self, ctx: mido_utils.Context, argument) -> discord.Member:
        try:
            member = await super().convert(ctx, argument)
        except commands.MemberNotFound:
            member = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.members)

            if not member:
                raise commands.MemberNotFound(argument)

        return member


class UserConverter(commands.UserConverter):
    async def convert(self, ctx: mido_utils.Context, argument) -> discord.User | discord.Object:
        user = None

        try:
            user = await super().convert(ctx, argument)
        except commands.UserNotFound:
            if argument.isdigit():
                user = discord.Object(id=int(argument))
            # else:
            #     user = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.members)

        if not user:
            raise commands.UserNotFound(argument)

        return user


def base_bit_length_check(argument, max_bit_length: int):
    try:
        arg = int(argument)
    except ValueError:
        raise commands.BadArgument("Please input a proper integer.")
    else:
        if arg.bit_length() >= max_bit_length:
            raise commands.BadArgument(
                f"Please input an integer that is withing the {max_bit_length} bit integer range.")

        return arg


class Int16(commands.Converter[int]):
    async def convert(self, ctx: mido_utils.Context, argument) -> int:
        return base_bit_length_check(argument, 16)


class Int32(commands.Converter[int]):
    async def convert(self, ctx: mido_utils.Context, argument) -> int:
        return base_bit_length_check(argument, 32)


class Int64(commands.Converter[int]):
    async def convert(self, ctx: mido_utils.Context, argument) -> int:
        return base_bit_length_check(argument, 64)


class BetAmountConverter(Int64):
    async def convert(self, ctx: mido_utils.Context, bet_amount: str) -> int:
        # make sure db objects are attached
        await ctx.attach_db_objects()

        # TODO: add 'k' support
        if isinstance(bet_amount, str) and not bet_amount.isdigit():
            if bet_amount == 'all':
                bet_amount = int(ctx.user_db.cash)
            elif bet_amount == 'half':
                bet_amount = int(ctx.user_db.cash / 2)
            else:
                raise commands.BadArgument("Please input a proper amount! (`all` or `half`)")

        # make sure it's within 64 bits
        bet_amount = await super().convert(ctx, str(bet_amount))

        if bet_amount > ctx.user_db.cash:
            raise mido_utils.InsufficientCash
        elif bet_amount <= 0:
            raise commands.BadArgument("The amount can not be less than or equal to 0!")
        else:
            await ctx.user_db.remove_cash(bet_amount, reason=f"Used for {ctx.command.name}.")
            return bet_amount


def readable_bigint(number: int | float, small_precision=False) -> str:
    if small_precision:
        return '{:,.2f}'.format(number).rstrip('0').rstrip('.')
    else:
        return '{:,f}'.format(number).rstrip('0').rstrip('.')


def readable_currency(number: int) -> str:
    return readable_bigint(number) + mido_utils.emotes.currency


async def parse_text_with_context(text: str, bot,
                                  guild: discord.Guild,
                                  channel: discord.TextChannel,
                                  author: discord.Member = None,
                                  message_obj: discord.Message = None) -> tuple[str | None, discord.Embed | None]:
    # missing or not-properly-working placeholders:
    # misc stuff
    # local time stuff

    bot_member: discord.Member = guild.me

    base_dict = {}

    # bot placeholders
    base_dict.update(
        {
            # old
            "%mention%"    : bot_member.mention,
            "%time%"       : datetime.utcnow().strftime('%Y-%m-%d, %H:%M:%S UTC'),

            # new
            "%bot.status%" : str(bot_member.status),
            "%bot.latency%": bot.latency,
            "%bot.name%"   : bot_member.display_name,
            "%bot.mention%": bot_member.mention,
            "%bot.fullname%": str(bot_member),
            "%bot.time%"    : datetime.utcnow().strftime('%Y-%m-%d, %H:%M:%S UTC'),
            "%bot.discrim%" : str(bot_member).split('#')[-1],
            "%bot.id%"      : bot_member.id,
            "%bot.avatar%" : bot_member.display_avatar.url
        }
    )

    # guild placeholders
    base_dict.update(
        {
            # old
            "%shardid%"       : guild.shard_id,

            # new
            "%server.id%"     : guild.id,
            "%server.name%"   : guild.name,
            "%server.members%": guild.member_count if hasattr(guild, '_member_count') else 0,
            "%server.time%"   : datetime.utcnow().strftime('%Y-%m-%d, %H:%M:%S UTC'),
        }
    )

    # channel placeholders
    if isinstance(channel, discord.TextChannel):
        base_dict.update(
            {
                "%channel.mention%": channel.mention,
                "%channel.name%"   : channel.name,
                "%channel.id%"     : channel.id,
                "%channel.created%": channel.created_at.strftime('%Y-%m-%d, %H:%M:%S UTC'),
                "%channel.nsfw%"   : channel.is_nsfw(),
                "%channel.topic%"  : channel.topic
            }
        )

    # user placeholders
    if author:
        base_dict.update(
            {
                # old
                "%user%"             : author.mention,

                # new
                "%user.mention%"     : author.mention,
                "%user.fullname%"    : str(author),
                "%user.name%"        : author.display_name,
                "%user.discrim%"     : str(author).split('#')[-1],
                "%user.avatar%"      : author.display_avatar.url,
                "%user.id%"          : author.id,
                "%user.created_time%": author.created_at.strftime('%Y-%m-%d, %H:%M:%S UTC'),
                "%user.created_date%": author.created_at.strftime('%Y-%m-%d, %H:%M:%S UTC'),
                "%user.joined_time%" : author.joined_at.strftime(
                    '%Y-%m-%d, %H:%M:%S UTC') if author.joined_at else 'None',
                "%user.joined_date%" : author.joined_at.strftime(
                    '%Y-%m-%d, %H:%M:%S UTC') if author.joined_at else 'None'
            }
        )

    # bot stats placeholders
    clusters = await bot.ipc.get_cluster_stats()

    base_dict.update(
        {
            "%servers%": mido_utils.readable_bigint(sum(x.guilds for x in clusters)),
            "%users%"  : mido_utils.readable_bigint(sum(x.members for x in clusters))
        }
    )

    # shard stats placeholders
    shard: ShardInfo = bot.get_shard(guild.shard_id)
    base_dict.update(
        {
            "%shard.servercount%": len([g for g in bot.guilds if g.shard_id == shard.id]),
            "%shard.usercount%"  : sum(
                [g.member_count for g in bot.guilds if g.shard_id == shard.id and hasattr(g, '_member_count')]),
            "%shard.id"          : shard.id
        }
    )

    # Miscellaneous placeholders
    if message_obj:
        base_dict.update(
            {
                "%target%": message_obj.mentions[0].mention if message_obj.mentions else ''
            }
        )

    for placeholder, to_place in base_dict.items():
        text = text.replace(placeholder, str(to_place))

    try:
        embed: dict = json.loads(text)
        if not isinstance(embed, dict):  # avoid loads returning something else (such as int)
            raise NotDict
    except (json.JSONDecodeError, NotDict):
        return text, None
    else:
        # plainText is for legacy messages
        content = embed.get('plainText', None) or embed.get('content', None)
        embed = embed.get('embed', None) or embed

        # if image/thumbnail is just a str, we need to convert it to dict
        # legacy, again
        for field in ('image', 'thumbnail'):
            if field in embed.keys() and isinstance(embed[field], str):
                embed[field] = {'url': embed[field]}

        try:
            embed: discord.Embed = discord.Embed.from_dict(embed)
        except ValueError:
            # probably wrong timestamp
            embed.pop('timestamp')
            embed: discord.Embed = discord.Embed.from_dict(embed)

        return content, embed


def html_to_discord(text: str):
    a = {
        "<b>"   : "**",
        "<i>"   : "*",
        "<del>" : "~~",
        "<ins>" : "__",
        "&nbsp;": " "
    }

    for start, to_place in a.items():
        end = start[0] + '/' + start[1:]

        text = text.replace(start, str(to_place))
        text = text.replace(end, str(to_place))

    # todo: fix consecutive html tags
    # for d in a.values():
    #     if d*2 in text:
    #         text = text.replace(d*2, d + ' ')

    return text


class ChannelConverter(commands.TextChannelConverter):
    async def convert(self, ctx: mido_utils.Context, argument: str) -> discord.abc.Messageable:
        if argument.casefold() in ['me', 'dm'] or isinstance(ctx.channel, discord.DMChannel):
            channel = ctx.author

        elif argument.casefold() == 'here':
            channel = ctx.channel

        else:
            try:
                channel = await super().convert(ctx, argument)
            except commands.ChannelNotFound:
                channel = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.text_channels)

            if not channel:
                raise commands.ChannelNotFound(argument)

        return channel
