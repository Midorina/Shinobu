from discord.ext import commands
import discord
import time
import os
from services import checks
from datetime import datetime, timedelta
import psutil


class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        if ctx.guild:
            color = ctx.guild.me.top_role.color
        else:
            color = discord.Colour.dark_grey()

        before = time.monotonic()

        embed_msg = discord.Embed(title="Ping!", description=f"Latency: `... ms`", color=color)
        message = await ctx.send(embed=embed_msg)

        ping = (time.monotonic() - before) * 1000
        new_embed_msg = discord.Embed(title="🏓 Pong!", description=f"Latency: `{int(ping)} ms`", color=color)

        await message.edit(embed=new_embed_msg)

    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @commands.command()
    async def prefix(self, ctx, *, prefix: str = None):
        if prefix:
            await self.bot.db.execute(
                """UPDATE guilds SET prefix=$1 where id=$2""", prefix, ctx.guild.id
            )

            await ctx.send(f"The prefix has been successfully changed to **{prefix}**")
            return

        else:
            prefix = await self.bot.db.fetchrow(
                """select prefix from guilds where id=$1""", ctx.guild.id
            )

            await ctx.send(f"Current prefix for this server: **{prefix['prefix']}**")
            return

    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @commands.command(name="deletecommands", aliases=["delcmds"])
    async def delete_commands(self, ctx):
        status = await self.bot.db.fetchrow(
            """SELECT * from guilds where id=$1""", ctx.guild.id
        )

        status = status["delete_commands"]

        if status is False:
            await self.bot.db.execute(
                """UPDATE guilds SET delete_commands=$1 where id=$2""", True, ctx.guild.id
            )

            await ctx.send(f"The successful commands will be deleted from now on.")

        else:
            await self.bot.db.execute(
                """UPDATE guilds SET delete_commands=$1 where id=$2""", False, ctx.guild.id
            )

            await ctx.send(f"The successful commands will not be deleted from now on.")

    @commands.command()
    async def stats(self, ctx):
        owner = self.bot.get_user(90076279646212096)

        uptime = self.bot.uptime
        days = 0
        hours = 0
        minutes = 0

        # total_shards = len(self.bot.shard_ids)
        # if ctx.guild:
        #     current_shard = ctx.guild.shard_id
        # else:
        #     current_shard = 0

        current_time = datetime.utcnow()
        time_difference = current_time - uptime
        time_difference_in_minutes = time_difference / timedelta(minutes=1)

        messages_per_sec = self.bot.message_counter / (60 * time_difference_in_minutes)

        if time_difference_in_minutes > 1440:
            days += int(time_difference_in_minutes // 1440)
            time_difference_in_minutes -= days * 1440

        if time_difference_in_minutes > 60:
            hours += int(time_difference_in_minutes // 60)
            time_difference_in_minutes -= hours * 60

        minutes += int(time_difference_in_minutes)

        memory = psutil.virtual_memory()[3]
        memory = memory >> 20

        embed = discord.Embed()
        embed.set_author(name=f"{self.bot.user}",
                         icon_url=self.bot.user.avatar_url)

        embed.add_field(name="Owner",
                        value=f"{str(owner)}\n"
                              f"(439632807770325012)",
                        inline=True)

        embed.add_field(name="Guild Count",
                        value=str(len(self.bot.guilds)),
                        inline=True)

        embed.add_field(name="Messages",
                        value=f"{self.bot.message_counter}\n({round(messages_per_sec, 2)}/sec)",
                        inline=True)

        embed.add_field(name="Memory",
                        value=str(memory) + " MB",
                        inline=True)

        embed.add_field(name="Commands ran",
                        value=self.bot.command_counter,
                        inline=True)

        embed.add_field(name="Uptime",
                        value=f"{days} days\n"
                              f"{hours} hours\n"
                              f"{minutes} minutes",
                        inline=True)
        # embed.add_field(name="Shard",
        #                 value=f"#{current_shard} / {total_shards}",
        #                 inline=True)

        await ctx.send(embed=embed)

    @commands.command()
    @checks.owner_only()
    async def reload(self, ctx):
        for file in os.listdir("cogs"):
            if file.endswith(".py"):
                name = file[:-3]
                try:
                    self.bot.reload_extension(f"cogs.{name}")
                except discord.ext.commands.ExtensionNotLoaded:
                    self.bot.load_extension(f"cogs.{name}")

        await ctx.send("Successfully reloaded all cogs!")

    @commands.command()
    async def servers(self, ctx):
        msg = ""
        for guild in self.bot.guilds:
            msg += f"{str(guild)} \n"

        await ctx.send(msg)


def setup(bot):
    bot.add_cog(Misc(bot))
