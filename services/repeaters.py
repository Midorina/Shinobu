import asyncio

import discord

import mido_utils
from models import RepeatDB
from ._base_service import BaseShinobuService


class RepeaterService(BaseShinobuService):
    def __init__(self, bot):
        super(RepeaterService, self).__init__(bot)

        self.active_repeaters = list()

        self.launch_repeaters_task = self.bot.loop.create_task(self.launch_repeaters())

    async def launch_repeaters(self):
        await self.bot.wait_until_ready()

        repeaters = await RepeatDB.get_all(bot=self.bot)

        for repeater in repeaters:
            self.add_repeater(repeater)

    def add_repeater(self, repeater: RepeatDB):
        task = self.bot.loop.create_task(self.process_repeater(repeater), name=str(repeater.id))
        task.add_done_callback(self.task_complete)

        self.active_repeaters.append(task)

    def cancel_repeater(self, reminder: RepeatDB):
        # find the repeater
        for task in self.active_repeaters:
            if task.get_name() == str(reminder.id):
                task.cancel()
                self.active_repeaters.remove(task)

    # TODO: don't post if the last message in that channel is our repeater message. (if user wants)
    async def process_repeater(self, repeater: RepeatDB):
        # sleep until its time
        last_message: discord.Message = None
        while True:
            interval = mido_utils.Time.add_to_previous_date_and_get(
                previous_date=repeater.last_post_date.start_date, seconds=repeater.post_interval)

            await asyncio.sleep(delay=interval.remaining_seconds)

            if not repeater.channel:
                return await repeater.delete()

            # fetch last msg if we dont have it
            if last_message is None and repeater.last_post_message_id:
                try:
                    last_message = await repeater.channel.fetch_message(repeater.last_post_message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    pass

            # parse the content
            content, embed = await mido_utils.parse_text_with_context(text=repeater.message,
                                                                      bot=self.bot,
                                                                      guild=repeater.guild,
                                                                      channel=repeater.channel)
            # delete last message if we have it
            if last_message and repeater.delete_previous is True:
                try:
                    await last_message.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass

            # post the repeater message
            try:
                last_message = await repeater.channel.send(content=f'🔁 {content}', embed=embed)
            except discord.Forbidden:
                return await repeater.delete()

            # update last post id and last post message id in db
            await repeater.just_posted(last_message.id)

    def task_complete(self, task):
        try:
            if task.exception():
                task.print_stack()
        except asyncio.CancelledError:
            pass

        try:
            self.active_repeaters.remove(task)
        except ValueError:
            pass

    def stop(self):
        self.launch_repeaters_task.cancel()

        for task in self.active_repeaters:
            task.cancel()

        self.active_repeaters = list()
