import typing

import discord
from discord.ext import commands, tasks

from db.models import GuildDB, ModLog
from main import MidoBot
from services.base_embed import BaseEmbed
from services.context import MidoContext
from services.converters import MidoMemberConverter, MidoRoleConverter
from services.exceptions import EmbedError
from services.menu_stuff import paginate, yes_no
from services.security_stuff import ensure_role_hierarchy
from services.time_stuff import MidoTime

action_emotes = {
    'kick': '👢',
    'ban' : '🔨',
    'mute': '🔇'
}


class Moderation(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.check_modlogs.start()

    def cog_check(self, ctx):  # guild only
        if not ctx.guild:
            raise commands.NoPrivateMessage
        else:
            return True

    @staticmethod
    def parse_welcome_bye_msg(member: discord.Member, msg: str):
        placeholders = {
            "{member_name}"        : member.display_name,
            "{member_name_discrim}": str(member),
            "{member_mention}"     : member.mention,

            "{server_name}"        : str(member.guild),
            "{server_member_count}": member.guild.member_count
        }

        for k, v in placeholders.items():
            msg = msg.replace(k, str(v))

        return msg

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_db = await GuildDB.get_or_create(self.bot.db, guild_id=member.guild.id)
        if guild_db.welcome_channel_id:
            if guild_db.welcome_channel_id == 1:
                channel = member
            else:
                channel = self.bot.get_channel(guild_db.welcome_channel_id)

            await channel.send(self.parse_welcome_bye_msg(member=member, msg=guild_db.welcome_message))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild_db = await GuildDB.get_or_create(self.bot.db, guild_id=member.guild.id)
        if guild_db.bye_channel_id:
            channel = self.bot.get_channel(guild_db.bye_channel_id)
            await channel.send(self.parse_welcome_bye_msg(member=member, msg=guild_db.bye_message))

    @commands.command(aliases=['greet'])
    async def welcome(self,
                      ctx: MidoContext,
                      channel: typing.Union[discord.TextChannel, str] = None, *,
                      message: commands.clean_content = None):
        """Setup a channel to welcome new members with a customized message.

        **To use the default message**, leave the welcome message empty.
        **To disable this feature**, use the command without inputting any arguments.

        Available placeholders:
        `{{member_name}}` -> Inserts the name of the new member.
        `{{member_name_discrim}}` -> Inserts the name and discriminator of the new member.
        `{{member_mention}}` -> Mentions the new member.
        `{{server_name}}` -> Inserts the name of the server.
        `{{server_member_count}}` -> Inserts the member count of the server.

        Examples:
        `{0.prefix}welcome dm`
        (welcomes new members in DMs using the default message)
        `{0.prefix}welcome #welcome`
        (welcomes new members in #welcome using the default message)
        `{0.prefix}welcome #welcome Welcome {{member_name}}!`
        (welcomes new members in #welcome using a customized message)
        `{0.prefix}welcome`
        (disables this feature)
        """
        if not channel:
            if not ctx.guild_db.welcome_channel_id:
                return await ctx.send("Welcome feature has already been disabled.")
            else:
                await ctx.guild_db.set_welcome(channel_id=None)
                return await ctx.send("Welcome feature has been successfully disabled.")
        else:
            if isinstance(channel, str):
                if channel.lower() == 'dm':
                    channel_str = 'DMs'
                    channel_id = 1
                else:
                    raise commands.BadArgument("Invalid channel!")
            else:
                channel_str = channel.mention
                channel_id = channel.id

            if not message:
                message = 'Hey {member_mention}! Welcome to **{server_name}**.'

            await ctx.guild_db.set_welcome(channel_id=channel_id, msg=message)
            await ctx.send(f"Success! New members will be welcomed in {channel_str} with this mesage:\n"
                           f"`{message}`")

    @commands.command(aliases=['goodbye'])
    async def bye(self,
                  ctx: MidoContext,
                  channel: discord.TextChannel = None, *,
                  message: commands.clean_content = None):
        """Setup a channel to say goodbye to members that leave with a customized message.

        **To use the default message**, leave the goodbye message empty.
        **To disable this feature**, use the command without inputting any arguments.

        Available placeholders:
        `{{member_name}}` -> Inserts the name of the member that left.
        `{{member_name_discrim}}` -> Inserts the name and discriminator of the member that left.
        `{{member_mention}}` -> Mentions the member that left.
        `{{server_name}}` -> Inserts the name of the server.
        `{{server_member_count}}` -> Inserts the member count of the server.

        **Examples:**
        `{0.prefix}bye #bye`
        (says goodbye in #bye to members that left using the default message)
        `{0.prefix}bye #bye It's sad to see you go {{member_name}}...`
        (says goodbye in #bye to members that left using a customized message)
        `{0.prefix}bye`
        (disables this feature)
        """
        if not channel:
            if not ctx.guild_db.bye_channel_id:
                return await ctx.send("Goodbye feature has already been disabled.")
            else:
                await ctx.guild_db.set_bye(channel_id=None)
                return await ctx.send("Goodbye feature has been successfully disabled.")
        else:
            if not message:
                message = '{member_name_discrim} just left the server...'

            await ctx.guild_db.set_bye(channel_id=channel.id, msg=message)
            await ctx.send(f"Success! "
                           f"I'll now say goodbye in {channel.mention} to members that leave with this mesage:\n"
                           f"`{message}`")

    @tasks.loop(seconds=30.0)
    async def check_modlogs(self):
        open_modlogs = await self.bot.db.fetch(
            """
            SELECT 
                *
            FROM 
                modlogs 
            WHERE 
                length_in_seconds IS NOT NULL 
                AND type = ANY($1) 
                AND done IS NOT TRUE;""", [ModLog.Type.MUTE.value, ModLog.Type.BAN.value])

        for modlog in open_modlogs:
            # convert it to local obj
            modlog = ModLog(modlog, self.bot.db)

            # if its the time
            if modlog.time_status.end_date_has_passed:
                guild = self.bot.get_guild(modlog.guild_id)

                if modlog.type == ModLog.Type.BAN:
                    member = discord.Object(id=modlog.user_id)
                    await guild.unban(member, reason='ModLog time has expired. (Auto-Unban)')

                elif modlog.type == ModLog.Type.MUTE:
                    member = guild.get_member(modlog.user_id)
                    if member:
                        mute_role = await self.get_or_create_muted_role(guild)
                        if mute_role in member.roles:
                            await member.remove_roles(mute_role, reason='ModLog time has expired. (Auto-Unban)')

                await modlog.complete()

    def cog_unload(self):
        self.check_modlogs.cancel()

    @check_modlogs.before_loop
    async def before_modlog_checks(self):
        await self.bot.wait_until_ready()

    @staticmethod
    def get_reason_string(reason=None) -> str:
        return f' with reason: `{reason}`' if reason else '.'

    @staticmethod
    async def get_or_create_muted_role(ctx_or_guild: typing.Union[MidoContext, discord.Guild]):
        if isinstance(ctx_or_guild, MidoContext):
            ctx = ctx_or_guild
            guild = ctx.guild
        else:
            ctx = None
            guild = ctx_or_guild

        muted_role = discord.utils.find(lambda m: m.name.lower() == 'muted', guild.roles)

        if not muted_role:
            if ctx:
                msg = await ctx.send("Creating the mute role and configuring it, please wait...")

            muted_role = await guild.create_role(name='Muted',
                                                 reason="Mute role for the mute command.",
                                                 color=discord.Colour.dark_grey())

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
                        overwrite.send_messages = False
                        overwrite.add_reactions = False
                    # if its a voice channel
                    if isinstance(channel, discord.VoiceChannel):
                        overwrite.speak = False

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
    async def kick(self, ctx: MidoContext, target: MidoMemberConverter(), *, reason: commands.clean_content = None):
        """Kicks a user.

        You need the Kick Members permission to use this command.
        """

        await target.kick(reason=reason)
        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLog.Type.KICK)

        await ctx.send(f"`{modlog.id}` {action_emotes['kick']} "
                       f"User {getattr(target, 'mention', target.id)} has been **kicked** "
                       f"by {ctx.author.mention}"
                       f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self,
                  ctx: MidoContext,
                  target: MidoMemberConverter(),
                  length: typing.Union[MidoTime, str] = None,
                  *, reason: commands.clean_content = None):
        """Bans a user for a specified period of time or indefinitely.

        **Examples:**
            `{0.prefix}ban @Mido` (bans permanently)
            `{0.prefix}ban @Mido toxic` (bans permanently with a reason)
            `{0.prefix}ban @Mido 30m` (bans for 30 minutes)
            `{0.prefix}ban @Mido 3d toxic` (bans for 3 days with reason)

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

        await target.ban(reason=reason, delete_message_days=1)

        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLog.Type.BAN,
                                         length=length)

        await ctx.send(f"`{modlog.id}` {action_emotes['ban']} "
                       f"User **{getattr(target, 'mention', target.id)}** "
                       f"has been **banned** "
                       f"by {ctx.author.mention} "
                       f"for **{getattr(length, 'initial_remaining_string', 'permanently')}**"
                       f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self,
                    ctx: MidoContext,
                    target: MidoMemberConverter(),
                    *, reason: commands.clean_content = None):
        """Unbans a banned user.

        You need Ban Members permission to use this command.
        """

        user_is_banned = await ctx.guild.fetch_ban(target)
        if not user_is_banned:
            return await ctx.send("That user isn't banned.")

        else:
            await ctx.guild.unban(target, reason=f"User unbanned by {ctx.author}"
                                                 f"{self.get_reason_string(reason)}")

            await ModLog.add_modlog(db_conn=ctx.db,
                                    guild_id=ctx.guild.id,
                                    user_id=target.id,
                                    type=ModLog.Type.UNBAN,
                                    executor_id=ctx.author.id,
                                    reason=reason)

            await ctx.send(f"User **{getattr(target, 'mention', target.id)}** "
                           f"has been **unbanned** "
                           f"by {ctx.author.mention}"
                           f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def mute(self,
                   ctx: MidoContext,
                   target: MidoMemberConverter(),
                   length: typing.Union[MidoTime, str] = None,
                   *, reason: commands.clean_content = None):
        """Mutes a user for a specified period of time or indefinitely.

        **Examples:**
            `{0.prefix}mute @Mido` (mutes permanently)
            `{0.prefix}mute @Mido shitposting` (mutes permanently with a reason)
            `{0.prefix}mute @Mido 30m` (mutes for 30 minutes)
            `{0.prefix}mute @Mido 3d shitposting` (mutes for 3 days with reason)

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
            return await ctx.send("That user is already muted!")

        await target.add_roles(mute_role, reason=f"User muted by {ctx.author}"
                                                 f"{self.get_reason_string(reason)}")

        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLog.Type.MUTE,
                                         length=length)

        await ctx.send(f"`{modlog.id}` {action_emotes['mute']} "
                       f"User **{getattr(target, 'mention', target.id)}** "
                       f"has been **muted** "
                       f"by {ctx.author.mention} "
                       f"for **{getattr(length, 'initial_remaining_string', 'permanently')}**"
                       f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self,
                     ctx: MidoContext,
                     target: MidoMemberConverter(),
                     *, reason: commands.clean_content = None):
        """Unmutes a muted user.

        You need Manage Roles permission to use this command.
        """

        mute_role = await self.get_or_create_muted_role(ctx)

        if mute_role not in target.roles:
            return await ctx.send("That user is not muted!")

        await target.remove_roles(mute_role, reason=f"User unmuted by {ctx.author}"
                                                    f"{self.get_reason_string(reason)}")

        await ModLog.add_modlog(ctx.db,
                                guild_id=ctx.guild.id,
                                user_id=target.id,
                                reason=reason,
                                executor_id=ctx.author.id,
                                type=ModLog.Type.UNMUTE)

        await ctx.send(f"User **{getattr(target, 'mention', target.id)}** "
                       f"has been **unmuted** "
                       f"by {ctx.author.mention}"
                       f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.has_permissions(ban_members=True, kick_members=True)
    async def logs(self,
                   ctx: MidoContext,
                   target: MidoMemberConverter()):
        """See the logs of a user.

        You need Kick Members and Ban Members permissions to use this command.
        """

        logs = await ModLog.get_logs(ctx.db, ctx.guild.id, target.id)
        if not logs:
            return await ctx.send("No logs have been found for that user.")

        e = BaseEmbed(self.bot)
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

        await paginate(self.bot, ctx, blocks=log_blocks, embed=e, extra_sep='\n')

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def clearlogs(self,
                        ctx: MidoContext,
                        target: MidoMemberConverter()):
        """Clears the logs of a user.

        You need to have the Administrator permission to use this command.
        """

        msg = await ctx.send(f"Are you sure you'd like to reset the logs of **{target}**?")
        yes = await yes_no(self.bot, ctx.author.id, msg)

        if not yes:
            return await msg.edit(content="Request has been declined.")

        else:
            await ModLog.hide_logs(ctx.db, ctx.guild.id, target.id)

            return await msg.edit(content=f"Logs of **{target}** has been successfully deleted.")

    @commands.command(aliases=['changereason'])
    async def reason(self,
                     ctx: MidoContext,
                     case_id: int,
                     *, new_reason: commands.clean_content = None):
        """Update the reason of a case using its ID.

        You either need to be the executor of the case or have Administrator permission to use this command.
        """
        log = await ModLog.get_by_id(ctx.db, log_id=case_id, guild_id=ctx.guild.id)
        if not log:
            raise EmbedError("No logs have been found with that case ID.")

        if log.executor_id != ctx.author.id and not ctx.author.guild_permissions.administrator:
            raise EmbedError("You have to be the executor of this case "
                             "or have Administrator permission in the server to do that!")

        await log.change_reason(new_reason)

        await ctx.send_success(f"Reason of `{log.id}` has been successfully updated: `{new_reason}`")

    @commands.command(aliases=['sr', 'giverole', 'gr'])
    @commands.has_permissions(manage_roles=True)
    async def setrole(self,
                      ctx: MidoContext,
                      member: MidoMemberConverter(),
                      role: MidoRoleConverter()):
        """Give a role to a member.

        You need the **Manage Roles** permissions to use this command.
        """
        # already has that role check
        if role in member.roles:
            raise EmbedError(f"Member {member.mention} already has the {role.mention} role.")

        await member.add_roles(role, reason=f'Role has been added by {ctx.author}.')

        await ctx.send_success(f"Role {role.mention} has been successfully given to {member.mention}.")

    @commands.command(aliases=['rr'])
    @commands.has_permissions(manage_roles=True)
    async def removerole(self,
                         ctx: MidoContext,
                         member: MidoMemberConverter(),
                         role: MidoRoleConverter()):
        """Remove a role from a member.

        You need the **Manage Roles** permissions to use this command.
        """

        # if they dont have the role
        if role not in member.roles:
            raise EmbedError(f"Member {member.mention} don't have the {role.mention} role.")

        await member.remove_roles(role, reason=f'Role has been removed by {ctx.author}.')

        await ctx.send_success(f"Role {role.mention} has been successfully removed from {member.mention}.")

    @commands.command(aliases=['cr'])
    @commands.has_permissions(manage_roles=True)
    async def createrole(self,
                         ctx: MidoContext,
                         role_name: str):
        """Create a role.

        You need the **Manage Roles** permissions to use this command.
        """
        role = await ctx.guild.create_role(name=role_name,
                                           reason=f'Role was created using {ctx.prefix}createrole')

        await ctx.send_success(f"Role {role.mention} has been successfully created!")

    @commands.command(aliases=['dr'])
    @commands.has_permissions(manage_roles=True)
    async def deleterole(self,
                         ctx: MidoContext,
                         role: MidoRoleConverter()):
        """Delete a role from the server.

        You need the **Manage Roles** permissions to use this command.
        """

        await role.delete(reason=f'Role got deleted by {ctx.author}.')

        await ctx.send_success(f"Role `{role}` has been successfully deleted.")

    @setrole.before_invoke
    @removerole.before_invoke
    @deleterole.before_invoke
    async def _ensure_role_hierarchy(self, ctx):
        ensure_role_hierarchy(ctx)

    @commands.command(aliases=['purge'])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def prune(self, ctx: MidoContext, number: int, target_user: MidoMemberConverter() = None):
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
            raise EmbedError("Invalid message amount. It can't be less than or equal to 0.")
        elif number > 100:
            number = 100

        # first delete the command msg
        await ctx.message.delete()

        # then delete the rest
        deleted = await ctx.channel.purge(limit=number, check=prune_check, bulk=True)

        return await ctx.send_success(f"Successfully deleted **{len(deleted)}** messages.")


def setup(bot):
    bot.add_cog(Moderation(bot))
