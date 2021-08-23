import asyncio
import math
from copy import deepcopy
from datetime import datetime
from typing import List, Optional

import discord

from .exceptions import MessageTooLong


class Embed(discord.Embed):
    def __init__(self, bot, default_footer=False, image_url=None, **kwargs):
        super().__init__(**kwargs)
        self.bot = bot

        self.color = self.color or self.bot.color

        # if default_footer is True and not hasattr(self, '_footer'):
        if default_footer is True:
            self.set_footer(text=self.bot.user.name, icon_url=self.bot.user.avatar_url)

            self.timestamp = self.timestamp or datetime.utcnow()

        if image_url:
            self.set_image(url=image_url)

    @staticmethod
    def filter_blocks(blocks: List[str]) -> List[str]:
        filtered_blocks = list()

        for block in blocks:
            if len(block) > 2040:
                filtered_blocks.append(block[:2040] + '...')
            else:
                filtered_blocks.append(block)

        return filtered_blocks

    async def paginate(self,
                       ctx,
                       blocks: List[str],
                       item_per_page: int = 6,
                       add_page_info_to: str = 'footer',
                       reactions: bool = True,
                       extra_sep: str = ''):
        arrows = [
            "⏪",
            "◀",
            "▶",
            "⏩"
        ]

        remove_reaction_mode = ctx.guild is not None

        def reaction_check(_reaction, _user):
            if _user == ctx.author:
                if _reaction.message.id == message.id:
                    if str(_reaction.emoji) in arrows:
                        return True

        def message_check(m):
            if m.author == ctx.author:
                if m.channel == ctx.channel:
                    try:
                        return int(m.content)
                    except ValueError:
                        pass

        async def clear_message_reactions(_message: discord.Message):
            try:
                await _message.clear_reactions()
            except discord.Forbidden:
                _m = await ctx.fetch_message(_message.id)
                if not _m:
                    return
                for _reaction in _m.reactions:
                    if _reaction.me:
                        await _reaction.remove(user=ctx.bot.user)

        async def update_message(msg=None, _item_per_page: int = item_per_page):
            if _item_per_page == 0:
                # we might hit 0 while trying to avoid the character length limit
                # in that case, raise MessageTooLong
                raise MessageTooLong(filtered_blocks[0])

            msg_for_embed = ""
            # get a copy of the embed
            _e = discord.Embed.from_dict(deepcopy(self.to_dict()))

            for i in range(page * _item_per_page - _item_per_page, page * _item_per_page):
                try:
                    msg_for_embed += f"{filtered_blocks[i]}\n" + extra_sep
                except IndexError:
                    break

            if add_page_info_to == 'footer':
                try:
                    _e._footer['text'] += f" | Page {page}/{total_pages}"
                except AttributeError:
                    _e.set_footer(text=f"Page {page}/{total_pages}")

            elif add_page_info_to == 'title':
                _e.title += f" | Page {page}/{total_pages}"

            elif add_page_info_to == 'author':
                try:
                    _e._author['name'] += f" |  Page {page}/{total_pages}"
                except AttributeError:
                    _e.set_author(name=f"Page {page}/{total_pages}")

            _e.description = msg_for_embed

            try:
                if not msg:
                    return await ctx.send(embed=_e)
                else:
                    await msg.edit(embed=_e)
            except discord.HTTPException:
                # we've probably hit 2048 character limit.
                # in this case, decrease _item_per_page and try again
                await update_message(msg, _item_per_page - 1)

        filtered_blocks = self.filter_blocks(blocks)

        page = 1
        total_pages = math.ceil(len(filtered_blocks) / item_per_page)

        message = await update_message()

        if len(filtered_blocks) <= item_per_page:
            return

        if reactions:
            for arrow in arrows:
                await message.add_reaction(arrow)

        while True:
            if remove_reaction_mode is True:
                done, pending = await asyncio.wait([
                    self.bot.wait_for('reaction_add', timeout=60, check=reaction_check),
                    self.bot.wait_for('message', timeout=60, check=message_check)], return_when=asyncio.FIRST_COMPLETED)
            else:
                done, pending = await asyncio.wait([
                    self.bot.wait_for('reaction_add', timeout=60, check=reaction_check),
                    self.bot.wait_for('reaction_remove', timeout=60, check=reaction_check),
                    self.bot.wait_for('message', timeout=60, check=message_check)], return_when=asyncio.FIRST_COMPLETED)
            try:
                for thing in done:
                    thing.exception()  # this is to retrieve exceptions

                stuff = done.pop().result()

            except asyncio.TimeoutError:
                return await clear_message_reactions(message)

            else:
                if isinstance(stuff, tuple):
                    if not reactions:
                        continue

                    arrow, user = stuff

                    if str(arrow.emoji) == arrows[0]:
                        if page != 1:
                            page = 1
                            await update_message(message)

                    elif str(arrow.emoji) == arrows[1]:
                        if page > 1:
                            page -= 1
                            await update_message(message)

                    elif str(arrow.emoji) == arrows[2]:
                        if page < total_pages:
                            page += 1
                            await update_message(message)

                    elif str(arrow.emoji) == arrows[3]:
                        if page != total_pages:
                            page = total_pages
                            await update_message(message)

                    if remove_reaction_mode is True:
                        try:
                            await arrow.remove(user)
                        except discord.Forbidden:
                            pass

                else:
                    if 0 < int(stuff.content) <= total_pages:
                        page = int(stuff.content)
                        await update_message(message)

                    try:
                        await stuff.delete()
                    except discord.Forbidden:
                        pass

            for future in pending:
                future.cancel()

    @staticmethod
    async def yes_no(bot, author_id: int, msg: discord.Message):
        emotes = ('🇾', '🇳')

        def reaction_check(_reaction, _user):
            if _user.id == author_id:
                if _reaction.message.id == msg.id:
                    if str(_reaction.emoji) in emotes:
                        return True

        for emote in emotes:
            await msg.add_reaction(emote)

        try:
            reaction, user = await bot.wait_for('reaction_add', check=reaction_check, timeout=30.0)

            await msg.clear_reactions()
        except asyncio.TimeoutError:
            return None

        else:
            return str(reaction.emoji) == emotes[0]

    @staticmethod
    async def get_msg(bot,
                      ctx,
                      author_id: int = None,
                      message_to_send: str = None,
                      must_be_int=False,
                      must_be_letter=False,
                      delete_response_after=False,
                      timeout: float = 120) -> Optional[discord.Message]:
        def message_check(m: discord.Message):
            if not author_id or m.author.id == author_id:
                if m.channel == ctx.channel:
                    content = m.content
                    if must_be_int is True:
                        if content.isdigit():
                            return True
                    elif must_be_letter is True:
                        if len(content) == 1:
                            return True
                    else:
                        return True

        if message_to_send:
            await ctx.send(message_to_send)

        try:
            message = await bot.wait_for('message', check=message_check, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        else:
            if delete_response_after:
                await message.delete()

            return message

    @staticmethod
    async def wait_for_reaction(bot: discord.AutoShardedClient,
                                message: discord.Message,
                                emotes_to_wait: List[str],
                                author_id: int = None,
                                clear_reactions_after: bool = True,
                                wait_for: float = 60.0) -> discord.Reaction:
        def reaction_check(_reaction, _user):
            if (not author_id and not _user.bot) or _user.id == author_id:
                if _reaction.message.id == message.id:
                    if str(_reaction.emoji) in emotes_to_wait:
                        return True

        ret = None

        try:
            ret, user = await bot.wait_for('reaction_add', check=reaction_check, timeout=wait_for)
        except asyncio.TimeoutError:
            pass

        if clear_reactions_after:
            try:
                await message.clear_reactions()
            except (discord.NotFound, discord.Forbidden):
                pass

        return ret
