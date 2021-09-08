import typing

import discord
from discord.ext import commands, tasks

import mido_utils
from models import ModLog
from shinobu import ShinobuBot

action_emotes = {
    'kick'  : '👢',
    'ban'   : '🔨',
    'mute'  : '🔇',
    'unmute': '🔈'
}


class Moderation(
    commands.Cog,
    description="Ban/mute temporarily, hold logs, manage roles, "
                "prune messages quickly to moderate your server easily."):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.check_modlogs.start()

    def cog_check(self, ctx):  # guild only
        if not ctx.guild:
            raise commands.NoPrivateMessage
        else:
            return True

    @tasks.loop(seconds=30.0)
    async def check_modlogs(self):
        time = mido_utils.Time()
        open_modlogs = await ModLog.get_open_logs(bot=self.bot)

        for modlog in open_modlogs:
            # if its the time
            if modlog.time_status.end_date_has_passed:
                guild = self.bot.get_guild(modlog.guild_id)
                if guild:
                    if modlog.type == ModLog.Type.BAN:
                        member = discord.Object(id=modlog.user_id)
                        try:
                            await guild.unban(member, reason='ModLog time has expired. (Auto-Unban)')
                        except discord.NotFound:
                            pass

                    elif modlog.type == ModLog.Type.MUTE:
                        member = guild.get_member(modlog.user_id)
                        if member:
                            mute_role = await self.get_or_create_muted_role(guild)
                            if mute_role in member.roles:
                                await member.remove_roles(mute_role, reason='ModLog time has expired. (Auto-Unmute)')

                await modlog.complete()
        self.bot.logger.debug("Checking modlogs took:\t\t" + time.passed_seconds_in_float_formatted)

    @check_modlogs.before_loop
    async def wait_for_bot_before_loop(self):
        await self.bot.wait_until_ready()

    @check_modlogs.error
    async def task_error(self, error):
        await self.bot.get_cog('ErrorHandling').on_error(error)

    def cog_unload(self):
        self.check_modlogs.cancel()

    @staticmethod
    def get_reason_string(reason=None) -> str:
        return f' with reason: `{reason}`' if reason else '.'

    @staticmethod
    async def get_or_create_muted_role(ctx_or_guild: typing.Union[mido_utils.Context, discord.Guild]):
        if isinstance(ctx_or_guild, mido_utils.Context):
            ctx = ctx_or_guild
            guild = ctx.guild
        else:
            ctx = None
            guild = ctx_or_guild

        muted_role = discord.utils.find(lambda m: m.name.lower() == 'muted', guild.roles)

        msg = None
        if not muted_role:
            if ctx:
                msg = await ctx.send("Creating the mute role and configuring it, please wait...")

            muted_role = await guild.create_role(name='Muted',
                                                 reason="Mute role for the mute command.",
                                                 color=mido_utils.Color.dark_grey())

            couldnt_configure_some_channels = False

            # read messages, view channel, manage roles and channels
            required_perms = discord.Permissions(268436496)

            for channel in guild.channels:
                channel_perms = channel.permissions_for(guild.me)

                # if we have permission to edit it
                if channel_perms.is_superset(required_perms):
                    overwrite = discord.PermissionOverwrite()

                    # if its a text channel
                    if isinstance(channel, discord.TextChannel):
                        setattr(overwrite, 'send_messages', False)
                        setattr(overwrite, 'add_reactions', False)
                    # if its a voice channel
                    if isinstance(channel, discord.VoiceChannel):
                        setattr(overwrite, 'speak', False)

                    await channel.set_permissions(target=muted_role,
                                                  overwrite=overwrite,
                                                  reason="Mute role permissions for the mute command.")
                else:
                    couldnt_configure_some_channels = True

            if ctx:
                if couldnt_configure_some_channels:
                    await msg.edit(content="Mute role has been successfully created "
                                           "but I couldn't configure it's permissions "
                                           "for some channels due to missing permissions.\n"
                                           "If you'd like me to configure it properly for every channel, "
                                           f"please delete the {muted_role.mention} role "
                                           f"and use the `mute` command again "
                                           "after giving me proper permissions.")
                else:
                    await msg.edit(content="Mute role has been successfully created and configured for all channels!")

        return muted_role

    @commands.command()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: mido_utils.Context,
                   target: mido_utils.MemberConverter(),
                   *,
                   reason: commands.clean_content = None):
        """Kicks a user.

        You need the Kick Members permission to use this command.
        """

        await target.kick(reason=reason)
        modlog = await ModLog.add_modlog(bot=ctx.bot,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         _type=ModLog.Type.KICK)

        await ctx.send_success(f"`{modlog.id}` {action_emotes['kick']} "
                               f"User {getattr(target, 'mention', target.id)} has been **kicked** "
                               f"by {ctx.author.mention}"
                               f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self,
                  ctx: mido_utils.Context,
                  target: mido_utils.UserConverter(),
                  length: typing.Union[mido_utils.Time, str] = None,
                  *, reason: commands.clean_content = None):
        """Bans a user for a specified period of time or indefinitely.

        **Examples:**
            `{ctx.prefix}ban @Mido` (bans permanently)
            `{ctx.prefix}ban @Mido toxic` (bans permanently with a reason)
            `{ctx.prefix}ban @Mido 30m` (bans for 30 minutes)
            `{ctx.prefix}ban @Mido 3d toxic` (bans for 3 days with reason)

        **Available time length letters:**
            `s` -> seconds
            `m` -> minutes
            `h` -> hours
            `d` -> days
            `w` -> weeks
            `mo` -> months

        You need Ban Members permission to use this command.
        """

        # if only reason is passed
        if isinstance(length, str):
            reason = length + (f" {reason}" if reason else '')
            length = None

        await ctx.guild.ban(user=target, reason=reason, delete_message_days=1)

        modlog = await ModLog.add_modlog(bot=ctx.bot,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         _type=ModLog.Type.BAN,
                                         length=length)

        await ctx.send_success(f"`{modlog.id}` {action_emotes['ban']} "
                               f"User **{getattr(target, 'mention', target.id)}** "
                               f"has been **banned** "
                               f"by {ctx.author.mention} "
                               f"for **{getattr(length, 'initial_remaining_string', 'life')}**"
                               f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self,
                    ctx: mido_utils.Context,
                    target: mido_utils.UserConverter(),
                    *, reason: commands.clean_content = None):
        """Unbans a banned user.

        You need Ban Members permission to use this command.
        """

        user_is_banned = await ctx.guild.fetch_ban(target)
        if not user_is_banned:
            raise commands.UserInputError("That user isn't banned.")

        else:
            await ctx.guild.unban(target, reason=f"User unbanned by {ctx.author}"
                                                 f"{self.get_reason_string(reason)}")

            await ModLog.add_modlog(bot=ctx.bot,
                                    guild_id=ctx.guild.id,
                                    user_id=target.id,
                                    _type=ModLog.Type.UNBAN,
                                    executor_id=ctx.author.id,
                                    reason=reason)

            await ctx.send_success(f"User **{getattr(target, 'mention', target.id)}** "
                                   f"has been **unbanned** "
                                   f"by {ctx.author.mention}"
                                   f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def mute(self,
                   ctx: mido_utils.Context,
                   target: mido_utils.MemberConverter(),
                   length: typing.Union[mido_utils.Time, str] = None,
                   *, reason: commands.clean_content = None):
        """Mutes a user for a specified period of time or indefinitely.

        **Examples:**
            `{ctx.prefix}mute @Mido` (mutes permanently)
            `{ctx.prefix}mute @Mido shitposting` (mutes permanently with a reason)
            `{ctx.prefix}mute @Mido 30m` (mutes for 30 minutes)
            `{ctx.prefix}mute @Mido 3d shitposting` (mutes for 3 days with reason)

        **Available time length letters:**
            `s` -> seconds
            `m` -> minutes
            `h` -> hours
            `d` -> days
            `w` -> weeks
            `mo` -> months

        You need Manage Roles permission to use this command.
        """

        # if only reason is passed
        if isinstance(length, str):
            reason = length + (f" {reason}" if reason else '')
            length = None

        mute_role = await self.get_or_create_muted_role(ctx)

        if mute_role in target.roles:
            raise commands.UserInputError("That user is already muted!")

        await target.add_roles(mute_role, reason=f"User muted by {ctx.author}"
                                                 f"{self.get_reason_string(reason)}")

        modlog = await ModLog.add_modlog(bot=ctx.bot,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         _type=ModLog.Type.MUTE,
                                         length=length)

        await ctx.send_success(f"`{modlog.id}` {action_emotes['mute']} "
                               f"User **{getattr(target, 'mention', target.id)}** "
                               f"has been **muted** "
                               f"by {ctx.author.mention} "
                               f"for **{getattr(length, 'initial_remaining_string', 'permanently')}**"
                               f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self,
                     ctx: mido_utils.Context,
                     target: mido_utils.MemberConverter(),
                     *, reason: commands.clean_content = None):
        """Unmutes a muted user.

        You need Manage Roles permission to use this command.
        """

        mute_role = await self.get_or_create_muted_role(ctx)

        if mute_role not in target.roles:
            raise commands.UserInputError("That user is not muted!")

        await target.remove_roles(mute_role, reason=f"User unmuted by {ctx.author}"
                                                    f"{self.get_reason_string(reason)}")

        await ModLog.add_modlog(bot=ctx.bot,
                                guild_id=ctx.guild.id,
                                user_id=target.id,
                                reason=reason,
                                executor_id=ctx.author.id,
                                _type=ModLog.Type.UNMUTE)

        await ctx.send_success(f"User **{getattr(target, 'mention', target.id)}** "
                               f"has been **unmuted** "
                               f"by {ctx.author.mention}"
                               f"{self.get_reason_string(reason)}")

    @commands.command(name='modlogs')
    @commands.has_permissions(ban_members=True, kick_members=True)
    async def mod_logs(self,
                       ctx: mido_utils.Context,
                       *,
                       target: mido_utils.MemberConverter()):
        """See the logs of a user.

        You need Kick Members and Ban Members permissions to use this command.
        """

        logs = await ModLog.get_guild_logs(bot=ctx.bot, guild_id=ctx.guild.id, user_id=target.id)
        if not logs:
            raise commands.UserInputError(f"No logs have been found for user **{target}**.")

        e = mido_utils.Embed(self.bot)
        e.set_author(icon_url=getattr(target, 'avatar_url', None),
                     name=f"Logs of {target}")
        e.set_footer(text=f"{len(logs)} Logs")

        log_blocks = []
        for log in logs:
            log_description = f"**Case ID:** `{log.id}` {log.time_status.start_date_string}\n" \
                              f"**Action:** {log.type.name.title()} {action_emotes[log.type.name.lower()]}\n"

            if log.length_string:
                log_description += f'**Length:** {log.length_string}\n'

            if log.reason:
                log_description += f"**Reason:** {log.reason}\n"

            log_description += f"**Executor:** <@{log.executor_id}>"

            log_blocks.append(log_description)

        await e.paginate(ctx, blocks=log_blocks, extra_sep='\n')

    @commands.command(name='clearmodlogs', aliases=['clearlogs'])
    @commands.has_permissions(administrator=True)
    async def clear_modlogs(self,
                            ctx: mido_utils.Context,
                            *,
                            target: mido_utils.MemberConverter()):
        """Clears the logs of a user.

        You need to have the Administrator permission to use this command.
        """
        msg = await ctx.send_success(f"Are you sure you'd like to reset the logs of **{target}**?")
        yes = await mido_utils.Embed.yes_no(self.bot, ctx.author.id, msg)

        if yes:
            await ModLog.hide_logs(bot=ctx.bot, guild_id=ctx.guild.id, user_id=target.id)

            await ctx.edit_custom(msg, f"Logs of **{target}** has been successfully deleted.")
        else:
            await ctx.edit_custom(msg, "Request declined.")

    @commands.command(aliases=['changereason'])
    async def reason(self,
                     ctx: mido_utils.Context,
                     case_id: mido_utils.Int32(),
                     *, new_reason: commands.clean_content = None):
        """Update the reason of a case using its ID.

        You either need to be the executor of the case or have Administrator permission to use this command.
        """
        log = await ModLog.get_by_id(bot=ctx.bot, log_id=case_id, guild_id=ctx.guild.id)
        if not log:
            raise commands.UserInputError("No logs have been found with that case ID.")

        if log.executor_id != ctx.author.id and not ctx.author.guild_permissions.administrator:
            raise commands.UserInputError("You have to be the executor of this case "
                                          "or have Administrator permission in the server to do that!")

        await log.change_reason(new_reason)

        await ctx.send_success(f"Reason of `{log.id}` has been successfully updated: `{new_reason}`")

    @commands.command(name='setrole', aliases=['sr', 'giverole', 'gr'])
    @commands.has_permissions(manage_roles=True)
    async def set_role(self,
                       ctx: mido_utils.Context,
                       member: mido_utils.MemberConverter(),
                       *,
                       role: mido_utils.RoleConverter()):
        """Give a role to a member.

        You need the **Manage Roles** permissions to use this command.
        """
        # already has that role check
        if role in member.roles:
            raise commands.UserInputError(f"Member {member.mention} already has the {role.mention} role.")

        await member.add_roles(role, reason=f'Added by {ctx.author}.')

        await ctx.send_success(f"Role {role.mention} has been successfully given to {member.mention}.")

    @commands.command(name='removerole', aliases=['rr'])
    @commands.has_permissions(manage_roles=True)
    async def remove_role(self,
                          ctx: mido_utils.Context,
                          member: mido_utils.MemberConverter(),
                          *,
                          role: mido_utils.RoleConverter()):
        """Remove a role from a member.

        You need the **Manage Roles** permissions to use this command.
        """

        # if they dont have the role
        if role not in member.roles:
            raise commands.UserInputError(f"Member {member.mention} don't have the {role.mention} role.")

        await member.remove_roles(role, reason=f'Removed by {ctx.author}.')

        await ctx.send_success(f"Role {role.mention} has been successfully removed from {member.mention}.")

    @commands.command(name='createrole', aliases=['cr'])
    @commands.has_permissions(manage_roles=True)
    async def create_role(self,
                          ctx: mido_utils.Context,
                          *,
                          role_name: str):
        """Create a role.

        You need the **Manage Roles** permissions to use this command.
        """
        if len(role_name) > 100:
            raise commands.BadArgument("Role name can't be more than 100 characters.")

        role = await ctx.guild.create_role(name=role_name,
                                           reason=f'Created by {ctx.author}.')

        await ctx.send_success(f"Role {role.mention} has been successfully created!")

    @commands.command(name='deleterole', aliases=['dr'])
    @commands.has_permissions(manage_roles=True)
    async def delete_role(self,
                          ctx: mido_utils.Context,
                          *,
                          role: mido_utils.RoleConverter()):
        """Delete a role from the server.

        You need the **Manage Roles** permissions to use this command.
        """

        await role.delete(reason=f'Deleted by {ctx.author}.')

        await ctx.send_success(f"Role `{role}` has been successfully deleted.")

    @commands.command(aliases=['av'])
    async def avatar(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter() = None):
        """See the avatar of someone."""
        user = target or ctx.author
        e = mido_utils.Embed(bot=self.bot, image_url=user.avatar_url)
        await ctx.send(embed=e)

    @set_role.before_invoke
    @remove_role.before_invoke
    @delete_role.before_invoke
    async def _ensure_role_hierarchy(self, ctx):
        mido_utils.ensure_role_hierarchy(ctx)

    @commands.command(aliases=['purge', 'clear'])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def prune(self, ctx: mido_utils.Context, number: int, target_user: mido_utils.MemberConverter() = None):
        """Delete a number of messages in a channel.
        **Maximum amount is 100.**
        You can specify a target user to delete only their messages.

        You need to have Manage Messages permission to use this command.
        """

        def prune_check(m):
            if not target_user:
                return True
            else:
                return m.author.id == target_user.id

        if number <= 0:
            raise commands.BadArgument("Invalid message amount. It can't be less than or equal to 0.")
        elif number > 100:
            number = 100

        # first delete the command msg
        await ctx.message.delete()

        # then delete the rest
        deleted = await ctx.channel.purge(limit=number, check=prune_check, bulk=True)

        await ctx.send_success(f"Successfully deleted **{len(deleted)}** messages.", delete_after=3.0)

    @commands.command(name='inrole')
    async def in_role(self, ctx: mido_utils.Context, *, role: mido_utils.RoleConverter()):
        """See the people in a specific role."""
        ppl = [member for member in ctx.guild.members if role in member.roles]

        e = mido_utils.Embed(bot=ctx.bot, title=f"List of people in the role: {role}")
        e.set_footer(text=f"{len(ppl)} People")

        blocks = []
        for member in ppl:
            blocks.append(f"· {member.mention}")

        await e.paginate(ctx=ctx, blocks=blocks, item_per_page=20)

    @commands.command(name="serverinfo", aliases=['sinfo'])
    async def server_info(self, ctx: mido_utils.Context, server_id: mido_utils.Int64() = None):
        """Shows the information of the server."""
        # TODO: get the guild using IPC

        # if user is not the owner or server id isn't specified
        if server_id is not None:
            if not await ctx.bot.is_owner(ctx.author):
                server_id = ctx.guild.id
        else:
            server_id = ctx.guild.id

        server: discord.Guild = ctx.bot.get_guild(server_id)

        if not server:
            raise commands.UserInputError("Could not find the guild.")

        humans = 0
        bots = 0
        online = 0

        for member in server.members:
            if member.status != discord.Status.offline:
                online += 1

            if member.bot:
                bots += 1
            else:
                humans += 1

        embed = mido_utils.Embed(bot=ctx.bot)
        embed.set_author(icon_url=server.icon_url, name=server.name)
        embed.set_thumbnail(url=server.icon_url)

        embed.add_field(name="Owner",
                        value=f"{server.owner}\n"
                              f"`{server.owner.id}`",
                        inline=True)

        embed.add_field(name=f"Members ({server.member_count if hasattr(server, '_member_count') else 0})",
                        value=f"{humans} Humans\n"
                              f"{bots} Bots\n"
                              f"({online} Online)",
                        inline=True)

        embed.add_field(name=f"Channels ({len(server.channels)})",
                        value=f"{len(server.categories)} Categories\n"
                              f"{len(server.text_channels)} Text Channels\n"
                              f"{len(server.voice_channels)} Voice Channels",
                        inline=True)

        embed.add_field(name="Emojis",
                        value=f"{len(server.emojis)}/{server.emoji_limit}",
                        inline=True)

        embed.add_field(name="Roles",
                        value=f"{len(server.roles)}/250",
                        inline=True)

        creation_date = mido_utils.Time(start_date=server.created_at, offset_naive=True)
        embed.add_field(name="Created in",
                        value=f"{creation_date.start_date_string}\n"
                              f"({creation_date.remaining_days} days ago)",
                        inline=True)

        embed.set_footer(text=f"Server ID: {server.id}")

        await ctx.send(embed=embed)

    # TODO: make this available inside guilds
    @commands.command(name="userinfo", aliases=['uinfo'])
    @commands.guild_only()
    async def user_info(self, ctx: mido_utils.Context,
                        *,
                        user: typing.Union[mido_utils.MemberConverter, mido_utils.UserConverter] = None):
        """Shows the information of a user."""
        user = user or ctx.author

        # if its a user obj but author is not an owner
        if isinstance(user, discord.User):
            if not await ctx.bot.is_owner(ctx.author):
                user = ctx.author

        embed = mido_utils.Embed(bot=ctx.bot)
        embed.set_thumbnail(url=user.avatar_url)

        # name
        embed.add_field(name='Name', value=str(user))

        # nick
        if isinstance(user, discord.Member):
            embed.add_field(name='Nickname', value=user.display_name)

        # id
        embed.add_field(name='ID', value=f'`{user.id}`')

        # account creation date
        account_creation_date = mido_utils.Time(start_date=user.created_at, offset_naive=True)
        embed.add_field(name="Joined Discord at",
                        value=f"{account_creation_date.start_date_string}\n"
                              f"({account_creation_date.remaining_days} days ago)",
                        inline=True)

        if isinstance(user, discord.Member):
            # server join date
            server_join_date = mido_utils.Time(start_date=user.joined_at, offset_naive=True)
            embed.add_field(name="Joined Server at",
                            value=f"{server_join_date.start_date_string}\n"
                                  f"({server_join_date.remaining_days} days ago)",
                            inline=True)

            # roles
            role_field = ""
            for i, role in enumerate(user.roles, 1):
                if len(role_field) < 977:
                    role_field += role.mention
                else:
                    role_field += f"**And {len(user.roles) - i} more role(s)**"
                    break

                if i != len(user.roles):
                    role_field += ',\n'

            embed.add_field(name=f'Roles ({len(user.roles)})',
                            value=role_field,
                            inline=False)

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Moderation(bot))
