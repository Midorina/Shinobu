import asyncio

import discord

import mido_utils
from models import ReminderDB
from ._base_service import BaseShinobuService


class ReminderService(BaseShinobuService):
    def __init__(self, bot):
        super(ReminderService, self).__init__(bot)

        self.active_reminders = list()

        self.launch_reminders_task = self.bot.loop.create_task(self.launch_reminders())

    async def launch_reminders(self):
        await self.bot.wait_until_ready()

        reminders = await ReminderDB.get_uncompleted_reminders(bot=self.bot)

        for reminder in reminders:
            self.add_reminder(reminder)

    def add_reminder(self, reminder: ReminderDB):
        task = self.bot.loop.create_task(self.complete_reminder(reminder), name=str(reminder.id))
        task.add_done_callback(self.task_complete)

        self.active_reminders.append(task)

    def cancel_reminder(self, reminder: ReminderDB):
        # find the repeater
        for task in self.active_reminders:
            if task.get_name() == str(reminder.id):
                task.cancel()
                self.active_reminders.remove(task)

    async def complete_reminder(self, reminder: ReminderDB):
        # sleep until its time
        await asyncio.sleep(delay=reminder.time_obj.remaining_seconds)

        channel = author = self.bot.get_user(reminder.author_id)
        # value has to be used due to importlib bug
        if reminder.channel_type.value != ReminderDB.ChannelType.DM.value:
            channel = self.bot.get_channel(reminder.channel_id)

        if not channel:
            return await reminder.complete()

        e = mido_utils.Embed(bot=self.bot,
                             title="A Friendly Reminder:",
                             description=reminder.content)
        e.add_field(name="Creator",
                    value=f"**{str(author)}**")
        e.add_field(name="Creation Date",
                    value=f"{reminder.time_obj.start_date_string}\n"
                          f"(**{reminder.time_obj.initial_remaining_string} ago**)")

        try:
            await channel.send(embed=e)
        except discord.Forbidden:
            pass

        await reminder.complete()

    def task_complete(self, task):
        try:
            if task.exception():
                task.print_stack()
        except asyncio.CancelledError:
            pass

        try:
            self.active_reminders.remove(task)
        except ValueError:
            pass

    def stop(self):
        self.launch_reminders_task.cancel()

        for task in self.active_reminders:
            task.cancel()

        self.active_reminders = list()
