import typing

import discord
from discord.ext import commands, tasks

from db.models import ModLog
from main import MidoBot
from services import base_embed, menu_stuff
from services.context import MidoContext
from services.converters import BetterMemberconverter
from services.time import MidoTime

action_emotes = {
    'kick': '👢',
    'ban': '🔨',
    'mute': '🔇'
}


class Moderation(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.check_modlogs.start()

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
    def get_reason_string(reason=None):
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
                                           "please delete the role Muted role and use the mute command again "
                                           "after giving me proper permissions.")
                else:
                    await msg.edit(content="Mute role has been successfully created and configured for all channels!")

        return muted_role

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: MidoContext, target: BetterMemberconverter(), *, reason: str = None):
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
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self,
                  ctx: MidoContext,
                  target: BetterMemberconverter(),
                  length: typing.Union[MidoTime, str] = None,
                  *, reason: str = None):
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
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self,
                    ctx: MidoContext,
                    target: BetterMemberconverter(),
                    *, reason: str = None):
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
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def mute(self,
                   ctx: MidoContext,
                   target: BetterMemberconverter(),
                   length: typing.Union[MidoTime, str] = None,
                   *, reason: str = None):
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
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(self,
                     ctx: MidoContext,
                     target: BetterMemberconverter(),
                     *, reason: str = None):
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
    @commands.guild_only()
    @commands.has_permissions(ban_members=True, kick_members=True)
    async def logs(self,
                   ctx: MidoContext,
                   target: BetterMemberconverter()):
        """See the logs of a user.

        You need Kick Members and Ban Members permissions to use this command.
        """

        logs = await ModLog.get_logs(ctx.db, ctx.guild.id, target.id)
        if not logs:
            return await ctx.send("No logs have been found for that user.")

        e = base_embed.BaseEmbed(self.bot)
        e.set_author(icon_url=getattr(target, 'avatar_url', None),
                     name=f"Logs of {target}")
        e.set_footer(text=f"{len(logs)} Logs")

        log_blocks = []
        for log in logs:
            log_description = f"**Case ID:** `{log.id}` {log.date.strftime('%Y-%m-%d, %H:%M:%S UTC')}\n" \
                              f"**Action:** {log.type.name.title()} {action_emotes[log.type.name.lower()]}\n"

            if log.length_string:
                log_description += f'**Length:** {log.length_string}\n'

            if log.reason:
                log_description += f"**Reason:** {log.reason}\n"

            log_description += f"**Executor:** <@{log.executor_id}>"

            log_blocks.append(log_description)

        await menu_stuff.paginate(self.bot, ctx, blocks=log_blocks, embed=e, extra_sep='\n')

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def clearlogs(self,
                        ctx: MidoContext,
                        target: BetterMemberconverter()):
        """Clears the logs of a user.

        You need to have the Administrator permission to use this command.
        """

        msg = await ctx.send(f"Are you sure you'd like to reset the logs of **{target}**?")
        yes = await menu_stuff.yes_no(self.bot, ctx.author.id, msg)

        if not yes:
            return await msg.edit(content="Request has been declined.")

        else:
            await ModLog.hide_logs(ctx.db, ctx.guild.id, target.id)

            return await msg.edit(content=f"Logs of **{target}** has been successfully deleted.")

    @commands.command(aliases=['changereason'])
    @commands.guild_only()
    async def reason(self,
                     ctx: MidoContext,
                     case_id: int,
                     *, new_reason: str = None):
        """Update the reason of a case using its ID.

        You either need to be the executor of the case or have Administrator permission to use this command.
        """
        log = await ModLog.get_by_id(ctx.db, log_id=case_id, guild_id=ctx.guild.id)
        if not log:
            return await ctx.send("No logs have been found with that case ID.")

        if log.executor_id != ctx.author.id and not ctx.author.guild_permissions.administrator:
            return await ctx.send("You have to be the executor of this case "
                                  "or have Administrator permission in the server to do that!")

        await log.change_reason(new_reason)

        await ctx.send(f"Reason of `{log.id}` has been successfully updated: `{new_reason}`")


def setup(bot):
    bot.add_cog(Moderation(bot))
