import math
import random
from typing import List, Optional, Union

import discord
import topgg
from discord.ext import commands, tasks

import mido_utils
from models.db import DonutEvent, ReminderDB, TransactionLog, UserDB
from shinobu import ShinobuBot

DIGIT_TO_EMOJI = {
    0: ":zero:",
    1: ":one:",
    2: ":two:",
    3: ":three:",
    4: ":four:",
    5: ":five:",
    6: ":six:",
    7: ":seven:",
    8: ":eight:",
    9: ":nine:"
}

COIN_SIDES = {
    "heads": {
        "aliases": ['heads', 'head', 'h'],
        "images" : [
            "https://i.imgur.com/BcSMPgD.png"
        ]
    },
    "tails": {
        "aliases": ['tails', 'tail', 't'],
        "images" : [
            "https://i.imgur.com/bt3xeCq.png"
        ]
    }
}


class Gambling(
    commands.Cog,
    description='Use the `{ctx.prefix}daily` command to get '
                '**{bot.config.daily_amount}{mido_utils.emotes.currency}** and use them in gambling and other games!'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        # donut event stuff
        self.active_donut_events: List[DonutEvent] = list()
        self.active_donut_task = self.bot.loop.create_task(self.get_active_donut_events())

        # things that only cluster 0 provides
        if self.bot.cluster_id == 0:
            # Patreon
            if self.bot.config.patreon_credentials:
                self.patreon_api = mido_utils.PatreonAPI(self.bot, self.bot.config.patreon_credentials)

            # TOP.GG / DBL
            if self.bot.config.topgg_credentials:
                creds = self.bot.config.topgg_credentials

                self.topgg = topgg.DBLClient(self.bot, creds["token"], autopost=False)
                # use another bot id if provided
                self.topgg.bot_id = creds.get('bot_id')

                self.topgg_webhook = topgg.WebhookManager(self.bot).dbl_webhook(
                    creds["webhook_path"], creds["webhook_auth"])
                self.topgg_webhook.run(creds["webhook_port"])

                self.votes = set()

                if creds["post_guild_count"]:
                    self.post_guild_count.start()

    @tasks.loop(minutes=30.0)
    async def post_guild_count(self):
        """Manual posting is required due to clustering"""
        if hasattr(self, 'topgg'):
            await self.topgg.http.post_guild_count(
                guild_count=await self.bot.ipc.get_guild_count(),
                shard_count=None,
                shard_id=None)

    @post_guild_count.before_loop
    async def wait_for_bot_before_loop(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        if hasattr(self, 'topgg'):
            self.bot.loop.create_task(self.topgg.close())

        self.active_donut_task.cancel()

    async def get_active_donut_events(self):
        """This function gets active donut events and processes them"""
        await self.bot.wait_until_ready()

        self.active_donut_events = await DonutEvent.get_active_ones(self.bot)

        for donut_event in self.active_donut_events:
            msg_obj: discord.Message = await donut_event.fetch_message_object()

            # if we can't fetch the msg object or the end date has passed, delete
            if not msg_obj or donut_event.end_date.end_date_has_passed:
                await donut_event.delete_msg_and_mark_as_deleted()
                continue

            self.bot.loop.create_task(
                donut_event.delete_msg_and_mark_as_deleted(delay=donut_event.end_date.remaining_seconds))

            try:
                # find the event reaction obj
                event_reaction = next(x for x in msg_obj.reactions
                                      if str(x.emoji) == mido_utils.emotes.currency)
            except StopIteration:
                continue
            else:
                # get all users who reacted with event reaction
                users = await event_reaction.users().flatten()

                for user in users:
                    if donut_event.user_is_eligible(user):  # if we missed their reaction
                        await donut_event.reward_attender(attender_id=user.id)

    @commands.Cog.listener()
    async def on_dbl_vote(self, data):
        self.votes.add(int(data['user']))
        self.bot.logger.info(f'Received an upvote and its been added to the set! {data}')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        try:
            donut_event = next(x for x in self.active_donut_events if x.message_id == payload.message_id)
        except StopIteration:
            return
        else:
            if donut_event.end_date.end_date_has_passed is True:  # if expired
                channel: discord.TextChannel = self.bot.get_channel(donut_event.channel_id)
                msg_obj: discord.Message = await channel.fetch_message(donut_event.message_id)
                await msg_obj.delete()
                self.active_donut_events.remove(donut_event)
                return

            if str(payload.emoji) == mido_utils.emotes.currency:
                user = self.bot.get_user(payload.user_id)

                if donut_event.user_is_eligible(user):
                    await donut_event.reward_attender(attender_id=user.id)

    async def cog_command_error(self, ctx: mido_utils.Context, error):
        """This function handles the removed money taken in the ensure_not_broke_and_parse_bet_amount function."""

        # this is handled poorly. I'll overhaul this in the future. Hopefully no one finds an exploit until then.
        list_of_commands_that_removes_cash = [
            'give',
            'wheel',
            'betroll',
            'slots',
            'coinflip'
        ]
        cmds = [ctx.bot.get_command(x) for x in list_of_commands_that_removes_cash]

        if isinstance(error, (commands.UserInputError, commands.BadArgument)) \
                and not isinstance(error, commands.MissingRequiredArgument) \
                and ctx.command in cmds \
                and isinstance(ctx.args[2], int):  # if amount is parsed
            await ctx.user_db.add_cash(ctx.args[2], reason=f"Command '{ctx.command.name}' errored.")

    @commands.command(aliases=['$', 'money'])
    async def cash(self, ctx: mido_utils.Context, *, user: mido_utils.MemberConverter() = None):
        """Check how many donuts you have or someone else has."""
        if user:
            user_db = await UserDB.get_or_create(bot=ctx.bot, user_id=user.id)
        else:
            user = ctx.author
            user_db = ctx.user_db

        await ctx.send_success(f"**{user.mention}** has **{user_db.cash_str}**!")

    async def user_has_voted(self, user_id: int) -> bool:
        ret = False
        if hasattr(self, 'patreon_api'):
            ret = self.patreon_api.is_patron_and_can_claim_daily(user_id)

        if not ret:
            if hasattr(self, 'topgg'):
                ret = user_id in self.votes
                if not ret:
                    try:
                        ret = await self.topgg.get_user_vote(user_id)
                    except topgg.HTTPException:
                        # TODO: this is sometimes 403. inform the host properly
                        raise mido_utils.APIError("Top.gg API is down. Please try again later.")
            else:
                # if its cluster 0 but topgg attribute doesn't exist, return True
                return self.bot.cluster_id == 0

        return ret

    @commands.command()
    async def daily(self, ctx: mido_utils.Context):
        """
        Claim **{bot.configdaily_amount}{mido_utils.emotes.currency}** for free every 12 hours.
        """
        daily_status = ctx.user_db.daily_date_status
        daily_amount = self.bot.config.daily_amount

        if not daily_status.end_date_has_passed:
            raise mido_utils.OnCooldownError(
                f"You're on cooldown! Try again after **{daily_status.remaining_string}**.")

        if not await mido_utils.is_patron(ctx.bot, ctx.author.id, allow_owner=False):  # patron check
            if not await self.bot.ipc.user_has_voted(ctx.author.id):  # vote check
                raise mido_utils.DidntVoteError(
                    f"It seems like you haven't voted yet.\n\n"
                    f"Vote [here]({mido_utils.links.upvote}), "
                    f"then use this command again "
                    f"to get your **{mido_utils.readable_currency(daily_amount)}**!\n\n"
                    f"*You can receive dailies without voting and **{mido_utils.readable_currency(1500)}** "
                    f"by [donating just $1!]({mido_utils.links.patreon})*")

        if hasattr(self, 'votes'):
            try:
                self.votes.remove(ctx.author.id)
            except KeyError:
                pass

        await ctx.user_db.add_cash(daily_amount, reason="Claimed daily.", daily=True)

        base_msg = f"You've successfully claimed your daily **{mido_utils.readable_currency(daily_amount)}**!\n\n"

        m = await ctx.send_success(base_msg + "Would you like to get reminded when you can vote again?")

        yes = await mido_utils.Embed.yes_no(self.bot, ctx.author.id, m)
        if yes:
            reminder = await ReminderDB.create(
                bot=ctx.bot,
                author_id=ctx.author.id,
                channel_id=ctx.author.id,
                channel_type=ReminderDB.ChannelType.DM,
                content=f"Your daily is ready! You can vote [here]({mido_utils.links.upvote}).",
                date_obj=mido_utils.Time.add_to_current_date_and_get(seconds=self.bot.config.cooldowns['daily'])
            )
            ctx.bot.get_cog('Reminder').reminder_service.add_reminder(reminder)

            await ctx.edit_custom(m, base_msg + f"Success! I will remind you to get your daily again "
                                                f"in {reminder.time_obj.initial_remaining_string}.")
        else:
            await m.clear_reactions()
            await ctx.edit_custom(m, base_msg + f"Alright, you won't be reminded when you can get your daily again.")

    @commands.command(name='claimrewards', aliases=['claimpatreonrewards', 'clparew'])
    @mido_utils.is_patron_decorator(allow_owner=False)
    async def claim_patreon_rewards(self, ctx: mido_utils.Context):
        """Claim the donut reward you'll be getting by [supporting this project.]({mido_utils.links.patreon}) ♥"""
        patron_obj = await self.bot.ipc.get_patron(ctx.author.id)
        await ctx.user_db.claim_patreon_reward(patron_obj)
        await ctx.send_success(f"You've successfully claimed "
                               f"**{mido_utils.readable_currency(patron_obj.level_status.monthly_donut_reward)}**!")

    @commands.command(name="flip", aliases=['cf', 'coinflip', 'bf', 'betflip'])
    async def coin_flip(self, ctx: mido_utils.Context, amount: Union[int, str], guessed_side: str):
        """A coin flip game. You'll earn x1.95 of what you bet if you predict correctly.

        Sides and Aliases:
        **Heads**: `heads`, `head`, `h`
        **Tails**: `tails`, `tail`, `t`"""
        actual_guessed_side_name = None
        for side_name, properties in COIN_SIDES.items():
            if guessed_side.lower() in properties['aliases']:
                actual_guessed_side_name = side_name

        if not actual_guessed_side_name:
            raise commands.BadArgument("Incorrect coin side!")

        random_side_name = random.choice(list(COIN_SIDES.keys()))

        e = mido_utils.Embed(bot=ctx.bot)
        e.set_image(url=random.choice(COIN_SIDES[random_side_name]['images']))

        if actual_guessed_side_name == random_side_name:
            won_amount = int(amount * 1.95)

            await ctx.user_db.add_cash(won_amount, reason="Won coin flip game.")

            e.title = "Congratulations!"
            e.description = f"You flipped {random_side_name} and won **{mido_utils.readable_currency(won_amount)}**!"
            e.colour = mido_utils.Color.success()

        else:
            e.title = "I'm sorry..."
            e.description = f"You flipped {random_side_name} and lost **{mido_utils.readable_currency(amount)}**."
            e.colour = mido_utils.Color.fail()

        e.set_footer(icon_url=ctx.author.avatar_url, text=f"Current cash: {ctx.user_db.cash_str_without_emoji}")

        return await ctx.send(embed=e)

    @commands.command()
    async def wheel(self, ctx: mido_utils.Context, amount: Union[int, str]):
        """Turn the wheel!

        What you bet will be multiplied by what you hit and get back to you."""
        # TODO: use a code block an move "possibilities_and_arrows" to somewhere else
        possibilities_and_arrows = {
            1.5: '↖️',
            1.7: '⬆️',
            2.4: '↗️',
            0.2: '⬅️',
            1.2: '➡️',
            0.1: '↙️',
            0.3: '⬇️',
            0.5: '↘️'
        }
        empty = "⠀"

        e = mido_utils.Embed(bot=self.bot)

        won_multiplier, won_arrow = random.choice(list(possibilities_and_arrows.items()))
        won_cash = int(won_multiplier * amount)

        await ctx.user_db.add_cash(won_cash, reason="Won wheel game.")

        e.description = f"**{ctx.author}** has just won: " \
                        f"**{mido_utils.readable_currency(won_cash)}** [x{won_multiplier}]\n\n"
        for i, multiplier in enumerate(possibilities_and_arrows.keys()):
            if i == 4:
                e.description += empty + won_arrow + empty * 4

            e.description += f'**『{multiplier}』**{empty * 2}'

            if i in (2, 4):
                e.description += '\n\n'

        await ctx.send(embed=e)

    @commands.command(aliases=['slot'])
    async def slots(self, ctx: mido_utils.Context, amount: Union[int, str]):
        """Play slots!

        You get;
        - **x30** -> If you get 3 {mido_utils.emotes.currency}
        - **x10** -> If you get 3 same emojis
        - **x4** -> If you get 2 {mido_utils.emotes.currency}
        - **x1** -> If you get 1 {mido_utils.emotes.currency}
        """
        emojis = [mido_utils.emotes.currency, "🦋", "♥", "🐱", "🌙", "🍑"]

        slot = [random.choices(emojis, k=3) for _ in range(3)]

        middle = slot[1]
        if middle.count(emojis[0]) == 3:  # 3 donuts
            win_multiplier = 30
        elif middle.count(middle[0]) == 3:  # 3 of the same emoji
            win_multiplier = 10
        elif middle.count(emojis[0]) == 2:  # 2 donuts
            win_multiplier = 4
        elif middle.count(emojis[0]) == 1:  # 1 donut
            win_multiplier = 1
        else:
            win_multiplier = 0

        won = win_multiplier * amount

        await ctx.user_db.add_cash(amount=won, reason="Won slot game.")

        if win_multiplier >= 1:
            content = '**[ 🟢  WIN  🟢 ]**\n'
        else:
            content = '**[ 🔴 LOST 🔴 ]**\n'

        content += '**' + '-' * 19 + '**' + '\n'

        # idk why im making this compatible with all sizes ¯\_(ツ)_/¯
        for i in range(len(slot)):
            for j in range(len(slot[i])):
                if j == 0:  # if beginning
                    content += '| '

                content += slot[i][j]

                content += ' | '

            if i == math.floor(len(slot) / 2):  # if middle
                content += ' **<**'

            content += '\n'  # usual new line
            if i != len(slot) - 1:  # extra new line in between
                content += '\n'

        content += '**' + '-' * 19 + '**' + '\n\n'

        content += f'**{ctx.author}** bet **{amount} {emojis[0]}** '
        # footer
        if win_multiplier > 1:
            content += f'and earned **{won} {emojis[0]}**!! (x{win_multiplier})'
        elif win_multiplier == 1:
            content += f'got the same amount back. '
        else:
            content += f'and lost it all :('

        await ctx.send(content=content)

    @commands.command(aliases=['br'])
    async def betroll(self, ctx: mido_utils.Context, amount: Union[int, str]):
        """Roll a random number between 1 and 100.

        You get;
        - **x10** -> If you get 100
        - **x4** -> If you get >90
        - **x2** -> If you get >66
        """
        rolled = random.randint(1, 100)
        win_multip = 0

        if rolled > 66:
            color = mido_utils.Color.success()
            if rolled == 100:
                win_multip = 10
                msg = f"Congratulations!! " \
                      f"You won **{mido_utils.readable_currency(win_multip * amount)}** for rolling 100 🎉"
            elif rolled > 90:
                win_multip = 4
                msg = f"Congratulations! " \
                      f"You won **{mido_utils.readable_currency(win_multip * amount)}** for rolling above 90."
            else:
                win_multip = 2
                msg = f"Congratulations! " \
                      f"You won **{mido_utils.readable_currency(win_multip * amount)}** for rolling above 66."
        else:
            color = mido_utils.Color.fail()
            msg = f"Better luck next time 🥺"

        await ctx.user_db.add_cash(amount=amount * win_multip, reason="Won betroll game.")

        e = mido_utils.Embed(bot=ctx.bot, colour=color)
        e.description = "**You rolled:** "
        rolled_str = "{:02d}".format(rolled)
        for digit in rolled_str:
            e.description += DIGIT_TO_EMOJI[int(digit)]

        e.description += '\n\n' + msg

        e.set_footer(icon_url=ctx.author.avatar_url, text=str(ctx.author))

        await ctx.send(embed=e)

    @commands.command(aliases=['lb'])
    async def leaderboard(self, ctx: mido_utils.Context):
        """See the global donut leaderboard!"""
        rich_people = await UserDB.get_rich_people(bot=ctx.bot, limit=100)

        e = mido_utils.Embed(bot=self.bot,
                             title=f"{mido_utils.emotes.currency} Leaderboard")

        blocks = []
        for i, user in enumerate(rich_people, 1):
            # if its the #1 user
            if i == 1:
                user_obj = await self.bot.get_user_using_ipc(user.id)
                if user_obj:
                    e.set_thumbnail(url=user_obj.avatar_url)

            blocks.append(f"`#{i}` **{user.discord_name}**\n"
                          f"{user.cash_str}")

        await e.paginate(ctx, blocks, item_per_page=10, extra_sep='\n')

    @commands.command(name="give")
    @commands.guild_only()
    async def give_cash(self, ctx: mido_utils.Context, amount: Union[int, str], *,
                        member: mido_utils.MemberConverter()):
        """Give a specific amount of donut to someone else."""
        if member.id == ctx.author.id:
            raise commands.UserInputError("Why'd you send money to yourself?")

        other_usr = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)

        await other_usr.add_cash(amount, reason=f"Transferred from {ctx.author.id}.")
        await ctx.send_success(f"**{ctx.author.mention}** has just sent **{mido_utils.readable_currency(amount)}** "
                               f"to **{member.mention}**!")

    @mido_utils.is_owner()
    @commands.command(name="award", aliases=['addcash'], hidden=True)
    async def add_cash(self, ctx: mido_utils.Context, amount: Union[int, str], *, member: mido_utils.MemberConverter()):
        other_usr = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)

        await other_usr.add_cash(amount, reason="Rewarded by the bot owner.")
        await member.send(f"You've been awarded **{mido_utils.readable_currency(amount)}** by the bot owner!")
        await ctx.send_success(f"You've successfully awarded {member} with **{mido_utils.readable_currency(amount)}**!")

    @mido_utils.is_owner()
    @commands.command(name="punish", aliases=['withdraw, removecash'], hidden=True)
    async def remove_cash(self, ctx: mido_utils.Context, amount: Union[int, str], *,
                          member: mido_utils.MemberConverter()):
        other_usr = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)

        await other_usr.remove_cash(amount, reason="Removed by the bot owner.", force=True)
        await ctx.send_success(f"You've just removed **{mido_utils.readable_currency(amount)}** from {member}.")

    @mido_utils.is_owner()
    @commands.command(name='donutevent', aliases=['event'], hidden=True)
    async def donut_event(self, ctx: mido_utils.Context, reward: mido_utils.Int32(), length: mido_utils.Time):
        e = mido_utils.Embed(bot=ctx.bot,
                             title="Donut Event!",
                             description=f"React with {mido_utils.emotes.currency} "
                                         f"to get **{mido_utils.readable_currency(reward)}** for free!"
                             )
        e.set_footer(text="Ends")
        e.timestamp = length.end_date

        msg = await ctx.send(embed=e)
        await msg.add_reaction(mido_utils.emotes.currency)

        self.bot.loop.create_task(msg.delete(delay=length.remaining_seconds))

        event = await DonutEvent.create(bot=ctx.bot,
                                        guild_id=ctx.guild.id,
                                        channel_id=ctx.channel.id,
                                        message_id=msg.id,
                                        length=length,
                                        reward=reward)
        self.active_donut_events.append(event)

    @commands.command(aliases=['curtrs'])
    async def transactions(self, ctx: mido_utils.Context, *, target: mido_utils.UserConverter() = None):
        """See your transaction log!"""
        if target and not await ctx.bot.is_owner(ctx.author):
            raise commands.NotOwner("You can't see the transaction log of someone else.")

        user = target or ctx.author

        e = mido_utils.Embed(bot=ctx.bot)
        e.set_author(icon_url=user.avatar_url, name=f"Transaction History of {user}:")

        blocks = []
        for transaction in await TransactionLog.get_users_logs(bot=ctx.bot, user_id=user.id):
            block = ""
            if transaction.amount < 0:
                block += "🔴"  # red circle
            else:
                block += "🔵"  # blue circle

            block += f" `[{transaction.date.start_date_string}]` **{transaction.amount}**\n" \
                     f"{transaction.reason}"

            blocks.append(block)

        await e.paginate(ctx=ctx, blocks=blocks, item_per_page=20)

    @commands.command(aliases=['eatdonut'])
    async def eat(self, ctx: mido_utils.Context, amount: Optional[Union[int, str]] = None):
        """Eat donuts! Do not specify amount if you just want to see how many donuts you have eaten."""
        if not amount:
            return await ctx.send_success(f"You have eaten **{ctx.user_db.eaten_cash_str}** donuts in total.")
        else:
            await mido_utils.ensure_not_broke_and_parse_bet(ctx, amount)

            await ctx.user_db.eat_cash(amount)

            e = mido_utils.Embed(ctx.bot)

            plural = "s" if amount > 1 else ""
            e.description = f"You have just eaten **{mido_utils.readable_currency(amount)}** donut{plural}."

            e.set_footer(text=f"Total Eaten Donuts: {ctx.user_db.eaten_cash_str_without_emoji}"
                              f" | Rank: #{await ctx.user_db.get_eaten_cash_rank()}")

            await ctx.send(embed=e)

    @commands.command(aliases=['edlb', 'donuteatenlb', 'delb'])
    async def eatendonutlb(self, ctx: mido_utils.Context):
        """See the global donut eaten leaderboard!"""
        crazy_people = await UserDB.get_top_cash_eaten_people(bot=ctx.bot, limit=100)

        e = mido_utils.Embed(bot=self.bot,
                             title=f"People Who Ate Most {mido_utils.emotes.currency}")

        blocks = []
        for i, user in enumerate(crazy_people, 1):
            # if its the #1 user
            if i == 1:
                user_obj = await self.bot.get_user_using_ipc(user.id)
                if user_obj:
                    e.set_thumbnail(url=user_obj.avatar_url)

            blocks.append(f"`#{i}` **{user.discord_name}**\n"
                          f"{user.eaten_cash_str}")

        await e.paginate(ctx, blocks, item_per_page=10, extra_sep='\n')

    @wheel.before_invoke
    @betroll.before_invoke
    @slots.before_invoke
    @coin_flip.before_invoke
    @give_cash.before_invoke
    async def ensure_not_broke_and_parse_bet_amount(self, ctx: mido_utils.Context):
        # for some reason this func is called before the global before_invoke
        # so we have to attach db objects here as well
        await ctx.attach_db_objects()

        ctx.args[2] = await mido_utils.ensure_not_broke_and_parse_bet(ctx, ctx.args[
            2])  # arg after the context is the amount.


def setup(bot):
    bot.add_cog(Gambling(bot))
