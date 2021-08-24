from datetime import datetime
from typing import List, Tuple, Union

import discord
from discord.ext import commands

import mido_utils
from models.db import MemberDB, UserDB, XpAnnouncement, XpRoleReward
from shinobu import ShinobuBot


def calculate_xp_data(total_xp: int) -> Tuple[int, int, int]:
    """Returns level, progress and required xp to level up"""
    base_xp = 30
    used_xp = 0
    lvl = 1

    while True:
        required_xp_to_level_up = int(base_xp + base_xp / 3.0 * (lvl - 1))

        if required_xp_to_level_up + used_xp > total_xp:
            break

        used_xp += required_xp_to_level_up
        lvl += 1

    return lvl, total_xp - used_xp, required_xp_to_level_up


class Leveling(
    commands.Cog,
    description="Check your xp status using `{ctx.prefix}xp`, "
                "set level rewards using `{ctx.prefix}xprolereward` "
                "and compete against others in `{ctx.prefix}xplb` and `{ctx.prefix}xpglb`!"):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

    async def get_xp_embed(self, user_or_member, db: Union[MemberDB, UserDB]) -> discord.Embed:
        e = mido_utils.Embed(bot=self.bot, title=str(user_or_member))

        # if in guild
        if isinstance(user_or_member, discord.Member):
            lvl, progress, required_xp_to_lvl_up = calculate_xp_data(db.total_xp)
            e.add_field(name='**Server Stats**',
                        value=f"**Level**: {lvl}\n"
                              f"**Total XP**: {db.total_xp}\n"
                              f"**Level Progress**: {progress}/{required_xp_to_lvl_up}\n"
                              f"**Server Rank**: #{await db.get_xp_rank()}")

            db = db.user

        lvl, progress, required_xp_to_lvl_up = calculate_xp_data(db.total_xp)
        e.add_field(name='**Global Stats**',
                    value=f"**Level**: {lvl}\n"
                          f"**Total XP**: {db.total_xp}\n"
                          f"**Level Progress**: {progress}/{required_xp_to_lvl_up}\n"
                          f"**Global Rank**: #{await db.get_xp_rank()}"
                    )

        e.set_thumbnail(url=user_or_member.avatar_url)
        e.timestamp = datetime.utcnow()

        return e

    async def send_leaderboard_embed(self, ctx, top: List[Union[UserDB, MemberDB]], title: str):
        e = mido_utils.Embed(bot=self.bot, title=title)

        e.timestamp = datetime.utcnow()

        blocks = []
        for i, user in enumerate(top, 1):
            if i == 1:
                user_discord = await self.bot.get_user_using_ipc(user.id)
                if user_discord:
                    e.set_thumbnail(url=user_discord.avatar_url)

            level, progress, required_xp_to_level_up = calculate_xp_data(user.total_xp)
            blocks.append(f"`#{i}` **{user.discord_name}**\n"
                          f"Level: **{level}** | Total XP: **{user.total_xp}**\n")

        await e.paginate(ctx, blocks=blocks, item_per_page=10)

    async def check_for_level_up(self,
                                 message: discord.Message,
                                 member_db: MemberDB,
                                 added=0,
                                 added_globally=False):
        if member_db.user.level_up_notification == XpAnnouncement.SILENT:
            return

        level, progress, required_xp_to_level_up = calculate_xp_data(member_db.total_xp)
        global_level, global_progress, global_required_xp_to_level_up = calculate_xp_data(member_db.user.total_xp)

        lvld_up_in_guild = progress < added
        lvld_up_globally = global_progress < added

        if not (lvld_up_globally or lvld_up_in_guild):
            return

        msg = f"🎉 **Congratulations {message.author.mention}!** 🎉\n"

        if lvld_up_in_guild:
            msg += f"You've just leveled up to **{level}** in {str(message.guild)}!\n"
        if lvld_up_globally and added_globally:
            msg += f"You've just leveled up to **{global_level}** globally!"

        if member_db.user.level_up_notification == XpAnnouncement.DM or member_db.guild.level_up_notifs_silenced:
            # if the preference is DMs or notifs are silenced in that guild, send it in DMs
            channel = message.author
        else:
            channel = message.channel

        try:
            await channel.send(msg)
        except discord.Forbidden:
            pass

        if lvld_up_in_guild:
            await self.check_member_xp_role_reward(message.author, member_db=member_db)

    async def check_guild_xp_role_rewards(self, guild_id: int = None):
        guild_discord: discord.Guild = self.bot.get_guild(guild_id)
        for member in guild_discord.members:
            await self.check_member_xp_role_reward(member)

    async def check_member_xp_role_reward(self, member: discord.Member, member_db: MemberDB = None):
        member_db = member_db or await MemberDB.get_or_create(self.bot, member.guild.id, member.id)
        level, progress, required_xp_to_level_up = calculate_xp_data(member_db.total_xp)

        role_rewards = await XpRoleReward.get_all(bot=self.bot, guild_id=member_db.guild.id)
        eligible_role_rewards = [reward for reward in role_rewards if reward.level <= level]

        for reward in eligible_role_rewards:
            role = member.guild.get_role(reward.role_id)
            if not role:
                return await reward.delete()

            if role not in member.roles:
                await member.add_roles(role, reason=f"XP Level {reward.level} reward.")

    async def base_xp_on_message(self, message: discord.Message):
        if not self.bot.should_listen_to_msg(message, guild_only=True):
            return

        member_db = await MemberDB.get_or_create(bot=self.bot,
                                                 guild_id=message.guild.id,
                                                 member_id=message.author.id)
        if message.channel.id in member_db.guild.xp_excluded_channels:
            return

        can_gain_xp = member_db.xp_status.end_date_has_passed
        can_gain_xp_global = member_db.user.xp_status.end_date_has_passed

        # if on cooldown
        if not can_gain_xp and not can_gain_xp_global:
            return

        if can_gain_xp:
            await member_db.add_xp(amount=3)

        if can_gain_xp_global:
            await member_db.user.add_xp(amount=3)

        await self.check_for_level_up(message, member_db, added=3, added_globally=can_gain_xp_global)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        time = mido_utils.Time()
        await self.base_xp_on_message(message)
        self.bot.logger.debug('Checking XP took:\t\t\t' + time.passed_seconds_in_float_formatted)

    @commands.command(name="xp", aliases=['level', 'rank'])
    async def show_rank(self, ctx: mido_utils.Context, member: mido_utils.MemberConverter() = None):
        """See your or someone else's XP rank."""
        if member:
            user = member
            user_db = await MemberDB.get_or_create(bot=ctx.bot,
                                                   guild_id=ctx.guild.id,
                                                   member_id=member.id)
        else:
            user = ctx.author
            if ctx.guild:
                user_db = ctx.member_db
            else:
                user_db = ctx.user_db

        e = await self.get_xp_embed(user, user_db)

        await ctx.send(embed=e)

    @commands.command(name='xpleaderboard', aliases=['xplb'])
    @commands.guild_only()
    async def show_leaderboard(self, ctx: mido_utils.Context):
        """See the XP leaderboard of the server."""
        top = await ctx.guild_db.get_top_xp_people(limit=100)

        await self.send_leaderboard_embed(ctx, top, title=f'XP Leaderboard of {ctx.guild}')

    @commands.command(name='xpgleaderboard', aliases=['xpgloballeaderboard', 'xpglb'])
    async def show_global_leaderboard(self, ctx: mido_utils.Context):
        """See the global XP leaderboard."""
        top = await ctx.user_db.get_top_xp_people(ctx.bot, limit=100)

        await self.send_leaderboard_embed(ctx, top, title='Global XP Leaderboard')

    @commands.command(name='xpnotifs')
    async def change_level_up_notifications(self, ctx: mido_utils.Context, new_preference: str):
        """Configure your level up notifications. It's DM by default.

        `{ctx.prefix}xpnotifs [silence|disable]` (**disables** level up notifications)
        `{ctx.prefix}xpnotifs dm` (sends level up notifications through your **DMs**)
        `{ctx.prefix}xpnotifs [guild|server]` (sends level up notifications to the **server**)
        """
        if new_preference in ('silence', 'disable'):
            new_preference = XpAnnouncement.SILENT
        elif new_preference in ('dm', 'dms'):
            new_preference = XpAnnouncement.DM
        elif new_preference in ('guild', 'server'):
            new_preference = XpAnnouncement.GUILD
        else:
            raise commands.BadArgument("Invalid notification preference type!")

        await ctx.user_db.change_level_up_preference(new_preference)
        await ctx.send(f"You've successfully changed your level up preference: `{new_preference.name.title()}`")

    @commands.command(name='xprolereward', aliases=['xprr'])
    @commands.has_permissions(manage_roles=True)
    @commands.guild_only()
    async def set_xp_role_reward(self, ctx: mido_utils.Context, level: mido_utils.Int32(),
                                 *, role: mido_utils.RoleConverter() = None):
        """Set a role reward for a specified level.

        Provide no role name in order to remove the role reward for that level.

        You need Manage Roles permission to use this command."""
        already_existing_reward = await XpRoleReward.get_level_reward(bot=ctx.bot,
                                                                      guild_id=ctx.guild.id,
                                                                      level=level)
        if not role:
            if not already_existing_reward:
                raise commands.BadArgument("There is already not a reward for this level.")
            else:
                role = ctx.guild.get_role(already_existing_reward.role_id)
                mido_utils.ensure_role_hierarchy(ctx, role)

                await already_existing_reward.delete()
                await ctx.send_success(f"I've successfully reset the role reward for level **{level}**.")

        else:
            mido_utils.ensure_role_hierarchy(ctx, role)

            if already_existing_reward:
                old_role_id = already_existing_reward.role_id
                await already_existing_reward.set_role_reward(role_id=role.id)
                await ctx.send_success(
                    f"I've successfully changed the role reward of level **{already_existing_reward.level}** "
                    f"from <@&{old_role_id}> to {role.mention}.\n"
                    f"\n"
                    f"I will go ahead and give this new role to those who have already reached level {level}, "
                    f"however, I will not remove their old role reward. This might take a while."
                )

            else:
                await XpRoleReward.create(bot=ctx.bot,
                                          guild_id=ctx.guild.id,
                                          level=level,
                                          role_id=role.id)
                await ctx.send_success(
                    f"I've successfully created a new role reward for level **{level}**!\n"
                    f"\n"
                    f"They'll get the {role.mention} role when they reach level **{level}**.\n"
                    f"I will go ahead and give this role to those who have already reached level {level}. "
                    f"This might take a while."
                )

            await self.check_guild_xp_role_rewards(guild_id=ctx.guild.id)

    @commands.command(name='xprolerewards', aliases=['xprewards', 'xprrs'])
    @commands.guild_only()
    async def list_xp_role_rewards(self, ctx: mido_utils.Context):
        """See a list of XP role rewards of this server."""
        rewards = await XpRoleReward.get_all(bot=ctx.bot, guild_id=ctx.guild.id)
        if not rewards:
            raise commands.UserInputError(f"This server does not have any XP role rewards.\n\n"
                                          f"You can add/set XP role rewards using "
                                          f"`{ctx.prefix}xprolereward <level> <role_reward>`")

        e = mido_utils.Embed(bot=ctx.bot)
        e.set_author(icon_url=ctx.guild.icon_url, name=f"XP Role Rewards of {ctx.guild}")

        blocks = []
        for reward in rewards:
            role = ctx.guild.get_role(reward.role_id)
            if not role:
                await reward.delete()
                continue

            people_in_this_role = len([member for member in ctx.guild.members if role in member.roles])
            blocks.append(f"Level **{reward.level}** -> {role.mention} Role **[{people_in_this_role} people]**")

        await e.paginate(ctx=ctx,
                         blocks=blocks,
                         item_per_page=10)

    @commands.command(name="xpsilenceservernotifs")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def silence_level_up_notifs_for_guild(self, ctx: mido_utils.Context):
        """Silence level up notifications in this server.
        **This command overwrites the notification preference of the users if silenced.**

        You need **Manage Guild** permission to use this command.
        """
        just_silenced = await ctx.guild_db.toggle_level_up_notifs()

        if just_silenced:
            await ctx.send("You've successfully silenced level up notifications in this server!")
        else:
            await ctx.send("You've successfully enabled level up notifications in this server!")

    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.command(name="xpchannelexclude", aliases=['xpex'])
    async def add_xp_excluded_channel(self, ctx: mido_utils.Context, *, channel: discord.TextChannel):
        """Exclude a channel to prevent people from gaining XP in that channel."""
        if channel.id in ctx.guild_db.xp_excluded_channels:
            raise commands.UserInputError(f"Channel {channel.mention} has already been excluded.")

        await ctx.guild_db.add_xp_excluded_channel(channel.id)
        await ctx.send_success(f"Channel {channel.mention} has been successfully added to the XP excluded channels.")

    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.command(name="xpchannelinclude", aliases=['xpin'])
    async def remove_xp_excluded_channel(self, ctx: mido_utils.Context, *, channel: discord.TextChannel):
        """Remove an XP excluded channel to no longer prevent people from gaining XP in that channel."""
        if channel.id not in ctx.guild_db.xp_excluded_channels:
            raise commands.UserInputError(f"Channel {channel.mention} is not excluded.")

        await ctx.guild_db.remove_xp_excluded_channel(channel.id)
        await ctx.send_success(
            f"Channel {channel.mention} has been successfully removed from the XP excluded channels.")

    @commands.guild_only()
    @commands.command(name="xpexcludedchannels", aliases=['xpexs'])
    async def show_excluded_channels(self, ctx: mido_utils.Context):
        """See excluded channels where people can not gain XP."""
        if not ctx.guild_db.xp_excluded_channels:
            return await ctx.send_success(f"**{ctx.guild}** does not have any XP excluded channels.")

        e = mido_utils.Embed(bot=ctx.bot)
        e.set_author(icon_url=ctx.guild.icon_url, name=f"XP Excluded Channels of {ctx.guild.name}")
        blocks = []
        for channel_id in ctx.guild_db.xp_excluded_channels:
            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                await ctx.guild_db.remove_xp_excluded_channel(channel_id)
                continue
            blocks.append(channel.mention + "\n")

        await e.paginate(ctx=ctx, blocks=blocks, item_per_page=10)

    @commands.command(name="addxp", hidden=True)
    @mido_utils.is_owner()
    async def add_xp(self, ctx: mido_utils.Context, member: mido_utils.MemberConverter(), amount: mido_utils.Int64()):
        member_db = await MemberDB.get_or_create(bot=ctx.bot, guild_id=ctx.guild.id, member_id=member.id)
        await member_db.add_xp(amount, owner=True)
        await ctx.send_success("Success!")

    @commands.command(name="addgxp", hidden=True)
    @mido_utils.is_owner()
    async def add_gxp(self, ctx: mido_utils.Context, member: mido_utils.MemberConverter(), amount: mido_utils.Int64()):
        user_db = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)
        await user_db.add_xp(amount, owner=True)
        await ctx.send_success("Success!")

    @commands.command(name="removexp", aliases=['remxp'], hidden=True)
    @mido_utils.is_owner()
    async def remove_xp(self, ctx: mido_utils.Context,
                        member: mido_utils.MemberConverter(), amount: mido_utils.Int64()):
        member_db = await MemberDB.get_or_create(bot=ctx.bot, guild_id=ctx.guild.id, member_id=member.id)
        await member_db.remove_xp(amount)
        await ctx.send_success("Success!")

    @commands.command(name="removegxp", aliases=['remgxp'], hidden=True)
    @mido_utils.is_owner()
    async def remove_gxp(self, ctx: mido_utils.Context,
                         member: mido_utils.MemberConverter(), amount: mido_utils.Int64()):
        member_db = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)
        await member_db.remove_xp(amount)
        await ctx.send_success("Success!")


def setup(bot):
    bot.add_cog(Leveling(bot))
