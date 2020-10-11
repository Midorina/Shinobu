import asyncio
import math
from typing import Dict

import discord
from discord.ext import commands

from midobot import MidoBot
from models.db_models import MidoTime
from services.apis import SomeRandomAPI, SpotifyAPI
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import EmbedError, MusicError, NotFoundError
from services.music import Song, VoiceState, YTDLSource


class Music(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.forcekip_by_default = True
        self.voice_states: Dict[VoiceState] = {}

        self.sri_api = SomeRandomAPI(self.bot.http_session)
        self.spotify_api = SpotifyAPI(self.bot.http_session, self.bot.config['spotify_credentials'])

    def get_voice_state(self, ctx: MidoContext) -> VoiceState:
        state = self.voice_states.get(ctx.guild.id)

        if not state or not state.exists:
            state = VoiceState(self.bot)
            state.volume = ctx.guild_db.volume
            state.voice = ctx.voice_client

            self.voice_states[ctx.guild.id] = state

        return state

    async def cog_check(self, ctx: MidoContext):
        if not ctx.guild:
            raise commands.NoPrivateMessage

        return True

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    async def cog_before_invoke(self, ctx: MidoContext):
        ctx.voice_state = self.get_voice_state(ctx)

    @commands.command(name='connect')
    async def _join(self, ctx: MidoContext):
        """Make me connect to your voice channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise EmbedError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise EmbedError('Bot is already in a voice channel.')

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            return await ctx.voice_state.voice.move_to(destination)

        if not destination.permissions_for(ctx.guild.me).is_superset(discord.Permissions(1049600)):
            raise MusicError("I do not have permission to connect to that voice channel!")

        try:
            ctx.voice_state.voice = await destination.connect()
        except asyncio.TimeoutError:
            raise MusicError("I could not connect to the voice channel. Please try again later.")
        except discord.ClientException as e:
            raise MusicError(str(e))
        else:
            await ctx.message.add_reaction('👍')

    @commands.command(name='disconnect', aliases=['destroy', 'd'])
    async def _leave(self, ctx: MidoContext):
        """Make me disconnect from your voice channel."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)

            await ctx.voice_state.stop()
            del self.voice_states[ctx.guild.id]

            await ctx.send_success("I've successfully left the voice channel.")

        else:
            raise EmbedError("I'm not currently not in a voice channel! (or am I 🤔)")

    @commands.command(name='volume', aliases=['vol', 'v'])
    async def _volume(self, ctx: MidoContext, volume: int = None):
        """Change or see the volume."""
        if not ctx.voice_state.is_playing:
            raise EmbedError('Nothing is being played at the moment.')

        if volume is None:
            return await ctx.send_success(f'Current volume: **{ctx.voice_state.volume}**%')

        elif volume == 0:
            raise EmbedError(f"Just do `{ctx.prefix}pause` rather than setting volume to 0.")

        elif volume < 0 or volume > 100:
            raise EmbedError('The volume must be **between 0 and 100!**')

        ctx.voice_state.volume = volume
        await ctx.guild_db.change_volume(volume)

        await ctx.send_success(f'Volume is set to **{volume}**%')

    @commands.command(name='now', aliases=['current', 'playing', 'nowplaying', 'np'])
    async def _now(self, ctx: MidoContext):
        """See what's currently playing."""
        if ctx.voice_state.current:
            await ctx.send(embed=ctx.voice_state.current.create_embed())
        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='pause')
    async def _pause(self, ctx: MidoContext):
        """Pause the song."""
        if ctx.voice_state.voice.is_paused():
            raise EmbedError(f"It's already paused! Use `{ctx.prefix}resume` to resume.")

        elif ctx.voice_state.is_playing:
            ctx.voice_state.voice.pause()
            await ctx.send_success("⏯ Paused.")

        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='resume')
    async def _resume(self, ctx: MidoContext):
        if not ctx.voice_state.voice.is_paused():
            raise EmbedError(f"It's not paused! Use `{ctx.prefix}pause` to pause.")

        elif ctx.voice_state.is_playing:
            ctx.voice_state.voice.resume()
            await ctx.send_success('⏯ Resumed.')

        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='stop')
    async def _stop(self, ctx: MidoContext):
        """Stop playing and clear the queue."""

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            ctx.voice_state.songs.clear()
            await ctx.send_success('⏹ Stopped.')
        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='skip', aliases=['next'])
    async def _skip(self, ctx: MidoContext):
        """Skip the currently playing song."""
        if not ctx.voice_state.is_playing:
            raise EmbedError('Not playing any music right now...')

        voter = ctx.message.author
        vc = ctx.voice_state.voice.channel
        if ctx.author not in vc.members:
            raise EmbedError("You are not in the voice channel!")

        people_in_vc = len(vc.members) - 1
        if people_in_vc <= 2:
            required_votes = people_in_vc
        else:
            required_votes = math.floor(people_in_vc * 0.8)

        if (voter == ctx.voice_state.current.requester  # if its the requester
                or len(ctx.voice_state.skip_votes) >= required_votes  # if it reached the required vote amount
                or self.forcekip_by_default):  # if forceskip is enabled
            ctx.voice_state.skip()
            await ctx.send_success('⏭ Skipped.')

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.append(voter.id)

            total_votes = len(ctx.voice_state.skip_votes)
            if total_votes >= required_votes:
                ctx.voice_state.skip()
                await ctx.send_success('⏭ Skipped.')

            else:
                base_string = f'Skip vote added, currently at **{total_votes}/{required_votes}**'
                if ctx.author.guild_permissions.manage_guild is True:
                    base_string += f'\n\n**You can force this action by typing `{ctx.prefix}forceskip`**'

                return await ctx.send_success(base_string)

        else:
            raise EmbedError('You have already voted to skip this song.')

    @commands.command(name='forceskip', aliases=['fskip'])
    @commands.has_permissions(manage_guild=True)
    async def _force_skip(self, ctx: MidoContext):
        """Skip the currently playing song without requiring votes if enabled.

        You need the **Manage Server** permission to use this command."""
        if not ctx.voice_state.is_playing:
            raise EmbedError('Not playing any music right now...')

        ctx.voice_state.skip()
        await ctx.send_success('⏭ Skipped.')

    @commands.command(name='queue', aliases=['q'])
    async def _queue(self, ctx: MidoContext):
        """See the current song queue."""
        if len(ctx.voice_state.songs) == 0 and not ctx.voice_state.current:
            raise EmbedError(f'The queue is empty. Try queueing songs with `{ctx.prefix}play song_name`')

        blocks = []
        current = ctx.voice_state.current
        queue_duration = current.source.data.get('duration')

        # currently playing
        blocks.append(f"🎶 **[{current.source.title}]({current.source.url})**\n"
                      f"`{current.source.duration} | "
                      f"{current.requester}`\n")

        for i, song in enumerate(ctx.voice_state.songs, 1):
            blocks.append(f"**{i}**. **[{song.source.title}]({song.source.url})**\n"
                          f"`{song.source.duration} | "
                          f"{song.requester}`")
            queue_duration += song.source.data.get('duration')

        embed = (MidoEmbed(self.bot)
                 .set_author(icon_url=ctx.guild.icon_url, name=f"{ctx.guild.name} Music Queue - ")
                 .set_footer(text=f"{int(current.source.volume * 100)}% | "
                                  f"{len(ctx.voice_state.songs) + 1} Songs | "
                                  f"{MidoTime.parse_seconds_to_str(queue_duration, short=True, sep=':')} in Total",
                             icon_url="https://i.imgur.com/T0532pn.png")
                 )
        await embed.paginate(ctx, blocks, item_per_page=5, add_page_info_to='author')

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: MidoContext):
        """Shuffle the song queue."""
        if len(ctx.voice_state.songs) == 0:
            raise EmbedError('The queue is empty.')

        ctx.voice_state.songs.shuffle()
        await ctx.send_success('Successfully shuffled the song queue.')

    @commands.command(name='remove')
    async def _remove(self, ctx: MidoContext, index: int):
        """Remove a song from the song queue."""
        if len(ctx.voice_state.songs) == 0:
            raise EmbedError('The queue is empty.')

        if not 0 < index <= len(ctx.voice_state.songs):
            raise EmbedError("Please specify a proper index!")

        if ctx.author.id != ctx.voice_state.songs[index - 1].requester.id:
            raise EmbedError("You are not the requester of this song!")

        ctx.voice_state.songs.remove(index - 1)
        await ctx.send_success('✅ Removed the song.')

    # This command has been disabled due to issues its causing.
    # @commands.command(name='loop')
    # async def _loop(self, ctx: context.Context):
    #     if not ctx.voice_state.is_playing:
    #         return await ctx.send('Nothing being played at the moment.')
    #
    #     # Inverse boolean value to loop and unloop.
    #     ctx.voice_state.loop = not ctx.voice_state.loop
    #     await ctx.message.add_reaction('✅')

    @commands.command(name='play', aliases=['p'])
    async def _play(self, ctx: MidoContext, *, query: str):
        """Queue a song to play!"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise EmbedError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise EmbedError('Bot is already in a voice channel.')

        if not ctx.voice_client:
            self.bot.loop.create_task(ctx.invoke(self._join))

        msg_task = self.bot.loop.create_task(ctx.send_success("Processing..."))

        # checks
        async with ctx.typing():
            # get song names
            if query.startswith('https://open.spotify.com/'):
                search: list = await self.spotify_api.get_song_names(query)
            else:
                search: list = await YTDLSource.create_source(ctx, query, process=False, loop=self.bot.loop)

            songs = []
            for _query in search:
                source = await YTDLSource.create_source(ctx, _query, process=True, loop=self.bot.loop)
                if source:
                    s_obj = Song(source[0])
                    songs.append(s_obj)
                    await ctx.voice_state.songs.put(s_obj)

            msg = msg_task.result()
            # if its the first song in the queue, just delete the msg
            if len(ctx.voice_state.songs) == 1 and not ctx.voice_state.is_playing:
                return await msg.delete()

            # if its a playlist
            if len(songs) > 1:
                await ctx.edit_custom(msg, f'**{len(songs)}** songs have been successfully added to the queue!\n\n'
                                           f'You can type `{ctx.prefix}queue` to see it.')
            # single query
            elif len(songs) == 1:
                await ctx.edit_custom(msg, f'**{songs[0].source.title}** has been successfully added to the queue.\n\n'
                                           f'You can type `{ctx.prefix}queue` to see it.')
            else:
                await ctx.edit_custom(msg, f"Couldn't find anything that matches `{query}`.")

    @commands.command()
    async def lyrics(self, ctx: MidoContext, *, song_name: str = None):
        """See the lyrics of the current song or a specific song."""
        if not song_name and not ctx.voice_state.current:
            raise EmbedError("You need to play a song then use this command or specify a song name!")
        elif not song_name:
            song_name = ctx.voice_state.current.source.title

        try:
            song_title, lyrics_pages, thumbnail = await self.sri_api.get_lyrics(song_name)
        except NotFoundError:
            raise EmbedError(f"I couldn't find the lyrics of **{song_name}**.\n"
                             f"Try writing the title in a simpler form.")

        e = MidoEmbed(bot=self.bot, title=song_title, default_footer=True)
        e.set_thumbnail(url=thumbnail)

        await e.paginate(
            ctx=ctx,
            item_per_page=1,
            blocks=lyrics_pages,
            extra_sep='\n')


def setup(bot):
    bot.add_cog(Music(bot))
