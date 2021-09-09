import typing

import discord
from discord.ext import commands

import mido_utils
from models import GuildDB
from shinobu import ShinobuBot


class AssignableRoles(
    commands.Cog, name='Assignable Roles',
    description='You can use the `{ctx.prefix}welcomerole` command to '
                'automatically assign a role to new members '
                'or `{ctx.prefix}aar` to add a self assignable role for all members '
                'which can be acquired using `{ctx.prefix}iam`.'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

    def cog_check(self, ctx):  # guild only
        if not ctx.guild:
            raise commands.NoPrivateMessage
        else:
            return True

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_db = await GuildDB.get_or_create(bot=self.bot, guild_id=member.guild.id)

        # welcome role
        if guild_db.welcome_role_id:
            role = member.guild.get_role(guild_db.welcome_role_id)
            if not role:
                await member.guild.owner.send(f"The welcome role of guild **{member.guild}** seems to be deleted, "
                                              f"so I'm resetting my welcome role configuration.")
                return await guild_db.set_welcome_role(None)

            try:
                await member.add_roles(role, reason="Welcome role.")
            except discord.Forbidden:
                await member.guild.owner.send(f"I've tried to add the {role.mention} role "
                                              f"to the new member {member.mention} "
                                              f"but I'm missing permissions. Please make sure "
                                              f"my role is higher than {role.mention} in the role hierarchy "
                                              f"and my role has Manage Roles permission.")

        # welcome message
        if guild_db.welcome_channel_id:
            if guild_db.welcome_channel_id == 1:
                channel = member
            else:
                channel = self.bot.get_channel(guild_db.welcome_channel_id)
                if not channel:
                    return await guild_db.set_welcome(channel_id=None)  # reset

            content, embed = await mido_utils.parse_text_with_context(
                text=guild_db.welcome_message,
                bot=self.bot,
                guild=member.guild,
                author=member,
                channel=channel)
            try:
                await channel.send(content=content,
                                   embed=embed,
                                   delete_after=guild_db.welcome_delete_after)
            except (discord.Forbidden, discord.HTTPException):
                pass
            except Exception as e:
                await self.bot.get_cog('ErrorHandling').on_error(
                    f"Error happened while sending welcome message for guild id `{member.guild.id}`: {e}")
                return

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.id == self.bot.user.id:
            # if we're the one who left, ignore
            return

        guild_db = await GuildDB.get_or_create(bot=self.bot, guild_id=member.guild.id)
        if guild_db.bye_channel_id:
            channel = self.bot.get_channel(guild_db.bye_channel_id)
            if not channel:
                return await guild_db.set_bye()  # reset

            content, embed = await mido_utils.parse_text_with_context(
                text=guild_db.bye_message,
                bot=self.bot,
                guild=member.guild,
                author=member,
                channel=channel)
            try:
                await channel.send(content=content,
                                   embed=embed,
                                   delete_after=guild_db.welcome_delete_after)
            except discord.Forbidden:
                pass
            except Exception as e:
                await self.bot.get_cog('ErrorHandling').on_error(
                    f"Error happened while sending bye message for guild id `{member.guild.id}`: {e}")
                return

    @commands.command(name='addassignablerole', aliases=['aar'])
    @commands.has_permissions(manage_roles=True)
    async def add_assignable_role(self,
                                  ctx: mido_utils.Context,
                                  *,
                                  role: mido_utils.RoleConverter()):
        """Add an assignable role.

        You need the **Manage Roles** permissions to use this command.
        """
        if role.id in ctx.guild_db.assignable_role_ids:
            raise commands.UserInputError(f"Role {role.mention} is already in your assignable role list.")

        await ctx.guild_db.add_assignable_role(role_id=role.id)

        await ctx.send_success(f"Role {role.mention} has been successfully added to the assignable role list.")

    @commands.command(name='removeassignablerole', aliases=['rar'])
    @commands.has_permissions(manage_roles=True)
    async def remove_assignable_role(self,
                                     ctx: mido_utils.Context,
                                     *,
                                     role: mido_utils.RoleConverter()):
        """Remove a role from the assignable role list.

        You need the **Manage Roles** permissions to use this command.
        """
        if role.id not in ctx.guild_db.assignable_role_ids:
            raise commands.UserInputError(f"Role {role.mention} is not in your assignable role list.")

        await ctx.guild_db.remove_assignable_role(role_id=role.id)

        await ctx.send_success(f"Role {role.mention} has been successfully removed from the assignable role list.")

    @commands.command(name='exclusiveassignablerole', aliases=['ear'])
    @commands.has_permissions(manage_roles=True)
    async def exclusive_assignable_role(self,
                                        ctx: mido_utils.Context):
        """Toggle exclusive assignable roles. If enabled, users can only have 1 assignable role.

        You need the **Manage Roles** permissions to use this command.
        """
        await ctx.guild_db.toggle_exclusive_assignable_roles()

        if ctx.guild_db.assignable_roles_are_exclusive:
            await ctx.send_success("Assignable roles are exclusive from now on.")
        else:
            await ctx.send_success("Assignable roles are no longer exclusive.")

    @commands.command(name='listassignableroles', aliases=['lsar', 'lar'])
    async def list_assignable_roles(self,
                                    ctx: mido_utils.Context):
        """List all assignable roles available.

        You need the **Manage Roles** permissions to use this command.
        """
        e = mido_utils.Embed(bot=ctx.bot, title="Assignable Roles", default_footer=True)
        e.set_footer(text=f"Assignable Roles Are Exclusive: {ctx.guild_db.assignable_roles_are_exclusive}")

        if ctx.guild_db.assignable_role_ids:
            e.description = ""
            index = 1  # this is cuz if we cant find the role, it'll skip an index
            for role_id in ctx.guild_db.assignable_role_ids:
                role = ctx.guild.get_role(role_id)
                if not role:
                    await ctx.guild_db.remove_assignable_role(role_id)
                else:
                    e.description += f"{index}. {role.mention} \n"
                    index += 1
        else:
            e.description = f"No assignable roles. You can add one using `{ctx.prefix}aar`"

        await ctx.send(embed=e)

    @commands.command(name='iam')
    async def join_role(self,
                        ctx: mido_utils.Context,
                        *,
                        role: mido_utils.RoleConverter()):
        """Join an assignable role."""
        if role.id not in ctx.guild_db.assignable_role_ids:
            raise commands.UserInputError("That role is not assignable.")

        # already has that role check
        if role in ctx.author.roles:
            raise commands.UserInputError(f"You already have the {role.mention} role.")

        await ctx.author.add_roles(role, reason=f'Role has been added using {ctx.prefix}join')

        if ctx.guild_db.assignable_roles_are_exclusive:
            for role_id in ctx.guild_db.assignable_role_ids:
                _role = ctx.guild.get_role(role_id)

                if not _role:
                    await ctx.guild_db.remove_assignable_role(role_id)
                elif role_id != role.id:
                    await ctx.author.remove_roles(_role,
                                                  reason=f'Role has been removed cuz assignable roles are exclusive.')

        await ctx.send_success(f"Role {role.mention} has been successfully given to you!")

    @commands.command(name='iamnot', aliases=['iamn'])
    async def leave_role(self,
                         ctx: mido_utils.Context,
                         *,
                         role: mido_utils.RoleConverter()):
        """Leave an assignable role."""
        if role.id not in ctx.guild_db.assignable_role_ids:
            raise commands.UserInputError("That role is not assignable.")

        # already has that role check
        if role not in ctx.author.roles:
            raise commands.UserInputError(f"You don't even the {role.mention} role.")

        await ctx.author.remove_roles(role, reason=f'Role has been removed using {ctx.prefix}leave')

        await ctx.send_success(f"Role {role.mention} has been successfully removed from you!")

    @commands.has_permissions(administrator=True)
    @commands.command(aliases=['greet'])
    async def welcome(self,
                      ctx: mido_utils.Context,
                      channel: typing.Union[discord.TextChannel, str] = None, *,
                      message: commands.clean_content = None):
        """Setup a channel to welcome new members with a customized message.

        **To use the default message**, leave the welcome message empty.
        **To disable this feature**, use the command without inputting any arguments.

        Available placeholders: https://nadekobot.readthedocs.io/en/latest/placeholders/

        Examples:
        `{ctx.prefix}welcome dm`
        (welcomes new members in DMs using the default message)
        `{ctx.prefix}welcome #welcome`
        (welcomes new members in #welcome using the default message)
        `{ctx.prefix}welcome #welcome Welcome %user.mention%!`
        (welcomes new members in #welcome using a customized message)
        `{ctx.prefix}welcome`
        (disables this feature)
        """
        if not channel:
            if not ctx.guild_db.welcome_channel_id:
                raise commands.BadArgument("Welcome feature has already been disabled.")
            else:
                await ctx.guild_db.set_welcome(channel_id=None)
                return await ctx.send_success("Welcome feature has been successfully disabled.")
        else:
            if isinstance(channel, str):
                if channel.lower() == 'dm':
                    channel_str = 'DMs'
                    channel_id = 1
                else:
                    raise commands.ChannelNotFound("Invalid channel!")
            else:
                channel_str = channel.mention
                channel_id = channel.id

            if not message:
                message = 'Welcome to the %server.name%, %user.mention%!'

            await ctx.guild_db.set_welcome(channel_id=channel_id, msg=message)
            await ctx.send_success(f"Success! New members will be welcomed in {channel_str} with this mesage:\n"
                                   f"`{message}`")

    @commands.has_permissions(administrator=True)
    @commands.command(aliases=['goodbye'])
    async def bye(self,
                  ctx: mido_utils.Context,
                  channel: discord.TextChannel = None, *,
                  message: commands.clean_content = None):
        """Setup a channel to say goodbye to members that leave with a customized message.

        **To use the default message**, leave the goodbye message empty.
        **To disable this feature**, use the command without inputting any arguments.

        Available placeholders: https://nadekobot.readthedocs.io/en/latest/placeholders/

        **Examples:**
        `{ctx.prefix}bye #bye`
        (says goodbye in #bye to members that left using the default message)
        `{ctx.prefix}bye #bye It's sad to see you go %user.name%...`
        (says goodbye in #bye to members that left using a customized message)
        `{ctx.prefix}bye`
        (disables this feature)
        """
        if not channel:
            if not ctx.guild_db.bye_channel_id:
                raise commands.BadArgument("Goodbye feature has already been disabled.")
            else:
                await ctx.guild_db.set_bye(channel_id=None)
                return await ctx.send_success("Goodbye feature has been successfully disabled.")

        else:
            if not message:
                message = '%user.mention% just left the server...'

            await ctx.guild_db.set_bye(channel_id=channel.id, msg=message)
            await ctx.send_success(f"Success! "
                                   f"I'll now say goodbye in {channel.mention} to members that leave "
                                   f"with this mesage:\n"
                                   f"`{message}`")

    @commands.command(name='welcomerole', aliases=['newmemberrole'])
    @commands.has_permissions(manage_roles=True)
    async def new_member_role(self,
                              ctx: mido_utils.Context,
                              *,
                              role: mido_utils.RoleConverter() = None):
        """Set a role to give to new members automatically.

        Provide no arguments to disable it. For example: `{ctx.prefix}welcomerole`
        """
        existing_welcome_role = ctx.guild_db.welcome_role_id

        if role:
            mido_utils.ensure_role_hierarchy(ctx, role)

        await ctx.guild_db.set_welcome_role(role.id if role else None)

        if existing_welcome_role:
            if not role:
                return await ctx.send_success(f"Previous welcome role <@&{existing_welcome_role}> has been disabled.")
            else:
                base_message = f"I've successfully changed the welcome role " \
                               f"from <@&{existing_welcome_role}> to {role.mention}."
        else:
            if not role:
                raise commands.BadArgument("This server does not have any welcome role set.")

            base_message = f"I've successfully set {role.mention} as the welcome role."

        m = await ctx.send_success(f"{base_message}\n"
                                   f"\n"
                                   f"Would you like me to give this role to everyone in this server?")
        yes = await mido_utils.Embed.yes_no(ctx.bot, ctx.author.id, m)
        if yes:
            await ctx.edit_custom(m, f"{base_message}\n"
                                     f"\n"
                                     f"Alright! I'll give this role to everyone in this server. "
                                     f"This will take a while...\n"
                                     f"*You can type `{ctx.prefix}inrole {role.name}` to see the progress.*")

            for member in ctx.guild.members:
                if role.id not in [x.id for x in member.roles]:
                    await member.add_roles(role, reason="New welcome role.")

            await ctx.edit_custom(m, f"{base_message}\n"
                                     f"\n"
                                     f"~~Alright! I'll give this role to everyone in this server. "
                                     f"This will take a while...~~\n"
                                     f"\n"
                                     f"Done.")
        else:
            await ctx.edit_custom(m, base_message)
            await m.clear_reactions()

    @add_assignable_role.before_invoke
    @remove_assignable_role.before_invoke
    async def _ensure_role_hierarchy(self, ctx):
        mido_utils.ensure_role_hierarchy(ctx)


def setup(bot):
    bot.add_cog(AssignableRoles(bot))
