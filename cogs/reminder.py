import asyncio
from typing import Union

import discord
from discord.ext import commands

from db.models import Reminder
from main import MidoBot
from services.base_embed import BaseEmbed
from services.context import MidoContext
from services.time import MidoTime


class ReminderCog(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.active_reminders = list()

        self.bot.loop.create_task(self.check_db_reminders())

    async def check_db_reminders(self):
        reminders = await Reminder.get_uncompleted_reminders(self.bot.db)

        for reminder in reminders:
            self.add_reminder(reminder)

    async def complete_reminder(self, reminder: Reminder):
        # sleep until its time
        await asyncio.sleep(delay=reminder.time_obj.remaining_seconds)

        author = self.bot.get_user(reminder.author_id)

        if reminder.channel_type == Reminder.ChannelType.DM:
            channel = self.bot.get_user(reminder.channel_id)
        else:
            channel = self.bot.get_channel(reminder.channel_id)

        e = BaseEmbed(bot=self.bot,
                      title="A Friendly Reminder:",
                      description=reminder.content)
        e.add_field(name="Creator",
                    value=f"**{str(author)}**")
        e.add_field(name="Creation Date",
                    value=f"{reminder.time_obj.start_date_string}\n"
                          f"(**{reminder.time_obj.initial_remaining_string} ago**)")

        await channel.send(embed=e)
        await reminder.complete()

    def add_reminder(self, reminder: Reminder):
        task = self.bot.loop.create_task(self.complete_reminder(reminder), name=reminder.id)

        self.active_reminders.append(task)

    def cancel_reminder(self, reminder: Reminder):
        # find the reminder
        for task in self.active_reminders:
            if task.get_name() == reminder.id:
                task.cancel()
                self.active_reminders.remove(task)

    @commands.command()
    async def remind(self,
                     ctx: MidoContext,
                     channel: Union[discord.TextChannel, str],
                     length: MidoTime,
                     *, message: commands.clean_content):
        """Adds a reminder.

        Use `me` as the channel to get the reminder in your DMs.
        Use `here` as the channel to get the reminder in the current channel.
        You can specify any other text channel to get the reminder on there.

        **Examples:**
            `{0.prefix}remind me 10m check the oven.`
            `{0.prefix}remind here 1h30m party!`
            `{0.prefix}remind #general 12h Avengers spoilers are no longer forbidden.`

        **Available time length letters:**
            `s` -> seconds
            `m` -> minutes
            `h` -> hours
            `d` -> days
            `w` -> weeks
            `mo` -> months
        """
        if isinstance(channel, discord.TextChannel):
            channel_id = channel.id
            channel_type = Reminder.ChannelType.TEXT_CHANNEL
        else:
            if channel == 'me' or isinstance(ctx.channel, discord.DMChannel):
                channel = ctx.author
                channel_id = ctx.author.id
                channel_type = Reminder.ChannelType.DM

            elif channel == 'here':
                channel = ctx.channel
                channel_id = ctx.channel.id
                channel_type = Reminder.ChannelType.TEXT_CHANNEL

            else:
                raise commands.BadArgument("Incorrect channel! Please input either `me` or specify a channel.")

        reminder = await Reminder.create(ctx.db, author_id=ctx.author.id,
                                         channel_id=channel_id,
                                         channel_type=channel_type,
                                         content=str(message),
                                         date_obj=length)
        self.add_reminder(reminder)

        await ctx.send(f"Success! "
                       f"**{channel.mention}** will be reminded "
                       f"to **{message}** in "
                       f"**{length.initial_remaining_string}**. `{length.end_date_string}`")


# TODO: add ways

def setup(bot):
    bot.add_cog(ReminderCog(bot))
