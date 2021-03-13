from discord.ext import commands

import mido_utils
from midobot import MidoBot


class AssignableRoles(commands.Cog, name='Assignable Roles'):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command(name='addassignablerole', aliases=['aar'])
    @commands.has_permissions(manage_roles=True)
    async def add_assignable_role(self,
                                  ctx: mido_utils.Context,
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
                         role: mido_utils.RoleConverter()):
        """Leave an assignable role."""
        if role.id not in ctx.guild_db.assignable_role_ids:
            raise commands.UserInputError("That role is not assignable.")

        # already has that role check
        if role not in ctx.author.roles:
            raise commands.UserInputError(f"You don't even the {role.mention} role.")

        await ctx.author.remove_roles(role, reason=f'Role has been removed using {ctx.prefix}leave')

        await ctx.send_success(f"Role {role.mention} has been successfully removed from you!")

    @add_assignable_role.before_invoke
    @remove_assignable_role.before_invoke
    async def _ensure_role_hierarchy(self, ctx):
        mido_utils.ensure_role_hierarchy(ctx)


def setup(bot):
    bot.add_cog(AssignableRoles(bot))
