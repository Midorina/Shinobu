import json
from datetime import datetime
from typing import Union

import discord
from discord import ShardInfo

from midobot import MidoBot
from services.music import VoicePlayer


def parse_text_with_context(text: str, bot: MidoBot, guild: discord.Guild, author: discord.Member,
                            channel: discord.TextChannel,
                            message_obj: discord.Message = None) -> Union[str, discord.Embed]:
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

    # noinspection PyTypeChecker
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
        embed = json.loads(text)
        return discord.Embed.from_dict(embed)
    except json.JSONDecodeError:

        return text
