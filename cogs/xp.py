from datetime import datetime
from typing import List, Union

import discord
from discord.ext import commands

from midobot import MidoBot
from models.db import MemberDB, UserDB, XpAnnouncement, XpRoleReward
from services import checks, context
from services.converters import MidoMemberConverter, MidoRoleConverter
from services.embed import MidoEmbed


# todo: xp exclude channel


class XP(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    async def get_xp_embed(self, user_or_member, db) -> discord.Embed:
        e = discord.Embed(color=self.bot.main_color,
                          title=str(user_or_member))

        # if in guild
        if isinstance(user_or_member, discord.Member):
            e.add_field(name='**Server Stats**',
                        value=f"**Level**: {db.level}\n"
                              f"**Total XP**: {db.total_xp}\n"
                              f"**Level Progress**: {db.progress}/{db.required_xp_to_level_up}\n"
                              f"**Server Rank**: #{await db.get_xp_rank()}")

            db = db.user

        e.add_field(name='**Global Stats**',
                    value=f"**Level**: {db.level}\n"
                          f"**Total XP**: {db.total_xp}\n"
                          f"**Level Progress**: {db.progress}/{db.required_xp_to_level_up}\n"
                          f"**Global Rank**: #{await db.get_xp_rank()}"
                    )

        e.set_thumbnail(url=user_or_member.avatar_url)
        e.timestamp = datetime.utcnow()

        return e

    def get_leaderboard_embed(self, top_10: List[Union[UserDB, MemberDB]], title: str):
        e = discord.Embed(color=self.bot.main_color,
                          title=title)

        e.timestamp = datetime.utcnow()

        e.description = ""
        for i, user in enumerate(top_10, 1):
            if i == 1 and self.bot.get_user(user.id):
                e.set_thumbnail(url=self.bot.get_user(user.id).avatar_url)

            e.description += f"`#{i}` **{user.discord_name}**\n" \
                             f"Level: **{user.level}** | Total XP: **{user.total_xp}**\n\n"

        return e

    async def check_for_level_up(self,
                                 message: discord.Message,
                                 member_db: MemberDB,
                                 guild_name: str,
                                 added=0,
                                 added_globally=False):
        if member_db.user.level_up_notification == XpAnnouncement.SILENT:
            return

        lvld_up_in_guild = member_db.progress < added
        lvld_up_globally = member_db.user.progress < added

        if not lvld_up_globally or not lvld_up_in_guild:
            return

        msg = f"🎉 **Congratulations {message.author.mention}!** 🎉\n"

        if lvld_up_in_guild:
            msg += f"You just have leveled up to **{member_db.level}** in {guild_name}!\n"
        if lvld_up_globally and added_globally:
            msg += f"You just have leveled up to **{member_db.user.level}** globally!"

        if member_db.user.level_up_notification == XpAnnouncement.DM or member_db.guild.level_up_notifs_silenced:
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

        role_rewards = await XpRoleReward.get_all(bot=self.bot, guild_id=member_db.guild.id)
        eligible_role_rewards = [reward for reward in role_rewards if reward.level <= member_db.level]

        for reward in eligible_role_rewards:
            role = member.guild.get_role(reward.role_id)
            if not role:
                return await reward.delete()

            if role not in member.roles:
                await member.add_roles(role, reason=f"XP Level {reward.level} reward.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.is_ready() or message.author.bot or not message.guild:
            return

        member_db = await MemberDB.get_or_create(bot=self.bot,
                                                 guild_id=message.guild.id,
                                                 member_id=message.author.id)

        can_gain_xp = member_db.xp_date_status.end_date_has_passed
        can_gain_xp_global = member_db.user.xp_status.end_date_has_passed

        # if on cooldown
        if not can_gain_xp and not can_gain_xp_global:
            return

        if can_gain_xp:
            await member_db.add_xp(amount=3)

        if can_gain_xp_global:
            await member_db.user.add_xp(amount=3)

        await self.check_for_level_up(message, member_db, str(message.guild), added=3,
                                      added_globally=can_gain_xp_global)

    @commands.command(name="rank", aliases=['xp', 'level'])
    async def show_rank(self, ctx: context.MidoContext, member: MidoMemberConverter() = None):
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
    async def show_leaderboard(self, ctx: context.MidoContext):
        """See the XP leaderboard of the server."""
        top_10 = await ctx.guild_db.get_top_10()

        e = self.get_leaderboard_embed(top_10, title=f'XP Leaderboard of {ctx.guild}')

        await ctx.send(embed=e)

    @commands.command(name='xpgleaderboard', aliases=['xpgloballeaderboard', 'xpglb'])
    @commands.guild_only()
    async def show_global_leaderboard(self, ctx: context.MidoContext):
        """See the global XP leaderboard."""
        top_10 = await ctx.user_db.get_top_10(ctx.bot)

        e = self.get_leaderboard_embed(top_10, title='Global XP Leaderboard')

        await ctx.send(embed=e)

    @commands.command(name='xpnotifs')
    async def change_level_up_notifications(self, ctx: context.MidoContext, new_preference: str):
        """Configure your level up notifications. It's DM by default.

        `{0.prefix}xpnotifs [silence|disable]` (**disables** level up notifications)
        `{0.prefix}xpnotifs dm` (sends level up notifications through your **DMs**)
        `{0.prefix}xpnotifs [guild|server]` (sends level up notifications to the **server**)
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
    async def set_xp_role_reward(self, ctx: context.MidoContext, level: int, role: MidoRoleConverter() = None):
        """Set a role reward for a specified level.

        Provide no role name in order to remove the role reward for that level."""
        already_existing_reward = await XpRoleReward.get_level_reward(bot=ctx.bot,
                                                                      guild_id=ctx.guild.id,
                                                                      level=level)
        if not role:
            if not already_existing_reward:
                raise commands.BadArgument("There is already not a reward for this level.")
            else:
                await already_existing_reward.delete()
                await ctx.send_success(f"I've successfully reset the role reward for level **{level}**.")

        else:
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
    async def list_xp_role_rewards(self, ctx: context.MidoContext):
        """See a list of XP role rewards of this server."""
        rewards = await XpRoleReward.get_all(bot=ctx.bot, guild_id=ctx.guild.id)
        if not rewards:
            raise commands.UserInputError(f"This server does not have any XP role rewards.\n\n"
                                          f"You can add/set XP role rewards using `{ctx.prefix}xprolereward <level> <role_reward>`")

        e = MidoEmbed(bot=ctx.bot)
        e.set_author(icon_url=ctx.guild.icon_url, name=f"XP Role Rewards of {ctx.guild}")

        blocks = []
        for reward in rewards:
            role = ctx.guild.get_role(reward.role_id)
            if not role:
                await reward.delete()
                continue

            blocks.append(f"Level **{reward.level}** -> {role.mention} Role")

        await e.paginate(ctx=ctx,
                         blocks=blocks,
                         item_per_page=10)

    @commands.command(name="silenceserverxp")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def silence_level_up_notifs_for_guild(self, ctx: context.MidoContext):
        """Silence level up notifications in this server.
        **This command overwrites the notification preference of the users if silenced.**

        You need **Manage Guild** permission to use this command.
        """
        just_silenced = await ctx.guild_db.toggle_level_up_notifs()

        if just_silenced:
            await ctx.send("You've successfully silenced level up notifications in this server!")
        else:
            await ctx.send("You've successfully enabled level up notifications in this server!")

    @commands.command(name="addxp", hidden=True)
    @checks.is_owner()
    async def add_xp(self, ctx, member: MidoMemberConverter(), amount: int):
        member_db = await MemberDB.get_or_create(bot=ctx.bot, guild_id=ctx.guild.id, member_id=member.id)
        await member_db.add_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="addgxp", hidden=True)
    @checks.is_owner()
    async def add_gxp(self, ctx, member: MidoMemberConverter(), amount: int):
        member_db = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)
        await member_db.add_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="removexp", aliases=['remxp'], hidden=True)
    @checks.is_owner()
    async def remove_xp(self, ctx, member: MidoMemberConverter(), amount: int):
        member_db = await MemberDB.get_or_create(bot=ctx.bot, guild_id=ctx.guild.id, member_id=member.id)
        await member_db.remove_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="removegxp", aliases=['remgxp'], hidden=True)
    @checks.is_owner()
    async def remove_gxp(self, ctx, member: MidoMemberConverter(), amount: int):
        member_db = await UserDB.get_or_create(bot=ctx.bot, user_id=member.id)
        await member_db.remove_xp(amount)
        await ctx.send("Success!")


def setup(bot):
    bot.add_cog(XP(bot))
