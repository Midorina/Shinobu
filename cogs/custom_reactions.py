import discord
from discord.ext import commands

from midobot import MidoBot
from models.db_models import CustomReaction
from services.checks import is_owner
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import EmbedError
from services.parsers import parse_text_with_context


def toggle_message(option_name: str, cr: CustomReaction, option_status: bool) -> str:
    def keyword(_enabled: bool):
        return 'enabled' if _enabled else 'disabled'

    return f'**{option_name}** option is now **{keyword(option_status)}**' \
           f' for custom reaction with ID `{cr.id}`.'


class CustomReactions(commands.Cog, name='Custom Reactions'):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.bot.is_ready() or message.author.bot or not message.guild:
            return False

        cr = await CustomReaction.try_get(self.bot, msg=message.content, guild_id=message.guild.id)

        if cr and cr.response != '-':
            self.bot.loop.create_task(cr.increase_use_count())

            channel_to_send = message.author if cr.send_in_DM else message.channel

            content, embed = parse_text_with_context(text=cr.response,
                                                     bot=self.bot,
                                                     guild=message.guild,
                                                     author=message.author,
                                                     channel=channel_to_send,
                                                     message_obj=message)

            try:
                await channel_to_send.send(content=content, embed=embed)
            except discord.Forbidden:
                pass
            else:
                if cr.delete_trigger:
                    await message.delete()

                self.bot.logger.info(f"User [{message.author}] "
                                     f"executed custom reaction [{cr.trigger}]"
                                     f" in [{message.guild}].")

    def get_cr_embed(self, cr: CustomReaction):
        e = MidoEmbed(bot=self.bot)
        e.add_field(name="Trigger", value=cr.trigger, inline=False)
        e.add_field(name="Response", value=cr.response)
        e.set_footer(text=f'ID: {cr.id}')

        return e

    @commands.has_permissions(administrator=True)
    @commands.command(aliases=['acr'])
    async def addcustomreaction(self, ctx: MidoContext, trigger: str, *, response):
        """Add a custom reaction with a trigger and a response.
        Running this command in server requires the Administration permission.

        http://nadekobot.readthedocs.io/en/latest/custom-reactions/"""

        cr = await CustomReaction.add(bot=ctx.bot,
                                      trigger=trigger,
                                      response=response,
                                      guild_id=ctx.guild.id)

        e = self.get_cr_embed(cr)
        e.title = "New Custom Reaction"

        await ctx.send(embed=e)

    @commands.command(aliases=['lcr'])
    async def listcustomreactions(self, ctx: MidoContext):
        """List all custom reactions of the server.
        If you use this command in DMs, it'll show you the global custom reactions."""

        crs = await CustomReaction.get_all(bot=ctx.bot,
                                           guild_id=ctx.guild.id if ctx.guild else None)

        e = MidoEmbed(bot=self.bot,
                      title='Custom Reactions' if ctx.guild else 'Global Custom Reactions')

        if not crs:
            e.description = "No custom reaction found."
            return await ctx.send(embed=e)

        blocks = []
        for cr in crs:
            blocks.append(f'`{cr.id}` {cr.trigger}')

        await e.paginate(ctx=ctx, blocks=blocks)

    @commands.command(aliases=['scr'])
    async def showcustomreaction(self, ctx: MidoContext, custom_reaction: CustomReaction):
        """Shows a custom reaction's response on a given ID."""

        await ctx.send(embed=self.get_cr_embed(custom_reaction))

    @commands.has_permissions(administrator=True)
    @commands.command(aliases=['crclear'])
    async def customreactionsclear(self, ctx: MidoContext):
        """Deletes all custom reactions on this server."""

        e = MidoEmbed(bot=self.bot,
                      description="Are you sure you want to delete every custom reaction in this server?")
        msg = await ctx.send(embed=e)

        yes = await MidoEmbed.yes_no(bot=self.bot, author_id=ctx.author.id, msg=msg)
        if yes:
            await CustomReaction.delete_all(bot=ctx.bot, guild_id=ctx.guild.id)

            await ctx.edit_custom(msg, "All custom reactions have been successfully deleted.")
        else:
            await ctx.edit_custom(msg, "Request declined.")

    @commands.command(aliases=['dcr'])
    async def deletecustomreaction(self, ctx: MidoContext, custom_reaction: CustomReaction):
        """Delete a custom reaction using it's ID.
        You can see the list of custom reactions using `{0.prefix}lcr`

        You need Administrator permission to use this command."""

        await custom_reaction.delete_from_db()

        e = self.get_cr_embed(custom_reaction)
        e.title = "Custom Reaction Deleted"

        await ctx.send(embed=e)

    @commands.command()
    async def crca(self, ctx: MidoContext, custom_reaction: CustomReaction):
        """Toggles whether the custom reaction will trigger
        if the triggering message contains the keyword (instead of only starting with it)."""
        await custom_reaction.toggle_contains_anywhere()

        await ctx.send_success(
            toggle_message(option_name='Contains Anywhere',
                           cr=custom_reaction,
                           option_status=custom_reaction.contains_anywhere))

    @commands.command()
    async def crdm(self, ctx: MidoContext, custom_reaction: CustomReaction):
        """Toggles whether the response message of the custom reaction will be sent as a direct message."""
        await custom_reaction.toggle_dm()

        await ctx.send_success(
            toggle_message(option_name='Respond in DM',
                           cr=custom_reaction,
                           option_status=custom_reaction.send_in_DM))

    @commands.command()
    async def crad(self, ctx: MidoContext, custom_reaction: CustomReaction):
        """Toggles whether the message triggering the custom reaction will be automatically deleted."""
        await custom_reaction.toggle_delete_trigger()

        await ctx.send_success(
            toggle_message(option_name='Delete the Trigger',
                           cr=custom_reaction,
                           option_status=custom_reaction.delete_trigger))

    @deletecustomreaction.before_invoke
    @crca.before_invoke
    @crad.before_invoke
    @crdm.before_invoke
    async def ensure_cr_ownership(self, ctx: MidoContext):
        cr: CustomReaction = ctx.args[2]  # arg after the context

        if not cr.guild_id:  # if its global
            if not is_owner(ctx.author.id, ctx.bot):  # and not owner
                raise EmbedError(f"You can not delete a global custom reaction!\n"
                                 f"Use `{ctx.prefix}acr \"{cr.trigger}\" -` to disable "
                                 f"this global custom reaction for your server.")
        else:
            if cr.guild_id != ctx.guild.id:  # if it belongs to a different server
                raise EmbedError("This custom reaction belongs to a different server!")
            elif not ctx.author.guild_permissions.administrator:
                raise commands.MissingPermissions


def setup(bot):
    bot.add_cog(CustomReactions(bot))
