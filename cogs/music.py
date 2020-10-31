import asyncio
import math

import discord
from discord.ext import commands
from wavelink import Node, TrackPlaylist, WavelinkMixin, events

from midobot import MidoBot
from models.db_models import MidoTime
from services.apis import SpotifyAPI
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import EmbedError, MusicError, NotFoundError
from services.music import VoicePlayer
from services.resources import Resources


class Music(commands.Cog, WavelinkMixin):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.forcekip_by_default = True

        self.spotify_api = SpotifyAPI(self.bot.http_session, self.bot.config['spotify_credentials'])

        self.wavelink = self.bot.wavelink

        self.bot.loop.create_task(self.start_nodes())

    async def start_nodes(self):
        await self.bot.wait_until_ready()

        # initiate the each node specified in the cfg file
        for node in self.bot.config['lavalink_nodes']:
            if node['identifier'] not in self.wavelink.nodes:
                await self.wavelink.initiate_node(**node)

    async def cog_check(self, ctx: MidoContext):
        if not ctx.guild:
            raise commands.NoPrivateMessage
        else:
            return True

    async def cog_before_invoke(self, ctx: MidoContext):
        ctx.voice_player = self.wavelink.get_player(ctx.guild.id, cls=VoicePlayer)

    @WavelinkMixin.listener(event="on_track_end")
    async def track_end_event(self, node: Node, payload: events.TrackEnd):
        await payload.player.play_next()

    @commands.command(name='connect')
    async def _join(self, ctx: MidoContext):
        """Make me connect to your voice channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise EmbedError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise EmbedError('Bot is already connected to a different voice channel.')
            if ctx.voice_client.channel.id == ctx.voice_player.channel_id:
                raise EmbedError("I'm already connected to your voice channel.")

        destination = ctx.author.voice.channel

        if not destination.permissions_for(ctx.guild.me).is_superset(discord.Permissions(1049600)):
            raise MusicError("I do not have permission to connect to that voice channel!")

        try:
            await ctx.voice_player.connect(destination.id)
        except asyncio.TimeoutError:
            raise MusicError("I could not connect to the voice channel. Please try again later.")
        except discord.ClientException as e:
            raise MusicError(str(e))
        else:
            await ctx.message.add_reaction('👍')

    @commands.command(name='disconnect', aliases=['destroy', 'd'])
    async def _leave(self, ctx: MidoContext):
        """Make me disconnect from your voice channel."""
        if ctx.voice_player.channel_id:
            await ctx.voice_player.destroy()

            await ctx.send_success("I've successfully left the voice channel.")

        else:
            raise EmbedError("I'm not currently not in a voice channel!")

    @commands.command(name='volume', aliases=['vol', 'v'])
    async def _volume(self, ctx: MidoContext, volume: int = None):
        """Change or see the volume."""
        if not ctx.voice_player.is_playing:
            raise EmbedError('Nothing is being played at the moment.')

        if volume is None:
            return await ctx.send_success(f'Current volume: **{ctx.voice_player.volume}**%')

        elif volume == 0:
            raise EmbedError(f"Just do `{ctx.prefix}pause` rather than setting volume to 0.")

        elif volume < 0 or volume > 100:
            raise EmbedError('The volume must be **between 0 and 100!**')

        # set
        await ctx.voice_player.set_volume(volume)
        await ctx.guild_db.change_volume(volume)

        await ctx.send_success(f'Volume is set to **{volume}**%')

    @commands.command(name='now', aliases=['current', 'playing', 'nowplaying', 'np'])
    async def _now_playing(self, ctx: MidoContext):
        """See what's currently playing."""
        if ctx.voice_player.is_playing:
            await ctx.send(embed=ctx.voice_player.current.create_embed())
        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='pause')
    async def _pause(self, ctx: MidoContext):
        """Pause the song."""
        if ctx.voice_player.is_paused:
            raise EmbedError(f"It's already paused! Use `{ctx.prefix}resume` to resume.")

        elif ctx.voice_player.is_playing:
            await ctx.voice_player.set_pause(pause=True)
            await ctx.message.add_reaction("⏯")

        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='resume')
    async def _resume(self, ctx: MidoContext):
        """Resume the player."""
        if not ctx.voice_player.is_paused:
            raise EmbedError(f"It's not paused! Use `{ctx.prefix}pause` to pause.")

        elif ctx.voice_player.is_playing:
            await ctx.voice_player.set_pause(pause=False)
            await ctx.message.add_reaction("⏯")

        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='stop')
    async def _stop(self, ctx: MidoContext):
        """Stop playing and clear the queue."""

        if ctx.voice_player.is_playing:
            await ctx.voice_player.stop()
            await ctx.send_success('⏹ Stopped.')
        else:
            raise EmbedError("I'm not currently playing any music!")

    @commands.command(name='skip', aliases=['next'])
    async def _skip(self, ctx: MidoContext):
        """Skip the currently playing song."""
        if not ctx.voice_player.is_playing:
            raise EmbedError('Not playing any music right now...')

        voter = ctx.message.author
        vc = ctx.guild.get_channel(ctx.voice_player.channel_id)
        if ctx.author not in vc.members:
            raise EmbedError("You are not in the voice channel!")

        people_in_vc = len(vc.members) - 1
        if people_in_vc <= 2:
            required_votes = people_in_vc
        else:
            required_votes = math.floor(people_in_vc * 0.8)

        if (voter == ctx.voice_player.current.requester  # if its the requester
                or len(ctx.voice_player.skip_votes) >= required_votes  # if it reached the required vote amount
                or self.forcekip_by_default):  # if force-skip is enabled
            await ctx.voice_player.skip()

        elif voter.id not in ctx.voice_player.skip_votes:
            ctx.voice_player.skip_votes.append(voter.id)

            total_votes = len(ctx.voice_player.skip_votes)
            if total_votes >= required_votes:
                await ctx.voice_player.skip()

            else:
                base_string = f'Skip vote added, currently at **{total_votes}/{required_votes}**'
                if ctx.author.guild_permissions.manage_guild is True:
                    base_string += f'\n\n**You can force this action by typing `{ctx.prefix}forceskip`**'

                return await ctx.send_success(base_string)

        else:
            raise EmbedError('You have already voted to skip this song.')

        await ctx.message.add_reaction('⏭')

    @commands.command(name='forceskip', aliases=['fskip'])
    @commands.has_permissions(manage_guild=True)
    async def _force_skip(self, ctx: MidoContext):
        """Skip the currently playing song without requiring votes if enabled.

        You need the **Manage Server** permission to use this command."""
        if not ctx.voice_player.is_playing:
            raise EmbedError('Not playing any music right now...')

        await ctx.voice_player.play_next()
        await ctx.message.add_reaction('⏭')

    @commands.command(name='queue', aliases=['q'])
    async def _queue(self, ctx: MidoContext):
        """See the current song queue."""
        if len(ctx.voice_player.song_queue) == 0 and not ctx.voice_player.current:
            raise EmbedError(f'The queue is empty. Try queueing songs with `{ctx.prefix}play`')

        blocks = []
        current = ctx.voice_player.current
        queue_duration = current.duration_in_seconds

        # currently playing
        blocks.append(f"🎶 **[{current.title}]({current.uri})**\n"
                      f"`{current.duration_str} | "
                      f"{current.requester}`\n")

        for i, song in enumerate(ctx.voice_player.song_queue, 1):
            blocks.append(f"**{i}**. **[{song.title}]({song.uri})**\n"
                          f"`{song.duration_str} | "
                          f"{song.requester}`")
            queue_duration += song.duration_in_seconds

        queue_duration = MidoTime.parse_seconds_to_str(queue_duration, short=True, sep=':')

        embed = (MidoEmbed(self.bot)
                 .set_author(icon_url=ctx.guild.icon_url, name=f"{ctx.guild.name} Music Queue - ")
                 .set_footer(text=f"{ctx.voice_player.volume}% | "
                                  f"{len(ctx.voice_player.song_queue) + 1} Songs | "
                                  f"{queue_duration} in Total",
                             icon_url=Resources.images.volume)
                 )
        await embed.paginate(ctx, blocks, item_per_page=5, add_page_info_to='author')

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: MidoContext):
        """Shuffle the song queue."""
        if len(ctx.voice_player.song_queue) == 0:
            raise EmbedError('The queue is empty.')

        ctx.voice_player.song_queue.shuffle()
        await ctx.send_success('Successfully shuffled the song queue.')

    @commands.command(name='remove')
    async def _remove(self, ctx: MidoContext, index: int):
        """Remove a song from the song queue."""
        if len(ctx.voice_player.song_queue) == 0:
            raise EmbedError('The queue is empty.')

        if not 0 < index <= len(ctx.voice_player.song_queue):
            raise EmbedError("Please specify a proper index!")

        if ctx.author.id != ctx.voice_player.song_queue[index - 1].requester.id:
            raise EmbedError("You are not the requester of this song!")

        ctx.voice_player.song_queue.remove(index - 1)
        await ctx.send_success('✅ Removed the song.')

    @commands.command(name='loop')
    async def _loop(self, ctx: MidoContext):
        """Enable the loop feature to play the same song over and over."""
        if not ctx.voice_player.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        # Inverse boolean value to loop and unloop.
        ctx.voice_player.loop = not ctx.voice_player.loop

        if ctx.voice_player.loop:
            await ctx.send_success("I will play the same song from now on.")
        else:
            await ctx.send_success("The loop feature has been disabled.")

    @commands.command(name='play', aliases=['p'])
    async def _play(self, ctx: MidoContext, *, query: str):
        """Queue a song to play!"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise EmbedError('You are not connected to any voice channel.')

        if ctx.voice_player.channel_id:
            if ctx.voice_player.channel_id != ctx.author.voice.channel.id:
                raise EmbedError('Bot is already in a voice channel.')
        else:
            self.bot.loop.create_task(ctx.invoke(self._join))

        async with ctx.typing():
            if query.startswith('https://open.spotify.com/'):  # spotify link
                song_names = [f'ytsearch:{x}' for x in await self.spotify_api.get_song_names(query)]

            elif not query.startswith('https://'):  # single query
                song_names = [f'ytsearch:{query}']
            else:  # yt link
                song_names = [query]

            added_songs = []
            for song_name in song_names:
                song = await self.wavelink.get_tracks(song_name)
                if not song and len(song_names) == 0:
                    raise EmbedError(f"Couldn't find anything that matches `{query}`.")

                if isinstance(song, TrackPlaylist):
                    song_to_add = song.tracks
                    added_songs.extend(song_to_add)
                else:
                    song_to_add = song[0]
                    added_songs.append(song_to_add)

                await ctx.voice_player.add_songs(song_to_add, ctx, try_playing_after=True)

            if len(added_songs) > 1:  # if its a playlist
                await ctx.send_success(
                    f'**{len(added_songs)}** songs have been successfully added to the queue!\n\n'
                    f'You can type `{ctx.prefix}queue` to see it.')

            else:
                if len(ctx.voice_player.song_queue) != 0:  # if its not the first song
                    await ctx.send_success(
                        f'**{added_songs[0].title}** has been successfully added to the queue.\n\n'
                        f'You can type `{ctx.prefix}queue` to see it.')

    @commands.command()
    async def lyrics(self, ctx: MidoContext, *, song_name: str = None):
        """See the lyrics of the current song or a specific song."""
        if not song_name and not ctx.voice_player.current:
            raise EmbedError("You need to play a song then use this command or specify a song name!")
        elif not song_name:
            song_name = ctx.voice_player.current.source.title

        api = self.bot.get_cog('Searches')

        try:
            song_title, lyrics_pages, thumbnail = await api.get_lyrics(song_name)
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
