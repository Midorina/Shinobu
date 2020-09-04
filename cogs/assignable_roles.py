from discord.ext import commands

from main import MidoBot
from services.context import MidoContext
from services.converters import MidoRoleConverter
from services.embed import MidoEmbed
from services.exceptions import EmbedError
from services.security_stuff import ensure_role_hierarchy


class AssignableRoles(commands.Cog, name='Assignable Roles'):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command(aliases=['aar'])
    @commands.has_permissions(manage_roles=True)
    async def addassignablerole(self,
                                ctx: MidoContext,
                                role: MidoRoleConverter()):
        """Add an assignable role.

        You need the **Manage Roles** permissions to use this command.
        """

        if role.id in ctx.guild_db.assignable_role_ids:
            raise EmbedError(f"Role {role.mention} is already in your assignable role list.")

        await ctx.guild_db.add_assignable_role(role_id=role.id)

        await ctx.send_success(f"Role {role.mention} has been successfully added to the assignable role list.")

    @commands.command(aliases=['rar'])
    @commands.has_permissions(manage_roles=True)
    async def removeassignablerole(self,
                                   ctx: MidoContext,
                                   role: MidoRoleConverter()):
        """Remove a role from the assignable role list.

        You need the **Manage Roles** permissions to use this command.
        """

        if role.id not in ctx.guild_db.assignable_role_ids:
            raise EmbedError(f"Role {role.mention} is not in your assignable role list.")

        await ctx.guild_db.remove_assignable_role(role_id=role.id)

        await ctx.send_success(f"Role {role.mention} has been successfully removed from the assignable role list.")

    @commands.command(aliases=['ear'])
    @commands.has_permissions(manage_roles=True)
    async def exclusiveassignablerole(self,
                                      ctx: MidoContext):
        """Toggle exclusive assignable roles. If enabled, users can only have 1 assignable role.

        You need the **Manage Roles** permissions to use this command.
        """
        await ctx.guild_db.toggle_exclusive_assignable_roles()

        if ctx.guild_db.assignable_roles_are_exclusive:
            await ctx.send_success("Assignable roles are exclusive from now on.")
        else:
            await ctx.send_success("Assignable roles are no longer exclusive.")

    @commands.command(aliases=['lar'])
    @commands.has_permissions(manage_roles=True)
    async def listassignableroles(self,
                                  ctx: MidoContext):
        """List all assignable roles available.

        You need the **Manage Roles** permissions to use this command.
        """
        e = MidoEmbed(bot=ctx.bot, title="Assignable Roles", default_footer=True)
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

    @commands.command(aliases=['iam'])
    @commands.has_permissions(manage_roles=True)
    async def join(self,
                   ctx: MidoContext,
                   role: MidoRoleConverter()):
        """Join an assignable role."""
        if role.id not in ctx.guild_db.assignable_role_ids:
            raise EmbedError("That role is not assignable.")

        # already has that role check
        if role in ctx.author.roles:
            raise EmbedError(f"You already have the {role.mention} role.")

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

    @commands.command(aliases=['iamn'])
    @commands.has_permissions(manage_roles=True)
    async def leave(self,
                    ctx: MidoContext,
                    role: MidoRoleConverter()):
        """Leave an assignable role."""
        if role.id not in ctx.guild_db.assignable_role_ids:
            raise EmbedError("That role is not assignable.")

        # already has that role check
        if role not in ctx.author.roles:
            raise EmbedError(f"You don't even the {role.mention} role.")

        await ctx.author.remove_roles(role, reason=f'Role has been removed using {ctx.prefix}leave')

        await ctx.send_success(f"Role {role.mention} has been successfully removed from you!")

    @addassignablerole.before_invoke
    @removeassignablerole.before_invoke
    async def _ensure_role_hierarchy(self, ctx):
        ensure_role_hierarchy(ctx)


def setup(bot):
    bot.add_cog(AssignableRoles(bot))
