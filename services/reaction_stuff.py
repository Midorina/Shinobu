import asyncio
import math


async def paginate(bot, ctx, embed, text, field_title=None, footer_text=None):
    arrows = [
        "◀",
        "<:left_button:593065354670899210>",
        "<:right_button:593065366146514944>",
        "▶"
    ]

    text_list = text.split('\n')
    text_list = list(filter(None, text_list))

    def reaction_check(_reaction, _user):
        if _user.id == ctx.author.id:
            if _reaction.message.id == message.id:
                if str(_reaction.emoji) in arrows:
                    return True

    def message_check(m):
        if m.author == ctx.author:
            if m.channel == ctx.channel:
                try:
                    int(m.content)
                    return True
                except ValueError:
                    pass

    async def update_message(msg=None):
        msg_for_embed = ""

        for i in range(page * 10 - 10, page * 10):
            try:
                msg_for_embed += f"{text_list[i]}\n"

            except IndexError:
                break
        if footer_text:
            embed.set_footer(text=footer_text.format(page, total_pages))
        else:
            embed.set_footer(
                text=f"Floor {page} / {total_pages} | In the elevator, type what floor you'd like to visit.")

        embed.clear_fields()
        if field_title:
            embed.add_field(name=field_title, value=msg_for_embed)
        else:
            embed.add_field(name="⠀", value=msg_for_embed)

        if not msg:
            return await ctx.send(embed=embed)
        else:
            await msg.edit(embed=embed)

    page = 1
    total_pages = math.ceil(len(text_list) / 10)

    message = await update_message()

    for arrow in arrows:
        await message.add_reaction(arrow)

    while True:
        done, pending = await asyncio.wait([
            bot.wait_for('reaction_add', timeout=60, check=reaction_check),
            bot.wait_for('message', timeout=60, check=message_check)], return_when=asyncio.FIRST_COMPLETED)

        try:
            stuff = done.pop().result()

        except asyncio.TimeoutError:
            await message.clear_reactions()
            return

        else:
            if isinstance(stuff, tuple):
                reaction = stuff[0]

                if str(reaction.emoji) == "◀":
                    if page != 1:
                        page = 1
                        await update_message(message)

                elif str(reaction.emoji) == "<:left_button:593065354670899210>":
                    if page > 1:
                        page -= 1
                        await update_message(message)

                elif str(reaction.emoji) == "<:right_button:593065366146514944>":
                    if page < total_pages:
                        page += 1
                        await update_message(message)

                if str(reaction.emoji) == "▶":
                    if page != total_pages:
                        page = total_pages
                        await update_message(message)

            else:
                if int(stuff.content) <= total_pages:
                    page = int(stuff.content)
                    await update_message(message)

        for future in pending:
            future.cancel()


async def yes_no(bot, author_id, msg):
    def reaction_check(_reaction, _user):
        if _user.id == author_id:
            if _reaction.message.id == msg.id:
                if str(_reaction.emoji) == '🇾' or str(_reaction.emoji) == '🇳':
                    return True

    await msg.add_reaction('🇾')
    await msg.add_reaction('🇳')

    try:
        reaction, user = await bot.wait_for('reaction_add', check=reaction_check, timeout=30.0)

    except asyncio.TimeoutError:
        return None

    else:
        if str(reaction.emoji) == '🇾':
            return True

        else:
            return False
