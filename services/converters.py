import json
from datetime import datetime
from typing import Optional

import discord
from discord import ShardInfo
from discord.ext import commands

from midobot import MidoBot
from services.context import MidoContext
from services.exceptions import InsufficientCash
from services.music import VoicePlayer
from services.resources import Resources


class MidoMemberConverter(commands.MemberConverter):
    async def convert(self, ctx: MidoContext, argument) -> discord.Member:
        try:
            member = await super().convert(ctx, argument)
        except commands.BadArgument:
            if argument.isdigit():
                member = ctx.bot.get_user(int(argument))
            else:  # if its a string
                member = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.members)

            if not member:
                raise commands.MemberNotFound(argument)

        return member


class MidoRoleConverter(commands.RoleConverter):
    async def convert(self, ctx: MidoContext, argument) -> discord.Role:
        try:
            role = await super().convert(ctx, argument)
        except commands.BadArgument:
            role = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.roles)

        if not role:
            raise commands.RoleNotFound(argument)

        return role


async def ensure_not_broke_and_parse_bet(ctx: MidoContext, bet_amount: str) -> int:
    if isinstance(bet_amount, str):
        if bet_amount == 'all':
            bet_amount = int(ctx.user_db.cash)
        elif bet_amount == 'half':
            bet_amount = int(ctx.user_db.cash / 2)
        else:
            raise commands.BadArgument("Please input a proper amount! (`all` or `half`)")

    if bet_amount > ctx.user_db.cash:
        raise InsufficientCash
    elif bet_amount <= 0:
        raise commands.BadArgument("The amount can not be less than or equal to 0!")
    else:
        await ctx.user_db.remove_cash(bet_amount, reason=f"Used for {ctx.command.name}.")
        return bet_amount


def readable_bigint(number: int) -> str:
    return '{:,}'.format(number)


def readable_currency(number: int) -> str:
    return readable_bigint(number) + Resources.emotes.currency


def parse_text_with_context(text: str, bot: MidoBot, guild: discord.Guild, author: discord.Member,
                            channel: discord.TextChannel,
                            message_obj: discord.Message = None) -> (str, Optional[discord.Embed]):
    # missing or not-properly-working placeholders:
    # misc stuff
    # local time stuff

    bot_member: discord.Member = guild.me

    base_dict = {}

    # bot placeholders
    base_dict.update(
        {
            # old
            "%mention%"     : bot_member.mention,
            "%time%"        : datetime.utcnow().strftime('%Y-%m-%d, %H:%M:%S UTC'),

            # new
            "%bot.status%"  : str(bot_member.status),
            "%bot.latency%" : bot.latency,
            "%bot.name%"    : bot_member.display_name,
            "%bot.mention%" : bot_member.mention,
            "%bot.fullname%": str(bot_member),
            "%bot.time%"    : datetime.utcnow().strftime('%Y-%m-%d, %H:%M:%S UTC'),
            "%bot.discrim%" : str(bot_member).split('#')[-1],
            "%bot.id%"      : bot_member.id,
            "%bot.avatar%"  : bot_member.avatar_url
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
            "%server.members%": guild.member_count,
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
    base_dict.update(
        {
            # old
            "%user%"             : author.mention,

            # new
            "%user.mention%"     : author.mention,
            "%user.fullname%"    : str(author),
            "%user.name%"        : author.display_name,
            "%user.discrim%"     : str(author).split('#')[-1],
            "%user.avatar%"      : author.avatar_url,
            "%user.id%"          : author.id,
            "%user.created_time%": author.created_at.strftime('%Y-%m-%d, %H:%M:%S UTC'),
            "%user.created_date%": author.created_at.strftime('%Y-%m-%d, %H:%M:%S UTC'),
            "%user.joined_time%" : author.joined_at.strftime('%Y-%m-%d, %H:%M:%S UTC'),
            "%user.joined_date%" : author.joined_at.strftime('%Y-%m-%d, %H:%M:%S UTC')
        }
    )

    # bot stats placeholders
    base_dict.update(
        {
            "%servers%": len(bot.guilds),
            "%users%"  : sum([guild.member_count for guild in bot.guilds])
        }
    )

    # shard stats placeholders
    shard: ShardInfo = bot.get_shard(guild.shard_id)
    base_dict.update(
        {
            "%shard.servercount%": len([g for g in bot.guilds if g.shard_id == shard.id]),
            "%shard.usercount%"  : sum([g.member_count for g in bot.guilds if g.shard_id == shard.id]),
            "%shard.id"          : shard.id
        }
    )

    voice_player: VoicePlayer = bot.wavelink.get_player(guild.id, cls=VoicePlayer)
    if voice_player.is_playing:
        base_dict.update(
            {
                "%music.queued%" : len(voice_player.song_queue),
                "%music.playing%": voice_player.current.title,
            }
        )

    # Miscellaneous placeholders
    if message_obj:
        base_dict.update(
            {
                "%target%": message_obj.mentions[0].mention if message_obj.mentions else ''
            }
        )

    for ph, to_place in base_dict.items():
        text = text.replace(ph, str(to_place))

    try:
        embed: dict = json.loads(text)
        if not isinstance(embed, dict):  # avoid loads returning something else (such as int)
            raise json.JSONDecodeError
    except json.JSONDecodeError:
        return text, None
    else:
        # plainText is for legacy messages
        content = embed.get('plainText', None) or embed.get('content', None)
        embed = embed.get('embed', None) or embed

        return content, discord.Embed.from_dict(embed)


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
