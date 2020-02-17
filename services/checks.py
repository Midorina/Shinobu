from discord.ext import commands
import json

with open('config.json') as f:
    config = json.load(f)


def owner_only():
    def pred(ctx):
        if ctx.author.id in config["owners"]:
            return True

    return commands.check(pred)
