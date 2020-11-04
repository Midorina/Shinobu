import json

from discord.ext import commands

with open('config.json') as f:
    config = json.load(f)


def owner_only():
    def pred(ctx):
        return is_owner(ctx.author.id)

    return commands.check(pred)


def is_owner(user_id: int):
    return user_id in config['owner_ids']
