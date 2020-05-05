import asyncio
import functools
import itertools
import math
import random

import discord
import youtube_dl
from discord.ext import commands, tasks


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class AlreadyConnected(Exception):
    pass


class MusicError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
        'cachedir': False
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data
        self.ctx = ctx

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        try:
            webpage_url = process_info['webpage_url']
        except KeyError:
            raise YTDLError("We currently do not support playlists.")
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return '\n'.join(duration)


class Song:
    __slots__ = ('ctx', 'source', 'requester')

    def __init__(self, source: YTDLSource):
        self.ctx = source.ctx
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        e = discord.Embed(description='```css\n{0.source.title}\n```'.format(self),
                          color=discord.Color.blurple())
        e.set_author(
            icon_url="https://img.favpng.com/20/12/15/youtube-kids-logo-png-favpng-JGLG77wUvkCUia4GXe51wsJBL.jpg",
            name="Now Playing",
            url=self.source.url)
        e.add_field(name='Requested by', value=self.requester.mention)
        e.add_field(name='Duration', value=self.source.duration if self.source.duration else 'Unknown')
        e.add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
        e.add_field(name="Upload Date", value=self.source.upload_date)
        e.add_field(name="View Count", value='{:,}'.format(self.source.views))

        if self.source.likes and self.source.dislikes:
            likes = self.source.likes
            dislikes = self.source.dislikes
            e.add_field(name="Like/Dislike Count",
                        value="{:,}/{:,}\n(**{:.2f}%**)".format(likes, dislikes, (likes * 100 / (likes + dislikes))))

        e.set_footer(icon_url=self.ctx.guild.icon_url, text=self.ctx.guild.name)
        e.set_thumbnail(url=self.ctx.guild.icon_url)
        e.set_image(url=self.source.thumbnail)

        return e


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.current = None
        self.voice = None
        self.exists = True
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = []

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume, self.current.source.volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                self.current = None
                while not self.current:
                    # it waits until it gets a song so this loop is fine.
                    # this is to make sure we have a current song.
                    self.current = await self.songs.get()

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))
        self.skip_votes.clear()
        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect(force=True)
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.voice_states = {}

    def get_voice_state(self, guild_id: int):
        state = self.voice_states.get(guild_id)

        if not state or not state.exists:
            state = VoiceState(self.bot)
            self.voice_states[guild_id] = state

        return state

    async def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx.guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        vc = member.guild.get_channel(self.bot.config['music_vc_id'])

        # if they left the music vc
        if before and before == vc:
            # if only lester is there
            if len(vc.members) == 1:
                vs = self.get_voice_state(member.guild.id)
                vs.songs.clear()
                vs.skip()

    @commands.command(name='connect')
    async def _join(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise MusicError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise MusicError('Bot is already in a voice channel.')

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='disconnect', aliases=['destroy', 'd'])
    async def _leave(self, ctx):
        if not ctx.voice_state.voice:
            await ctx.send("I'm not currently playing any music!")
            return

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]
        await ctx.send("I've successfully left the voice channel.")

    @commands.command(name='volume', aliases=['v'])
    async def _volume(self, ctx, volume: int = None):
        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        if not volume:
            return await ctx.send(f'Current volume: {ctx.voice_state.volume * 100}%')

        if 0 > volume > 100:
            return await ctx.send('Volume must be between 0 and 100')

        ctx.voice_state.volume = volume / 100
        await ctx.send(f'Volume of the player set to {volume}%')

    @commands.command(name='now', aliases=['current', 'playing', 'nowplaying', 'np'])
    async def _now(self, ctx: commands.Context):
        if ctx.voice_state.current:
            await ctx.send(embed=ctx.voice_state.current.create_embed())
        else:
            await ctx.send("I'm not currently playing any music!")

    @commands.command(name='pause', aliases=['p'])
    async def _pause(self, ctx: commands.Context):
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')
        else:
            await ctx.send("I'm not currently playing any music!")

    @commands.command(name='resume')
    async def _resume(self, ctx: commands.Context):
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')
        else:
            await ctx.send("I'm not currently playing any music!")

    @commands.command(name='stop')
    async def _stop(self, ctx: commands.Context):
        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')
        else:
            await ctx.send("I'm not currently playing any music!")

    @commands.command(name='skip', aliases=['next'])
    async def _skip(self, ctx: commands.Context):
        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        vc = ctx.voice_state.voice.channel
        if ctx.author not in vc.members:
            return await ctx.send("You are not in the voice channel!")

        people_in_vc = len(vc.members) - 1
        if people_in_vc <= 2:
            required_votes = people_in_vc
        else:
            required_votes = math.floor(people_in_vc * 0.8)

        # if it reached the required vote amount
        if voter == ctx.voice_state.current.requester or len(ctx.voice_state.skip_votes) == required_votes:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.append(voter.id)

            total_votes = len(ctx.voice_state.skip_votes)
            if total_votes >= required_votes:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send('Skip vote added, currently at **{}/{}**'.format(total_votes, required_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='forceskip', aliases=['fskip'])
    @commands.has_permissions(manage_guild=True)
    async def _force_skip(self, ctx: commands.Context):
        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        await ctx.message.add_reaction('⏭')
        ctx.voice_state.skip()

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(color=discord.Colour.blurple(),
                               description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages))
                 .set_author(icon_url=ctx.guild.icon_url, name=f"{ctx.guild.name} Music Queue")
                 )
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        if not 0 < index <= len(ctx.voice_state.songs):
            return await ctx.send("Please specify a proper index!")

        if ctx.author.id != ctx.voice_state.songs[index - 1].requester.id:
            return await ctx.send("You are not the requester of this song!")

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    # This command has been disabled due to issues its causing.
    # @commands.command(name='loop')
    # async def _loop(self, ctx: commands.Context):
    #     if not ctx.voice_state.is_playing:
    #         return await ctx.send('Nothing being played at the moment.')
    #
    #     # Inverse boolean value to loop and unloop.
    #     ctx.voice_state.loop = not ctx.voice_state.loop
    #     await ctx.message.add_reaction('✅')

    @commands.command(name='play')
    async def _play(self, ctx: commands.Context, *, search: str):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise MusicError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise MusicError('Bot is already in a voice channel.')

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        # checks
        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except (YTDLError, youtube_dl.DownloadError) as e:
                await ctx.send(str(e))
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send('Queued {}'.format(str(source)))


def setup(bot):
    bot.add_cog(Music(bot))
