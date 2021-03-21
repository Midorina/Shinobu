import asyncio
from typing import Union

import discord
from discord.ext import commands

import mido_utils
from midobot import MidoBot
from models.db import ReminderDB


class Reminder(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.active_reminders = list()

        self.check_db_reminders_task = self.bot.loop.create_task(self.check_db_reminders())

    async def check_db_reminders(self):
        reminders = await ReminderDB.get_uncompleted_reminders(bot=self.bot)

        for reminder in reminders:
            self.add_reminder(reminder)

    async def complete_reminder(self, reminder: ReminderDB):
        # sleep until its time
        await asyncio.sleep(delay=reminder.time_obj.remaining_seconds)

        channel = author = self.bot.get_user(reminder.author_id)

        if reminder.channel_type != ReminderDB.ChannelType.DM:
            channel = self.bot.get_channel(reminder.channel_id)

        if not channel:
            return

        e = mido_utils.Embed(bot=self.bot,
                             title="A Friendly Reminder:",
                             description=reminder.content)
        e.add_field(name="Creator",
                    value=f"**{str(author)}**")
        e.add_field(name="Creation Date",
                    value=f"{reminder.time_obj.start_date_string}\n"
                          f"(**{reminder.time_obj.initial_remaining_string} ago**)")

        await channel.send(embed=e)
        await reminder.complete()

    def add_reminder(self, reminder: ReminderDB):
        task = self.bot.loop.create_task(self.complete_reminder(reminder), name=str(reminder.id))

        self.active_reminders.append(task)

    def cancel_reminder(self, reminder: ReminderDB):
        # find the reminder
        for task in self.active_reminders:
            if task.get_name() == str(reminder.id):
                task.cancel()
                self.active_reminders.remove(task)

    def cog_unload(self):
        self.check_db_reminders_task.cancel()

        for task in self.active_reminders:
            task.cancel()

        self.active_reminders = list()

    @commands.command()
    async def remind(self,
                     ctx: mido_utils.Context,
                     channel: Union[discord.TextChannel, str],
                     length: mido_utils.Time,
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
            channel_type = ReminderDB.ChannelType.TEXT_CHANNEL
        else:
            if channel.casefold() == 'me' or isinstance(ctx.channel, discord.DMChannel):
                channel = ctx.author
                channel_id = ctx.author.id
                channel_type = ReminderDB.ChannelType.DM

            elif channel.casefold() == 'here':
                channel = ctx.channel
                channel_id = ctx.channel.id
                channel_type = ReminderDB.ChannelType.TEXT_CHANNEL

            else:
                raise commands.BadArgument("Incorrect channel! Please input either `me` or specify a channel.")

        reminder = await ReminderDB.create(bot=ctx.bot, author_id=ctx.author.id,
                                           channel_id=channel_id,
                                           channel_type=channel_type,
                                           content=str(message),
                                           date_obj=length)
        self.add_reminder(reminder)

        e = mido_utils.Embed(bot=ctx.bot,
                             description=f"Success! "
                                         f"**{channel.mention}** will be reminded "
                                         f"to **{message}** in "
                                         f"**{length.initial_remaining_string}**.",
                             timestamp=reminder.time_obj.end_date)
        e.set_footer(text="In your timezone, this will execute")

        await ctx.send(embed=e)

    @commands.command()
    async def remindlist(self,
                         ctx: mido_utils.Context):
        """See the list of your reminders."""
        reminders = await ReminderDB.get_uncompleted_reminders(bot=ctx.bot, user_id=ctx.author.id)

        if not reminders:
            raise commands.UserInputError("You don't have any reminders!")

        e = mido_utils.Embed(self.bot)
        e.set_author(name=f"{ctx.author}'s Reminders", icon_url=ctx.author.avatar_url)

        blocks = []
        for i, reminder in enumerate(reminders, 1):
            block = f'**#{i}**\n' \
                    f'`Remaining:` **{reminder.time_obj.remaining_string}** ({reminder.time_obj.end_date_string})\n'

            if reminder.channel_type == ReminderDB.ChannelType.DM:
                block += f'`Channel:` **DM**\n'
            else:
                block += f'`Channel:` <#{reminder.channel_id}>\n'

            block += f'`Message:` {reminder.content}'

            blocks.append(block)

        await e.paginate(ctx, blocks, extra_sep='\n')

    @commands.command(aliases=['reminddel'])
    async def reminddelete(self,
                           ctx: mido_utils.Context,
                           reminder_index: int):
        """
        Delete a reminder you have using its index.

        You can see a complete list of your reminders and their indexes using `{0.prefix}remindlist`
        """

        reminders = await ReminderDB.get_uncompleted_reminders(bot=ctx.bot, user_id=ctx.author.id)

        if not reminders:
            raise commands.UserInputError("You don't have any reminders!")

        try:
            reminder_to_remove = reminders[reminder_index - 1]
        except IndexError:
            raise commands.UserInputError("Invalid reminder index!")

        self.cancel_reminder(reminder_to_remove)
        await reminder_to_remove.complete()

        await ctx.send_success(f"Reminder **#{reminder_index}** has been successfully deleted.")


def setup(bot):
    bot.add_cog(Reminder(bot))
