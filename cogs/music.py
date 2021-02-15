import asyncio
import math

import discord
from discord.ext import commands
from wavelink import Client, Node, WavelinkMixin, ZeroConnectedNodes, events

import mido_utils
from midobot import MidoBot


class Music(commands.Cog, WavelinkMixin):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.forcekip_by_default = True

        self.spotify_api = mido_utils.SpotifyAPI(self.bot.http_session, self.bot.config['spotify_credentials'])

        if not hasattr(self.bot, 'wavelink'):
            self.bot.wavelink = Client(bot=self.bot)
            self.bot.loop.create_task(self.start_nodes())

        self.wavelink: Client = self.bot.wavelink

    async def start_nodes(self):
        # initiate the each node specified in the cfg file
        for node in self.bot.config['lavalink_nodes']:
            await self.wavelink.initiate_node(**node)

    async def reload_nodes(self):
        for node in self.bot.config['lavalink_nodes']:
            identifier = node['identifier']
            if identifier in self.wavelink.nodes:
                await self.wavelink.nodes[identifier].destroy()

            await self.wavelink.initiate_node(**node)

    async def cog_check(self, ctx: mido_utils.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage
        else:
            return True

    async def cog_before_invoke(self, ctx: mido_utils.Context):
        ctx.voice_player: mido_utils.VoicePlayer = self.wavelink.get_player(ctx.guild.id, cls=mido_utils.VoicePlayer)

    async def cog_command_error(self, ctx: mido_utils.Context, error):
        error = getattr(error, 'original', error)
        if isinstance(error, ZeroConnectedNodes):
            await self.reload_nodes()
            await asyncio.sleep(0.5)
            await ctx.reinvoke()

    @WavelinkMixin.listener(event="on_track_exception")
    async def track_errored_event(self, node: Node, payload: events.TrackException):
        channel = payload.player.last_song.text_channel
        await channel.send(f"There has been an error while playing `{payload.player.current}`:\n"
                           f"```{payload.error}```")

    @WavelinkMixin.listener(event="on_track_end")
    async def track_end_event(self, node: Node, payload: events.TrackEnd):
        payload.player.next.set()

    @commands.command(name='connect')
    async def _join(self, ctx: mido_utils.Context):
        """Make me connect to your voice channel."""
        await self.ensure_can_control(ctx)  # this is cuz ctx.invoke doesn't call pre-invoke hooks

        if ctx.voice_client and ctx.voice_client.channel.id == ctx.voice_player.channel_id:
            raise mido_utils.MusicError("I'm already connected to your voice channel.")

        try:
            await ctx.voice_player.connect(ctx.author.voice.channel.id)
        except asyncio.TimeoutError:
            raise discord.HTTPException
        else:
            await ctx.voice_player.set_volume(ctx.guild_db.volume)
            await ctx.message.add_reaction('👍')

    @commands.command(name='stop', aliases=['disconnect', 'destroy', 'd'])
    async def _leave(self, ctx: mido_utils.Context):
        """Make me disconnect from your voice channel."""
        if ctx.voice_player.channel_id:
            await ctx.voice_player.destroy()

            await ctx.send_success("I've successfully left the voice channel.")

        else:
            raise mido_utils.MusicError("I'm not currently not in a voice channel!")

    @commands.command(name='volume', aliases=['vol', 'v'])
    async def _volume(self, ctx: mido_utils.Context, volume: int = None):
        """Change or see the volume."""
        if volume is None:
            return await ctx.send_success(f'Current volume: **{ctx.voice_player.volume}**%')

        elif volume == 0:
            raise mido_utils.MusicError(f"Just do `{ctx.prefix}pause` rather than setting volume to 0.")

        elif volume < 0 or volume > 100:
            raise mido_utils.MusicError('The volume must be **between 0 and 100!**')

        # set
        await ctx.voice_player.set_volume(volume)
        await ctx.guild_db.change_volume(volume)

        await ctx.send_success(f'Volume is set to **{volume}**%')

    @commands.command(name='now', aliases=['current', 'playing', 'nowplaying', 'np'])
    async def _now_playing(self, ctx: mido_utils.Context):
        """See what's currently playing."""
        await ctx.send(embed=ctx.voice_player.current.create_np_embed())

    @commands.command(name='pause')
    async def _pause(self, ctx: mido_utils.Context):
        """Pause the song."""
        if ctx.voice_player.is_paused:
            raise mido_utils.MusicError(f"It's already paused! Use `{ctx.prefix}resume` to resume.")

        await ctx.voice_player.set_pause(pause=True)
        await ctx.message.add_reaction("⏯")

    @commands.command(name='resume')
    async def _resume(self, ctx: mido_utils.Context):
        """Resume the player."""
        if not ctx.voice_player.is_paused:
            raise mido_utils.MusicError(f"It's not paused! Use `{ctx.prefix}pause` to pause.")

        await ctx.voice_player.set_pause(pause=False)
        await ctx.message.add_reaction("⏯")

    @commands.command(name='skip', aliases=['next'])
    async def _skip(self, ctx: mido_utils.Context):
        """Skip the currently playing song."""
        voter = ctx.message.author
        vc = ctx.guild.get_channel(ctx.voice_player.channel_id)
        if not vc:
            raise mido_utils.MusicError("I can not see the voice channel I'm playing songs in.")

        people_in_vc = len(vc.members) - 1
        if people_in_vc <= 2:
            required_votes = people_in_vc
        else:
            required_votes = math.floor(people_in_vc * 0.8)

        if (voter == ctx.voice_player.get_current().requester  # if its the requester
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
            raise mido_utils.MusicError('You have already voted to skip this song.')

        await ctx.message.add_reaction('⏭')

    @commands.command(name='forceskip', aliases=['fskip'])
    @commands.has_permissions(manage_guild=True)
    async def _force_skip(self, ctx: mido_utils.Context):
        """Skip the currently playing song without requiring votes if enabled.

        You need the **Manage Server** permission to use this command."""
        await ctx.voice_player.skip()
        await ctx.message.add_reaction('⏭')

    @commands.command(name='queue', aliases=['q'])
    async def _queue(self, ctx: mido_utils.Context):
        """See the current song queue."""
        if len(ctx.voice_player.song_queue) == 0 and not ctx.voice_player.current:
            raise mido_utils.MusicError(f'The queue is empty. Try queueing songs with `{ctx.prefix}play`')

        blocks = []
        current = ctx.voice_player.get_current()
        queue_duration = current.duration_in_seconds

        # currently playing
        blocks.append(f"🎶 **[{current.title}]({current.url})**\n"
                      f"`{current.duration_str} | "
                      f"{current.requester}`\n")

        for i, song in enumerate(ctx.voice_player.song_queue, 1):
            blocks.append(f"**{i}**. **[{song.title}]({song.url})**\n"
                          f"`{song.duration_str} | "
                          f"{song.requester}`")
            queue_duration += song.duration_in_seconds

        queue_duration = mido_utils.Time.parse_seconds_to_str(queue_duration, short=True, sep=':')

        embed = (mido_utils.Embed(self.bot)
                 .set_author(icon_url=ctx.guild.icon_url, name=f"{ctx.guild.name} Music Queue - ")
                 .set_footer(text=f"{ctx.voice_player.volume}% | "
                                  f"{len(ctx.voice_player.song_queue) + 1} Songs | "
                                  f"{queue_duration} in Total",
                             icon_url=mido_utils.Resources.images.volume)
                 )
        await embed.paginate(ctx, blocks, item_per_page=5, add_page_info_to='author')

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: mido_utils.Context):
        """Shuffle the song queue."""
        if len(ctx.voice_player.song_queue) == 0:
            raise mido_utils.MusicError('The queue is empty.')

        ctx.voice_player.song_queue.shuffle()
        await ctx.send_success('Successfully shuffled the song queue.')

    @commands.command(name='remove')
    async def _remove(self, ctx: mido_utils.Context, index: int):
        """Remove a song from the song queue."""
        if len(ctx.voice_player.song_queue) == 0:
            raise mido_utils.MusicError('The queue is empty.')

        if not 0 < index <= len(ctx.voice_player.song_queue):
            raise commands.BadArgument("Please specify a proper index!")

        if ctx.author.id != ctx.voice_player.song_queue[index - 1].requester.id:
            raise commands.CheckFailure("You are not the requester of this song!")

        ctx.voice_player.song_queue.remove(index - 1)
        await ctx.send_success('✅ Removed the song.')

    @commands.command(name='loop', aliases=['repeat'])
    async def _loop(self, ctx: mido_utils.Context):
        """Enable the loop feature to play the same song over and over."""
        # Inverse boolean value to loop and unloop.
        ctx.voice_player.loop = not ctx.voice_player.loop

        if ctx.voice_player.loop:
            await ctx.send_success("I will play the same song from now on.")
        else:
            await ctx.send_success("The loop feature has been disabled.")

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command(name='play', aliases=['p'])
    async def _play(self, ctx: mido_utils.Context, *, query: str):
        """Queue a song to play!"""
        task = None
        if not ctx.voice_player.channel_id:
            task = self.bot.loop.create_task(ctx.invoke(self._join))

        added_songs = await ctx.voice_player.parse_query_and_add_songs(ctx, query, spotify=self.spotify_api)
        if task:
            await task
            task.result()

        if len(added_songs) > 1:  # if its a playlist
            shuffle_emote = '🔀'
            m = await ctx.send_success(
                f'**{len(added_songs)}** songs have been successfully added to the queue!\n\n'
                f'You can type `{ctx.prefix}queue` to see it.\n\n'
                f'*You can click {shuffle_emote} if you\'d like to shuffle the queue.*'
            )
            await m.add_reaction(shuffle_emote)

            r = await mido_utils.Embed.wait_for_reaction(ctx.bot, m, [shuffle_emote], author_id=ctx.author.id)
            if r:
                ctx.voice_player.song_queue.shuffle()
                await ctx.edit_custom(m, f'**{len(added_songs)}** songs have been successfully added to the queue!\n\n'
                                         f'You can type `{ctx.prefix}queue` to see it.\n\n'
                                         f'***You\'ve successfully shuffled the queue.***')
            else:
                await m.remove_reaction(shuffle_emote, ctx.guild.me)

        else:
            if len(ctx.voice_player.song_queue) >= 1 and ctx.voice_player.is_playing:
                await ctx.send_success(
                    f'**{added_songs[0].title}** has been successfully added to the queue.\n\n'
                    f'You can type `{ctx.prefix}queue` to see it.'
                )

    @commands.command(name='youtube', aliases=['yt'])
    async def _find_video(self, ctx: mido_utils.Context, *, query: str):
        """Find a YouTube video with the given query."""
        song = await self.wavelink.get_tracks(query=f'ytsearch:{query}', retry_on_failure=True)
        if not song:
            raise mido_utils.NotFoundError(f"Couldn't find anything that matches the query:\n"
                                           f"`{query}`.")

        await ctx.send(content=song[0].uri)

    @commands.command()
    async def lyrics(self, ctx: mido_utils.Context, *, song_name: str = None):
        """See the lyrics of the current song or a specific song."""
        if not song_name and not ctx.voice_player.current:
            raise mido_utils.MusicError("You need to play a song then use this command or specify a song name!")
        elif not song_name:
            song_name = ctx.voice_player.current.title

        api = self.bot.get_cog('Searches').some_random_api

        try:
            song_title, lyrics_pages, thumbnail = await api.get_lyrics(song_name)
        except mido_utils.NotFoundError:
            raise mido_utils.NotFoundError(f"I couldn't find the lyrics of **{song_name}**.\n"
                                           f"Try writing the title in a simpler form.")

        e = mido_utils.Embed(bot=self.bot, title=song_title[:256], default_footer=True)
        e.set_thumbnail(url=thumbnail)

        await e.paginate(
            ctx=ctx,
            item_per_page=1,
            blocks=lyrics_pages,
            extra_sep='\n')

    @_volume.before_invoke
    @_now_playing.before_invoke
    @_pause.before_invoke
    @_resume.before_invoke
    @_skip.before_invoke
    @_force_skip.before_invoke
    @_loop.before_invoke
    async def ensure_playing(self, ctx: mido_utils.Context):
        """This func ensures that the voice player is playing something."""
        voice_player: mido_utils.VoicePlayer = self.wavelink.get_player(ctx.guild.id, cls=mido_utils.VoicePlayer)

        if not voice_player.is_playing:
            if len(voice_player.song_queue) != 0:
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
    @_join.before_invoke
    async def ensure_can_control(self, ctx: mido_utils.Context):
        """This func ensures that the author can control the player."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise mido_utils.MusicError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise mido_utils.MusicError('Bot is connected to a different voice channel.')

        if not ctx.author.voice.channel.permissions_for(ctx.guild.me).is_superset(discord.Permissions(1049600)):
            raise commands.UserInputError("I do not have permission to connect to that voice channel!")


def setup(bot):
    bot.add_cog(Music(bot))
