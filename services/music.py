import asyncio
import audioop
import collections
import functools
import itertools
import random

import discord
import youtube_dl
from async_timeout import timeout

# TODO: use ffmpeg to seek
from services.context import MidoContext
from services.time_stuff import MidoTime


class YTDLSource(discord.PCMVolumeTransformer):
    # youtube_dl.utils.std_headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64) ' \
    #                                              'AppleWebKit/537.36 (KHTML, like Gecko) ' \
    #                                              'Chrome/51.0.2704.103 Safari/537.36'
    youtube_dl.utils.std_headers[
        'User-Agent'] = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'

    YTDL_OPTIONS = {
        'format'            : 'bestaudio/best',
        'extractaudio'      : True,
        'audioformat'       : 'mp3',
        # 'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames' : True,
        # 'playlistend': 100,
        'nocheckcertificate': True,
        'ignoreerrors'      : True,
        'logtostderr'       : False,
        'quiet'             : True,
        'no_warnings'       : True,
        'default_search'    : 'auto',
        'source_address'    : '0.0.0.0',
        'cachedir'          : False,
        # 'cookiefile': 'other/cookies.txt',
        'verbose'           : True
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options'       : '-vn',
    }

    BLACKLISTED_TITLES = [
        '[Deleted video]',
        '[Private video]'
    ]

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: MidoContext, source: discord.FFmpegPCMAudio, *, data: dict, volume: int = 10):
        super().__init__(source, volume / 100)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data
        self.ctx = ctx

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')

        self.upload_date = data.get('upload_date')
        if self.upload_date:
            self.upload_date = self.upload_date[6:8] + '.' + self.upload_date[4:6] + '.' + self.upload_date[0:4]

        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = MidoTime.parse_seconds_to_str(int(data.get('duration')), short=True, sep=':')
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')
        self._played_duration = 0

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls,
                            ctx: MidoContext,
                            search: str,
                            process: bool = True,
                            loop: asyncio.BaseEventLoop = asyncio.get_event_loop()) -> list:
        if search in cls.BLACKLISTED_TITLES:
            return []

        try:
            partial = functools.partial(cls.ytdl.extract_info, url=search, download=False, process=process)
            processed_info = await loop.run_in_executor(None, partial)
            if not processed_info:
                raise youtube_dl.DownloadError('No processed info.')
        except youtube_dl.DownloadError:
            return []

        # if we have a list of entries (most likely a playlist or a search)
        if 'entries' in processed_info:
            # this is an issue that I don't know why happens or how to fix.
            if processed_info['entries'] is None:
                print(processed_info)
                # raise youtube_dl.DownloadError('For some reason, YouTube returned no results for this.')

            if process is True:
                return [cls(ctx, discord.FFmpegPCMAudio(song['url'], **cls.FFMPEG_OPTIONS), data=song)
                        for song in processed_info['entries']]
            else:
                return [song['title'] for song in processed_info['entries']]

        # if a song link is provided
        else:
            if process is True:
                return [
                    cls(ctx, discord.FFmpegPCMAudio(processed_info['url'], **cls.FFMPEG_OPTIONS), data=processed_info)]
            else:
                return [processed_info['webpage_url']]

    @property
    def played_duration(self) -> str:
        return MidoTime.parse_seconds_to_str(int(self._played_duration), short=True, sep=':')

    def read(self):
        self._played_duration += 0.02
        ret = self.original.read()
        return audioop.mul(ret, 2, min(self._volume, 2.0))


class Song:
    __slots__ = ('ctx', 'source', 'requester')

    def __init__(self, source: YTDLSource):
        self.ctx = source.ctx
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        e = discord.Embed(
            title=self.source.title,
            color=0x15a34a)

        e.set_author(
            icon_url="https://cdn.discordapp.com/attachments/244405453948321792/707797956295655434/PngItem_2087614.png",
            name="Now Playing",
            url=self.source.url)

        e.add_field(name='Duration', value=f"{self.source.played_duration}/{self.source.duration}")
        e.add_field(name='Requester', value=self.requester.mention)
        e.add_field(name='Uploader', value=f'[{self.source.uploader}]({self.source.uploader_url})')

        if self.source.upload_date:
            e.add_field(name="Upload Date", value=self.source.upload_date)

        e.add_field(name="View Count", value='{:,}'.format(self.source.views))

        if self.source.likes and self.source.dislikes:
            likes = self.source.likes
            dislikes = self.source.dislikes
            e.add_field(name="Like/Dislike Count",
                        value="{:,}/{:,}\n(**{:.2f}%**)".format(likes, dislikes, (likes * 100 / (likes + dislikes))))

        e.set_footer(text=f"Volume: {int(self.source.volume * 100)}%",
                     icon_url="https://i.imgur.com/T0532pn.png")

        if self.source.thumbnail:
            e.set_thumbnail(url=self.source.thumbnail)

        return e


class SongQueue(asyncio.Queue):
    def _init(self, maxsize):
        self._queue = collections.deque()

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
        # noinspection PyTypeChecker
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    from midobot import MidoBot

    # noinspection PyTypeChecker
    def __init__(self, bot: MidoBot):
        self.bot = bot
        self.exists: bool = True

        self.songs = SongQueue()
        self.current: Song = None
        self.next = asyncio.Event()

        self.voice: discord.VoiceClient = None

        self._loop = False
        self._volume = 10
        self.skip_votes = []

        self.played_duration = 0
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
    def volume(self, new_vol: int):
        self._volume = new_vol
        if self.current:
            self.current.source.volume = new_vol / 100

    @property
    def is_playing(self):
        return self.voice is not None and self.voice.is_playing()

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                try:
                    async with timeout(5):
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    return self.bot.loop.create_task(self.stop())

            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise Exception(str(error))
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
            self.exists = False
