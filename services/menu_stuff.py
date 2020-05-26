import asyncio
import math
from copy import deepcopy
from typing import List

import discord


def filter_blocks(blocks: List[str], extra_sep='') -> List[str]:
    filtered_blocks = list()

    for block in blocks:
        # if a block is larger than 2048 characters, split it
        # if len(block) > 2048:
        #     splitted = block.split()
        #     half = int(len(splitted) / 2)
        #
        #     filtered_blocks.append(" ".join(splitted[:half]))
        #     filtered_blocks.append(" ".join(splitted[half:]))
        # else:
        #     filtered_blocks.append(block)
        if len(block) > 2040:
            filtered_blocks.append(block[:2040] + '...')
        else:
            filtered_blocks.append(block)

    # if is_urban:
    #     for i in range(len(filtered_blocks)):
    #         last_occ_of_bold_start = filtered_blocks[i].rfind('[')
    #         last_occ_of_bold_end = filtered_blocks[i].rfind(']')
    #
    #         if last_occ_of_bold_start > last_occ_of_bold_end:
    #             filtered_blocks[i] += "]"
    #             filtered_blocks[i + 1] = "[" + filtered_blocks[i + 1]
    #
    #         filtered_blocks[i] = filtered_blocks[i].replace('[', '**').replace(']', '**')

    if extra_sep:
        filtered_blocks = [x + extra_sep for x in filtered_blocks]

    return filtered_blocks


async def paginate(bot,
                   ctx,
                   embed: discord.Embed,
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

    async def update_message(msg=None):
        msg_for_embed = ""
        # get a copy of the embed
        _e = discord.Embed.from_dict(deepcopy(embed.to_dict()))

        for i in range(page * item_per_page - item_per_page, page * item_per_page):
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
                _e._author['name'] += f" | Page {page}/{total_pages}"
            except AttributeError:
                _e.set_author(name=f"Page {page}/{total_pages}")

        _e.description = msg_for_embed

        if not msg:
            return await ctx.send(embed=_e)
        else:
            await msg.edit(embed=_e)

    filtered_blocks = filter_blocks(blocks, extra_sep=extra_sep)

    page = 1
    total_pages = math.ceil(len(filtered_blocks) / item_per_page)

    message = await update_message()

    if len(filtered_blocks) <= item_per_page:
        return

    if reactions:
        for arrow in arrows:
            await message.add_reaction(arrow)

    while True:
        done, pending = await asyncio.wait([
            bot.wait_for('reaction_add', timeout=60, check=reaction_check),
            bot.wait_for('message', timeout=60, check=message_check)], return_when=asyncio.FIRST_COMPLETED)
        try:
            for thing in done:
                thing.exception()  # this is to retrieve exceptions

            stuff = done.pop().result()

        except asyncio.TimeoutError:
            await message.clear_reactions()
            return

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

                await arrow.remove(user)

            else:
                if 0 < int(stuff.content) <= total_pages:
                    page = int(stuff.content)
                    await update_message(message)

                await stuff.delete()

        for future in pending:
            future.cancel()


async def yes_no(bot, author_id, msg):
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

    except asyncio.TimeoutError:
        await msg.clear_reactions()
        return None

    else:
        await msg.clear_reactions()
        if str(reaction.emoji) == emotes[0]:
            return True

        elif str(reaction.emoji) == emotes[1]:
            return False
