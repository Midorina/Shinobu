from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import mido_utils
import services
from models.db import ReminderDB, RepeatDB

if TYPE_CHECKING:
    from shinobu import ShinobuBot


# todo: share reminders across clusters so that not all of them send a message

class Reminder(commands.Cog, description='Use `{ctx.prefix}remind` to remind yourself or someone of something.'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.reminder_service = services.ReminderService(self.bot)
        self.repeater_service = services.RepeaterService(self.bot)

    def cog_unload(self):
        self.reminder_service.stop()
        self.repeater_service.stop()

    @commands.hybrid_command()
    async def remind(self,
                     ctx: mido_utils.Context,
                     channel: mido_utils.ChannelConverter,
                     length: mido_utils.Time,
                     *, message: commands.clean_content):
        """Adds a reminder.

        Use `me` as the channel to get the reminder in your DMs.
        Use `here` as the channel to get the reminder in the current channel.
        You can specify any other text channel to get the reminder on there.

        **Examples:**
            `{ctx.prefix}remind me 10m check the oven.`
            `{ctx.prefix}remind here 1h30m party!`
            `{ctx.prefix}remind #general 12h Avengers spoilers are no longer forbidden.`

        **Available time length letters:**
            `s` -> seconds
            `m` -> minutes
            `h` -> hours
            `d` -> days
            `w` -> weeks
            `mo` -> months
        """
        channel: discord.TextChannel | discord.DMChannel

        channel_id = channel.id
        channel_type = ReminderDB.ChannelType.DM if isinstance(channel,
                                                               discord.DMChannel) else ReminderDB.ChannelType.TEXT_CHANNEL

        reminder = await ReminderDB.create(bot=ctx.bot, author_id=ctx.author.id,
                                           channel_id=channel_id,
                                           channel_type=channel_type,
                                           content=str(message),
                                           date_obj=length)
        self.reminder_service.add_reminder(reminder)

        e = mido_utils.Embed(bot=ctx.bot,
                             description=f"Success! "
                                         f"**{channel.mention}** will be reminded "
                                         f"to **{message}** in "
                                         f"**{length.initial_remaining_string}**.",
                             timestamp=reminder.time_obj.end_date)
        e.set_footer(text="In your timezone, this will execute")

        await ctx.send(embed=e)

    @commands.hybrid_command()
    async def remindlist(self,
                         ctx: mido_utils.Context):
        """See the list of your reminders."""
        reminders = await ReminderDB.get_uncompleted_reminders(bot=ctx.bot, user_id=ctx.author.id)

        if not reminders:
            raise commands.UserInputError("You don't have any reminders!")

        e = mido_utils.Embed(self.bot)
        e.set_author(name=f"{ctx.author}'s Reminders", icon_url=ctx.author.avatar.url)

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

    @commands.hybrid_command(aliases=['reminddel'])
    async def reminddelete(self,
                           ctx: mido_utils.Context,
                           reminder_index: int):
        """
        Delete a reminder you have using its index.

        You can see a complete list of your reminders and their indexes using `{ctx.prefix}remindlist`
        """

        reminders = await ReminderDB.get_uncompleted_reminders(bot=ctx.bot, user_id=ctx.author.id)

        if not reminders:
            raise commands.UserInputError("You don't have any reminders!")

        try:
            reminder_to_remove = reminders[reminder_index - 1]
        except IndexError:
            raise commands.UserInputError("Invalid reminder index!")

        self.reminder_service.cancel_reminder(reminder_to_remove)
        await reminder_to_remove.complete()

        await ctx.send_success(f"Reminder **#{reminder_index}** has been successfully deleted.")

    @commands.hybrid_command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def repeat(self,
                     ctx: mido_utils.Context,
                     channel: mido_utils.ChannelConverter,
                     interval: mido_utils.Time,
                     *, message: str):
        """Adds a repeater.

        Use `here` as the channel to get the repeater in the current channel.
        You can specify any other text channel to get the repeater on there.

        An embed can be used. Check `{ctx.prefix}help acr` to get a link to create an embed structure and learn placeholders.

        **Examples:**
            `{ctx.prefix}repeat here 10m Please behave.`
            `{ctx.prefix}repeat #general 12h Please make sure you read rules.`

        **Available time length letters:**
            `s` -> seconds
            `m` -> minutes
            `h` -> hours
            `d` -> days
            `w` -> weeks
            `mo` -> months
        """
        channel: discord.TextChannel | discord.DMChannel

        if isinstance(channel, discord.DMChannel):
            raise commands.UserInputError("You can not create a repeater for your DMs. Sorry.")

        # interval check
        if interval.initial_remaining_seconds < 30:
            raise commands.UserInputError("Interval can not be less than 30 seconds. Sorry.")

        # repeater count check
        guild_repeaters = await RepeatDB.get_of_a_guild(ctx.bot, ctx.guild.id)
        if len(guild_repeaters) > 5:
            raise commands.UserInputError("You can't have more than 5 repeaters in a guild. Sorry.")

        repeater = await RepeatDB.create(bot=ctx.bot, channel_id=channel.id,
                                         guild_id=ctx.guild.id, message=message,
                                         post_interval=interval.initial_remaining_seconds,
                                         created_by_id=ctx.author.id)
        self.repeater_service.add_repeater(repeater)

        e = mido_utils.Embed(bot=ctx.bot,
                             description=f"Success! Your message will be repeated "
                                         f"every {interval.initial_remaining_string} in **{channel.mention}**.")
        await ctx.send(embed=e)

    @commands.hybrid_command()
    @commands.guild_only()
    async def repeatlist(self,
                         ctx: mido_utils.Context):
        """See the list of repeaters in this guild."""
        repeaters = await RepeatDB.get_of_a_guild(bot=ctx.bot, guild_id=ctx.guild.id)

        if not repeaters:
            raise commands.UserInputError("This guild does not have any repeaters.")

        e = mido_utils.Embed(self.bot)
        e.set_author(name=f"{ctx.guild}'s Repeaters", icon_url=ctx.guild.icon_url)

        blocks = []
        for i, repeater in enumerate(repeaters, 1):
            block = f'**#{i}**\n' \
                    f'`Channel:` <#{repeater.channel_id}>\n' \
                    f'`Every:` **{mido_utils.Time.parse_seconds_to_str(repeater.post_interval)}**\n' \
                    f'`Message:` {repeater.message[200:] + "..." if len(repeater.message) > 200 else repeater.message}\n' \
                    f'`Created by`: <@{repeater.created_by_id}>'

            blocks.append(block)

        await e.paginate(ctx, blocks, extra_sep='\n')

    @commands.hybrid_command(aliases=['repeatremove', 'repeatdel', 'repeatrm'])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def repeatdelete(self,
                           ctx: mido_utils.Context,
                           repeater_index: int):
        """
        Delete a repeater you have using its index.

        You can see a complete list of your repeater and their indexes using `{ctx.prefix}repeatlist`
        """

        repeaters = await RepeatDB.get_of_a_guild(bot=ctx.bot, guild_id=ctx.guild.id)

        if not repeaters:
            raise commands.UserInputError("This guild does not have any repeaters.")

        try:
            repeater_to_remove = repeaters[repeater_index - 1]
        except IndexError:
            raise commands.UserInputError("Invalid repeater index!")

        self.repeater_service.cancel_repeater(repeater_to_remove)
        await repeater_to_remove.delete()

        await ctx.send_success(f"Repeater **#{repeater_index}** has been successfully deleted.")


async def setup(bot: ShinobuBot):
    await bot.add_cog(Reminder(bot))
