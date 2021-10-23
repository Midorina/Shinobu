import discord
from discord.ext import commands

import mido_utils
from models.db import CustomReaction
from shinobu import ShinobuBot


# todo: cooldown to crs
# todo: try to post the custom reaction before it is set and check if it errors
def cr_toggle_message(option_name: str, cr: CustomReaction, option_status: bool) -> str:
    def keyword(_enabled: bool):
        return 'enabled' if _enabled else 'disabled'

    return f'**{option_name}** option is now **{keyword(option_status)}**' \
           f' for custom reaction with ID `{cr.id}`.'


class CustomReactions(
    commands.Cog, name='Custom Reactions',
    description='You can add custom reactions with a trigger and a response using `{ctx.prefix}acr`.'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.bot.loop.create_task(self.check_cr_db_func())

    async def check_cr_db_func(self):
        """PSQL function to escape special characters"""
        time = mido_utils.Time()
        exists = await self.bot.db.fetchval("SELECT EXISTS(SELECT * FROM pg_proc WHERE proname = 'f_like_escape');")
        if not exists:
            await self.bot.db.execute("""
                CREATE OR REPLACE FUNCTION f_like_escape(text)
                  RETURNS text  LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS
                $func$
                SELECT REPLACE(REPLACE(REPLACE($1
                         , '\', '\\')  -- must come 1st
                         , '%', '\%')
                         , '_', '\_');
                $func$;
                """)
        self.bot.logger.debug("Checking CR DB function took:\t" + time.passed_seconds_in_float_formatted)

    async def base_cr_on_message(self, message: discord.Message):
        """This on_message function is used to check whether a message triggered a custom reaction or not."""
        if not self.bot.should_listen_to_msg(message, guild_only=True):
            return False

        try:
            cr = await CustomReaction.try_get(
                self.bot,
                msg=message.content.replace('\x00', ''),  # remove 0x00
                guild_id=message.guild.id)

        except Exception:
            await self.bot.get_cog('ErrorHandling').on_error(f"CR error happened with message: {message.content}")
            return

        if cr and cr.response != '-':
            channel_to_send = message.author if cr.send_in_DM else message.channel

            # message.guild is guaranteed as we make guild only check at the beginning of this func
            # so suppress the type checker
            # noinspection PyTypeChecker
            content, embed = await mido_utils.parse_text_with_context(text=cr.response,
                                                                      bot=self.bot,
                                                                      guild=message.guild,
                                                                      author=message.author,
                                                                      channel=channel_to_send,
                                                                      message_obj=message)
            try:
                await channel_to_send.send(content=content, embed=embed)
                if cr.delete_trigger:
                    await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            except discord.HTTPException as e:
                if e.status < 500:  # if not an internal server error
                    await channel_to_send.send(
                        f"There was an error while sending the custom reaction. "
                        f"It's most likely a bad embed structure.\n"
                        f"```{str(e)[:1000]}```"
                        f"I am deleting the custom reaction so that you can re-create it easily. "
                        f"Please try to put a properly built embed next time.\n"
                    )
                    await cr.delete_from_db()

                    self.bot.logger.debug(f"Was not able to send the embed "
                                          f"in custom reaction with ID: {cr.id}\n"
                                          f"Embed content: {embed.to_dict() if embed else None}")
            else:
                self.bot.logger.info(f"User [{message.author}] "
                                     f"executed custom reaction [{cr.trigger}]"
                                     f" in [{message.guild}].")
                await cr.increase_use_count()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        time = mido_utils.Time()
        await self.base_cr_on_message(message)
        self.bot.logger.debug(
            'Checking custom reaction took:\t' + time.passed_seconds_in_float_formatted)

    def get_cr_embed(self, cr: CustomReaction):
        e = mido_utils.Embed(bot=self.bot)
        e.add_field(name="Trigger", value=cr.trigger[:1024], inline=False)
        e.add_field(name="Response", value=cr.response[:1024])
        e.set_footer(text=f'ID: {cr.id}')

        return e

    @commands.command(name='addcustomreaction', aliases=['acr'])
    async def add_custom_reaction(self, ctx: mido_utils.Context, trigger: str, *, response):
        """Add a custom reaction with a trigger and a response.
        Running this command in server requires the Administration permission.

        https://nadekobot.readthedocs.io/en/latest/custom-reactions/
        You can use an embed as well. https://leovoel.github.io/embed-visualizer/"""

        if ctx.guild:
            if not ctx.author.guild_permissions.administrator:
                raise commands.MissingPermissions(['administrator'])
        else:
            if not await ctx.bot.is_owner(ctx.author):
                raise commands.NotOwner("You have to be in a server to add a custom reaction.")

        guild_id = ctx.guild.id if ctx.guild else None
        cr = await CustomReaction.add(bot=ctx.bot,
                                      trigger=trigger,
                                      response=response,
                                      guild_id=guild_id)

        e = self.get_cr_embed(cr)
        e.title = "New Custom Reaction"

        await ctx.send(embed=e)

    @commands.command(name='listcustomreactions', aliases=['lcr'])
    async def list_custom_reactions(self, ctx: mido_utils.Context):
        """List all custom reactions of the server.
        If you use this command in DMs, it'll show you the global custom reactions."""

        crs = await CustomReaction.get_all(bot=ctx.bot,
                                           guild_id=ctx.guild.id if ctx.guild else None)

        e = mido_utils.Embed(bot=self.bot,
                             title='Custom Reactions' if ctx.guild else 'Global Custom Reactions')

        if not crs:
            e.description = "No custom reaction found."
            return await ctx.send(embed=e)

        blocks = []
        for cr in crs:
            blocks.append(f'`{cr.id}` {cr.trigger}')

        await e.paginate(ctx=ctx, blocks=blocks, item_per_page=15)

    @commands.command(name='showcustomreaction', aliases=['scr'])
    async def show_custom_reaction(self, ctx: mido_utils.Context, custom_reaction: CustomReaction):
        """Shows a custom reaction's response on a given ID."""

        await ctx.send(embed=self.get_cr_embed(custom_reaction))

    @commands.has_permissions(administrator=True)
    @commands.command(name='clearcustomreactions', aliases=['crclear'])
    async def clear_custom_reactions(self, ctx: mido_utils.Context):
        """Deletes all custom reactions on this server."""

        e = mido_utils.Embed(bot=self.bot,
                             description="Are you sure you want to delete every custom reaction in this server?")
        msg = await ctx.send(embed=e)

        yes = await mido_utils.Embed.yes_no(bot=self.bot, author_id=ctx.author.id, msg=msg)
        if yes:
            await CustomReaction.delete_all(bot=ctx.bot, guild_id=ctx.guild.id)

            await ctx.edit_custom(msg, "All custom reactions have been successfully deleted.")
        else:
            await ctx.edit_custom(msg, "Request declined.")

    @commands.command(name='deletecustomreaction', aliases=['dcr'])
    async def delete_custom_reaction(self, ctx: mido_utils.Context, custom_reaction: CustomReaction):
        """Delete a custom reaction using it's ID.
        You can see the list of custom reactions using `{ctx.prefix}lcr`

        You need Administrator permission to use this command."""

        await custom_reaction.delete_from_db()

        e = self.get_cr_embed(custom_reaction)
        e.title = "Custom Reaction Deleted"

        await ctx.send(embed=e)

    @commands.command(name='customreactioncontainsanywhere', aliases=['crca'])
    async def toggle_custom_reaction_contains_anywhere(self, ctx: mido_utils.Context, custom_reaction: CustomReaction):
        """Toggles whether the custom reaction will trigger
        if the triggering message contains the keyword (instead of only starting with it)."""
        await custom_reaction.toggle_contains_anywhere()

        await ctx.send_success(
            cr_toggle_message(option_name='Contains Anywhere',
                              cr=custom_reaction,
                              option_status=custom_reaction.contains_anywhere))

    @commands.command(name='customreactiondm', aliases=['crdm'])
    async def toggle_custom_reaction_dm(self, ctx: mido_utils.Context, custom_reaction: CustomReaction):
        """Toggles whether the response message of the custom reaction will be sent as a direct message."""
        await custom_reaction.toggle_dm()

        await ctx.send_success(
            cr_toggle_message(option_name='Respond in DM',
                              cr=custom_reaction,
                              option_status=custom_reaction.send_in_DM))

    @commands.command(name='customreactionautodelete', aliases=['crad'])
    async def toggle_custom_reaction_auto_delete(self, ctx: mido_utils.Context, custom_reaction: CustomReaction):
        """Toggles whether the message triggering the custom reaction will be automatically deleted."""
        await custom_reaction.toggle_delete_trigger()

        await ctx.send_success(
            cr_toggle_message(option_name='Delete the Trigger',
                              cr=custom_reaction,
                              option_status=custom_reaction.delete_trigger))

    @delete_custom_reaction.before_invoke
    @toggle_custom_reaction_auto_delete.before_invoke
    @toggle_custom_reaction_contains_anywhere.before_invoke
    @toggle_custom_reaction_dm.before_invoke
    async def ensure_cr_ownership(self, ctx: mido_utils.Context):
        cr: CustomReaction = ctx.args[2]  # arg after the context

        if not cr.guild_id:  # if its global
            if not await ctx.bot.is_owner(ctx.author):  # if user is not the owner
                raise commands.NotOwner(f"You can not delete a global custom reaction!\n\n"
                                        f"Use `{ctx.prefix}acr \"{cr.trigger}\" -` to disable "
                                        f"this global custom reaction for your server.")
        else:
            if cr.guild_id != ctx.guild.id:  # if it belongs to a different server
                raise commands.UserInputError("This custom reaction belongs to a different server!")
            elif not ctx.author.guild_permissions.administrator:
                raise commands.MissingPermissions(['administrator'])


def setup(bot):
    bot.add_cog(CustomReactions(bot))
