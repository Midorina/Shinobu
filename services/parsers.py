import json
from datetime import datetime

import discord

from midobot import MidoBot


def parse_text_with_context(response: str, message_obj: discord.Message, bot: MidoBot) -> str:
    try:
        embed = json.loads(response)
        return discord.Embed.from_dict(embed)
    except json.JSONDecodeError:
        bot_member = message_obj.guild.me
        parse_dict = {
            # old
            "%mention%"    : bot_member.mention,
            # new
            "%bot.mention%": bot_member.mention,

            # old
            "%shardid%"    : message_obj.guild.shard_id,
            "%time%"       : datetime.utcnow().strftime('%Y-%m-%d, %H:%M:%S UTC'),
            # new
            "%bot.status%" : str(bot_member.status),
            "%bot.latency%": bot.latency,

            # old
            "%user%"       : message_obj.author.mention,
            "%target%"     : message_obj.mentions[0].mention if message_obj.mentions else '',
        }
        # todo: complete this

        for ph, to_place in parse_dict.items():
            response = response.replace(ph, str(to_place))

        return response
