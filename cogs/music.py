from __future__ import annotations

import asyncio
import math
from typing import List
from typing import TYPE_CHECKING

import discord
import wavelink
from discord.ext import commands
from wavelink import Node

import mido_utils
from cogs.searches import Searches
from shinobu import ShinobuBot

if TYPE_CHECKING:
    from mido_utils import VoicePlayer


class Music(commands.Cog, description='Play music using `{ctx.prefix}play`. **Spotify is supported.**'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.forcekip_by_default = True

        self.spotify_api: mido_utils.SpotifyAPI | None = None

        if self.bot.config.spotify_credentials:
            self.spotify_api = mido_utils.SpotifyAPI(self.bot.http_session, self.bot.config.spotify_credentials)

        if self.bot.config.lavalink_nodes_credentials:
            self.bot.loop.create_task(self.start_nodes())
        else:
            self.bot.logger.warning("Music configuration is not done properly. "
                                    "Please install Lavalink and enter node credentials to the config file.")

    async def start_nodes(self):
        await self.bot.wait_until_ready()

        nodes: List[Node] = []
        # initiate each node specified in the cfg file
        for node_credentials in self.bot.config.lavalink_nodes_credentials:
            nodes.append(Node(**node_credentials))

        await wavelink.Pool.connect(nodes=nodes, client=self.bot)

    async def reload_nodes(self):
        # destroy existing nodes
        for node in wavelink.Pool().nodes.values():
            await node.disconnect(force=True)

        # initiate the new ones
        await self.start_nodes()

    async def cog_check(self, ctx: mido_utils.Context):
        # todo: add_reactions perm check
        if not ctx.guild:
            raise commands.NoPrivateMessage

        if ctx.command.name == "youtube":
            return True

        return await mido_utils.is_patron(
            bot=self.bot, user_id=ctx.author.id, required_level=2, allow_owner=True,
            raise_exceptions=True)

    async def cog_command_error(self, ctx: mido_utils.Context, error):
        error = getattr(error, 'original', error)

        if mido_utils.better_is_instance(error, wavelink.InvalidNodeException):
            await self.reload_nodes()
            await asyncio.sleep(1)
            await ctx.reinvoke()

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        # get our own player from the guild
        player: VoicePlayer = payload.player.guild.voice_client

        await player.last_song.text_channel.send(f"There has been an error while playing `{payload.track}`:\n"
                                                 f"```{payload.exception}```")

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        if payload.player:  # if we have a player, set next
            # get our own player from the guild
            player: VoicePlayer = payload.player.guild.voice_client
            player.next.set()

    @commands.command(name='connect')  # not hybrid because of slash command limit
    async def _connect(self, ctx: mido_utils.Context):
        """Connects bot to the voice channel."""
        await self.ensure_can_control(ctx)  # this is cuz ctx.invoke doesn't call pre-invoke hooks

        channel = ctx.author.voice.channel

        if ctx.voice_client and ctx.voice_client.channel.id == channel.id:
            raise mido_utils.MusicError("I'm already connected to your voice channel.")

        # Connect and Speak permissions
        required_perms = discord.Permissions(3145728)
        channel_perms = channel.permissions_for(ctx.guild.me)

        if not channel_perms.is_superset(required_perms):
            raise mido_utils.MusicError(f"I need both **Connect** and **Speak** permissions "
                                        f"in **{channel}** to be able to play music.")
            # raise commands.BotMissingPermissions(['connect', 'speak'])

        try:
            vc: mido_utils.VoicePlayer = await channel.connect(cls=mido_utils.VoicePlayer)
        except asyncio.TimeoutError:
            raise discord.HTTPException
        else:
            await vc.set_volume(ctx.guild_db.volume)

            try:
                await ctx.message.add_reaction('👍')
            except discord.NotFound:
                await ctx.send_success("Successfully connected to your voice channel.")

    @commands.hybrid_command(name='disconnect', aliases=['destroy', 'd', 'dc', 'stop'])
    async def _disconnect(self, ctx: mido_utils.Context):
        """Make me disconnect from your voice channel."""
        if not ctx.voice_client:
            raise mido_utils.MusicError("I'm not currently not in a voice channel!")

        await ctx.voice_client.disconnect(force=True)

        await ctx.send_success("I've successfully left the voice channel.")

    @commands.hybrid_command(name='volume', aliases=['vol', 'v'])
    async def _volume(self, ctx: mido_utils.Context, volume: mido_utils.Int16 = None):
        """Change or see the volume."""
        volume: int | None

        if volume is None:
            return await ctx.send_success(f'Current volume: **{ctx.voice_client.volume}**%')

        elif volume == 0 or volume < 0:
            raise mido_utils.MusicError(f"Just do `{ctx.prefix}pause` rather than setting volume to 0 or below.")

        elif volume > 100 and not await mido_utils.is_patron(bot=ctx.bot, user_id=ctx.author.id, required_level=2,
                                                             raise_exceptions=False):
            raise mido_utils.MusicError('Volume can not be more than 100.\n\n'
                                        f'*You can unlock this limit '
                                        f'by [supporting the project.]({mido_utils.links.patreon})*')
        # set
        await ctx.voice_client.set_volume(volume)
        await ctx.guild_db.change_volume(volume)

        await ctx.send_success(f'Volume is set to **{volume}**%')

    @commands.hybrid_command(name='nowplaying', aliases=['current', 'playing', 'now', 'np'])
    async def _now_playing(self, ctx: mido_utils.Context):
        """See what's currently playing."""
        await ctx.send(embed=ctx.voice_client.get_current_or_last_song().create_np_embed())

    @commands.hybrid_command(name='pause')
    async def _pause_or_resume(self, ctx: mido_utils.Context):
        """Pause or resume the song."""
        await ctx.voice_client.pause(not ctx.voice_client.paused)

        try:
            await ctx.message.add_reaction("⏯")
        except discord.NotFound:
            await ctx.send_success("Paused." if ctx.voice_client.paused else "Resuming...")

    @commands.hybrid_command(name='seek')
    async def _seek(self, ctx: mido_utils.Context, seconds: mido_utils.Int32):
        """Seek forwards by x seconds. Enter a negative number to seek backwards.

        Use `{ctx.prefix}skipto` to go to a certain time."""
        seconds: int

        if seconds == 0:
            raise commands.BadArgument("Please input a different value than 0.")

        song = ctx.voice_client.get_current_or_last_song()

        # calculate new position and change it
        new_position = ctx.voice_client.position / 1000 + seconds
        if new_position > song.duration:
            new_position = song.duration
        elif new_position < 0:
            new_position = 0

        await ctx.voice_client.seek(int(new_position * 1000))

        # prepare the embed
        e = mido_utils.Embed(ctx.bot)
        if seconds > 0:
            e.description = f"Seeked **{seconds}** seconds forwards 👌"
        else:
            e.description = f"Seeked **{0 - seconds}** seconds backwards 👌"

        new_position_str = mido_utils.Time.parse_seconds_to_str(new_position, short=True, sep=':')
        e.set_footer(text=f"New player position: {new_position_str}/{song.duration_str}")

        await ctx.send(embed=e)

    @commands.command(name='skipto', aliases=['goto'])  # not hybrid because of slash command limit
    async def _goto(self, ctx: mido_utils.Context, seconds: mido_utils.Int32):
        """Go to a certain time in the song.

        Use `{ctx.prefix}seek` to seek forwards or backwards from the current position."""
        seconds: int

        if seconds < 0:
            seconds = 0

        await ctx.voice_client.seek(seconds * 1000)

        # prepare the embed
        song = ctx.voice_client.get_current_or_last_song()
        new_position_str = mido_utils.Time.parse_seconds_to_str(seconds, short=True, sep=':')

        e = mido_utils.Embed(ctx.bot)
        e.description = 'Adjusted the song position 👌'
        e.set_footer(text=f"New player position: {new_position_str}/{song.duration_str}")

        await ctx.send(embed=e)

    @commands.hybrid_command(name='skip', aliases=['next'])
    async def _skip(self, ctx: mido_utils.Context):
        """Skip the currently playing song."""
        voter = ctx.message.author
        vc = ctx.voice_client.channel

        if not vc:
            raise mido_utils.MusicError("I can not see the voice channel I'm playing songs in.")

        people_in_vc = len(vc.members) - 1
        if people_in_vc <= 2:
            required_votes = people_in_vc
        else:
            required_votes = math.floor(people_in_vc * 0.8)

        if (voter == ctx.voice_client.get_current_or_last_song().requester  # if it's the requester
                or len(ctx.voice_client.skip_votes) >= required_votes  # if it reached the required vote amount
                or self.forcekip_by_default):  # if force-skip is enabled
            await ctx.voice_client.skip()

        elif voter.id not in ctx.voice_client.skip_votes:
            ctx.voice_client.skip_votes.append(voter.id)

            total_votes = len(ctx.voice_client.skip_votes)
            if total_votes >= required_votes:
                await ctx.voice_client.skip()

            else:
                base_string = f'Skip vote added, currently at **{total_votes}/{required_votes}**'
                if ctx.author.guild_permissions.manage_guild is True:
                    base_string += f'\n\n**You can force this action by typing `{ctx.prefix}forceskip`**'

                return await ctx.send_success(base_string)

        else:
            raise mido_utils.MusicError('You have already voted to skip this song.')

        try:
            await ctx.message.add_reaction('⏭')
        except discord.NotFound:
            await ctx.send_success("Successfully skipped the current song.")

    # TODO: add a way to toggle vote requirement and enable this
    # @commands.hybrid_command(name='forceskip', aliases=['fskip'])
    # @commands.has_permissions(manage_guild=True)
    # async def _force_skip(self, ctx: mido_utils.Context):
    #     """Skip the currently playing song without requiring votes if enabled.
    #
    #     You need the **Manage Server** permission to use this command."""
    #     await ctx.voice_client.skip()
    #     await ctx.message.add_reaction('⏭')

    @commands.hybrid_command(name='queue', aliases=['q', 'songlist'])
    async def _queue(self, ctx: mido_utils.Context):
        """See the current song queue."""
        if len(ctx.voice_client.song_queue) == 0 and not ctx.voice_client.current:
            raise mido_utils.MusicError(f'The queue is empty. Try queueing songs with `{ctx.prefix}play`')

        blocks = []
        current = ctx.voice_client.get_current_or_last_song()
        queue_duration = current.duration

        # currently playing
        blocks.append(f"🎶 **[{current.title}]({current.url})**\n"
                      f"`{current.duration_str} | "
                      f"{current.requester}`\n")

        for i, song in enumerate(ctx.voice_client.song_queue, 1):
            song: mido_utils.Song
            blocks.append(f"**{i}**. **[{song.title}]({song.url})**\n"
                          f"`{song.duration_str} | "
                          f"{song.requester}`")
            queue_duration += song.duration

        queue_duration = mido_utils.Time.parse_seconds_to_str(queue_duration, short=True, sep=':')
        footer_text = f"{ctx.voice_client.volume}%  |  " \
                      f"{len(ctx.voice_client.song_queue) + 1} Songs  |  " \
                      f"{queue_duration} in Total"

        # loop info
        if ctx.voice_client.loop is True:
            footer_text += "  |  Loop Enabled 🔄"

        embed = (mido_utils.Embed(self.bot)
                 .set_author(icon_url=ctx.guild.icon.url, name=f"{ctx.guild.name} Music Queue ")
                 .set_footer(text=footer_text,
                             icon_url=mido_utils.images.volume)
                 )
        await embed.paginate(ctx, blocks, item_per_page=10, add_page_info_to='author')

    @commands.hybrid_command(name='shuffle')
    async def _shuffle(self, ctx: mido_utils.Context):
        """Shuffle the song queue."""
        if len(ctx.voice_client.song_queue) == 0:
            raise mido_utils.MusicError('The queue is empty.')

        ctx.voice_client.song_queue.shuffle()
        await ctx.send_success('Successfully shuffled the song queue.')

    @commands.hybrid_command(name='remove')
    async def _remove(self, ctx: mido_utils.Context, index: int):
        """Remove a song from the song queue."""
        if len(ctx.voice_client.song_queue) == 0:
            raise mido_utils.MusicError('The queue is empty.')

        if not 0 < index <= len(ctx.voice_client.song_queue):
            raise commands.BadArgument("Please specify a proper index!")

        if ctx.author.id != ctx.voice_client.song_queue[index - 1].requester.id:
            raise commands.CheckFailure("You are not the requester of this song!")

        ctx.voice_client.song_queue.remove(index - 1)
        await ctx.send_success('✅ Removed the song.')

    @commands.hybrid_command(name='loop', aliases=['repeatqueue'])
    @mido_utils.is_patron_decorator(level=2)
    async def _loop(self, ctx: mido_utils.Context):
        """Enable the loop feature to keep playing the current queue."""
        ctx.voice_client.loop = not ctx.voice_client.loop

        if ctx.voice_client.loop:
            await ctx.send_success("**🔄 Loop feature has been enabled.**\n\n"
                                   "Finished songs will be put back to the end of the queue.")
        else:
            await ctx.send_success("Loop feature has been disabled.")

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command(name='playnext', aliases=['pn'])  # not hybrid because of slash command limit
    async def _play_next(self, ctx: mido_utils.Context, *, query: str):
        """Put a song/songs to the top of your song queue so that it gets played next."""
        await self.ensure_voice_client(ctx)

        songs = await ctx.voice_client.fetch_songs_from_query(ctx, query, spotify=self.spotify_api)
        await ctx.voice_client.add_songs(ctx, *songs, add_to_beginning=True)

        await self.songs_added_message(ctx, songs)

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.hybrid_command(name='play', aliases=['p'])
    async def _play(self, ctx: mido_utils.Context, *, query: str):
        """Queue a song to play! You can use song names or YouTube/**Spotify** playlist/album/single links."""
        await self.ensure_voice_client(ctx)

        songs = await ctx.voice_client.fetch_songs_from_query(ctx, query, spotify=self.spotify_api)
        await ctx.voice_client.add_songs(ctx, *songs)

        await self.songs_added_message(ctx, songs)

    @commands.hybrid_command(name='autoplay', aliases=['ap'])
    async def _autoplay(self, ctx: mido_utils.Context):
        """Turn on or off autoplay."""
        await self.ensure_voice_client(ctx)

        if not ctx.voice_client.mido_autoplay:
            ctx.voice_client.mido_autoplay = True

            # add a song to kickstart it if we have no songs in the queue
            if len(ctx.voice_client.song_queue) == 0 and ctx.voice_client.last_song is not None:
                await ctx.voice_client.add_songs(ctx, await ctx.voice_client.get_recommended_song())

            await ctx.send_success("Autoplay has been enabled.")
        else:
            ctx.voice_client.mido_autoplay = False
            await ctx.send_success("Autoplay has been disabled.")

    @commands.hybrid_command(name='youtube', aliases=['yt'])
    async def _find_video(self, ctx: mido_utils.Context, *, query: str):
        """Find a YouTube video with the given query."""
        song: list[wavelink.Playable] = await wavelink.Pool.fetch_tracks(f'ytsearch:{query}')
        if not song:
            raise mido_utils.NotFoundError(f"Couldn't find anything that matches the query:\n"
                                           f"`{query}`.")

        await ctx.send(content=song[0].uri)

    @commands.hybrid_command()
    async def lyrics(self, ctx: mido_utils.Context, *, song_name: str = None):
        """See the lyrics of the current song or a specific song."""
        if not song_name and not ctx.voice_client.current:
            raise mido_utils.MusicError("You need to play a song then use this command, or specify a song name!")
        elif not song_name:
            song_name = ctx.voice_client.current.title

        cog: Searches = self.bot.get_cog('Searches')
        api = cog.some_random_api

        # TODO: scrape lyrics ourselves. some-random-api sucks
        try:
            song_title, lyrics_pages, thumbnail = await api.get_lyrics(song_name)
        except mido_utils.NotFoundError:
            raise mido_utils.NotFoundError(f"I couldn't find the lyrics of **{song_name}**.\n"
                                           f"Try writing the title in a simpler form.")

        e = mido_utils.Embed(bot=self.bot, title=song_title[:256], use_default_footer=True)
        e.set_thumbnail(url=thumbnail)

        await e.paginate(
            ctx=ctx,
            item_per_page=1,
            blocks=lyrics_pages,
            extra_sep='\n')

    @_volume.before_invoke
    @_now_playing.before_invoke
    @_pause_or_resume.before_invoke
    @_skip.before_invoke
    # @_force_skip.before_invoke
    @_loop.before_invoke
    @_seek.before_invoke
    async def ensure_playing(self, ctx: mido_utils.Context):
        """This func ensures that the voice player is playing something."""
        if not ctx.voice_client.playing:
            if len(ctx.voice_client.song_queue) >= 0:
                # if voice_player.task.done() is True:
                #     voice_player.task = ctx.bot.loop.create_task(voice_player.player_loop(),
                #                                                  name=f"Recovered Music Player of {ctx.guild.id}")
                # else:
                #     await voice_player.destroy()
                #     raise mido_utils.MusicError("Music player seems to be stuck. Please queue your songs again "
                #                             "and report this to help the developer fix the issue.")
                pass
            else:
                raise mido_utils.MusicError(f'Not playing anything at the moment. '
                                            f'Try playing something with `{ctx.prefix}play`')

    @_play.before_invoke
    @_connect.before_invoke
    @_play_next.before_invoke
    async def ensure_can_control(self, ctx: mido_utils.Context):
        """This func ensures that the author can control the player."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise mido_utils.MusicError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise mido_utils.MusicError('Bot is connected to a different voice channel.')

        if not ctx.author.voice.channel.permissions_for(ctx.guild.me).is_superset(discord.Permissions(1049600)):
            raise commands.UserInputError("I do not have permission to connect to that voice channel!")

    async def ensure_voice_client(self, ctx: mido_utils.Context):
        if not ctx.voice_client:
            await ctx.invoke(self._connect)

    @staticmethod
    async def songs_added_message(ctx: mido_utils.Context, songs: list):
        if len(songs) > 1:  # if it's a playlist
            shuffle_emote = '🔀'
            m = await ctx.send_success(
                f'**{len(songs)}** songs have been successfully added to the queue!\n\n'
                f'You can type `{ctx.prefix}queue` to see it.\n\n'
                f'*You can click {shuffle_emote} if you\'d like to shuffle the queue.*'
            )
            await m.add_reaction(shuffle_emote)

            r = await mido_utils.Embed.wait_for_reaction(ctx.bot, m, [shuffle_emote], author_id=ctx.author.id)
            if r:
                ctx.voice_client.song_queue.shuffle()
                await ctx.edit_custom(m, f'**{len(songs)}** songs have been successfully added to the queue!\n\n'
                                         f'You can type `{ctx.prefix}queue` to see it.\n\n'
                                         f'***{shuffle_emote} You\'ve successfully shuffled the queue.***')

        else:
            if ctx.voice_client.playing and len(ctx.voice_client.song_queue) >= 1:
                await ctx.send_success(
                    f'**{songs[0].title}** has been successfully added to the queue.\n\n'
                    f'You can type `{ctx.prefix}queue` to see it.'
                )


async def setup(bot: ShinobuBot):
    await bot.add_cog(Music(bot))
