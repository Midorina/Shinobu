from __future__ import annotations

import asyncio
import collections
import itertools
import random
from typing import Any, List, TYPE_CHECKING

import discord
import wavelink
from async_timeout import timeout
from wavelink import InvalidIDProvided, Player, Track

from .exceptions import IncompleteConfigFile, NotFoundError, OnCooldownError
from .resources import images
from .time import Time

if TYPE_CHECKING:
    from .context import Context


class VoicePlayer(Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.song_queue: SongQueue = SongQueue()
        self.next = asyncio.Event()

        self.loop = False
        self.skip_votes = []

        self.last_song: Song | None = None

        self.task = self.client.loop.create_task(self.player_loop(), name=f"Music Player of {self.channel.guild.id}")

    @property
    def position(self):
        if not self.is_playing() \
                or not self.current \
                or not self.last_update \
                or self.last_update.timestamp() == 0:
            return 0

        return super().position

    @property
    def current(self) -> Song | None:
        return self.source

    @current.setter
    def current(self, current: Song | None) -> None:
        self._source = current

    @property
    def position_str(self):
        return Time.parse_seconds_to_str(self.position, short=True, sep=':')

    async def destroy(self) -> None:
        try:
            await super().disconnect(force=True)
        except (InvalidIDProvided, KeyError):
            pass
        finally:
            self.task.cancel()

    async def add_songs(self, ctx: Context, *songs: Song, add_to_beginning=False):
        for i, song in enumerate(reversed(songs) if add_to_beginning is True else songs):
            if len(self.song_queue) > 5000:
                raise OnCooldownError("You can't add more than 5000 songs.")

            if isinstance(song, Track):
                song = Song.convert(song, ctx)

            if add_to_beginning is True:
                await self.song_queue.append_left(song)
            else:
                await self.song_queue.put(song)

    async def _get_tracks_from_query(self, ctx: Context, query: str) -> List[Song]:
        original_query = query
        if not query.startswith('http'):  # if not a link
            query = f'ytsearch:{query} Audio'

        song = None
        while not song:
            attempt = 0
            while attempt < 5:
                if song := await self.node.get_tracks(query=query, cls=wavelink.Track):
                    break
                await asyncio.sleep(0.5)
                attempt += 1

            if not song and query.endswith(' Audio'):
                # if we couldn't find the song, and it ends with "Audio"
                # the audio keyword might be the cause, so remove it and try again
                query = query[:-6]
            else:
                break

        if not song:
            raise NotFoundError(f"Couldn't find anything that matches the query:\n"
                                f"`{original_query}`.")

        if isinstance(song, wavelink.YouTubePlaylist):
            songs = song.tracks
        else:
            songs = [song[0]]

        return list(map(lambda x: Song.convert(x, ctx), songs))

    async def fetch_songs_from_query(self, ctx: Context, query: str, spotify=None):
        if query.startswith('https://open.spotify.com/'):  # spotify link
            if not spotify:
                raise IncompleteConfigFile(
                    "Spotify credentials have not been set up in the configuration file. "
                    "Please fill that in and restart the bot.")
            songs = [x for x in await spotify.get_songs(ctx, query) if x is not None]
        else:
            songs = await self._get_tracks_from_query(ctx, query)

        return songs

    async def skip(self):
        await self.stop()

    async def parse_and_get_the_next_song(self) -> Song:
        song = await self.song_queue.get()

        if not isinstance(song, Song):
            song: Song = (await self._get_tracks_from_query(song.ctx, song.search_query))[0]
        return song

    async def player_loop(self):
        await self.client.wait_until_ready()

        while True:
            self.next.clear()
            self.skip_votes.clear()

            if self.loop is True:
                await self.song_queue.put(self.last_song)

            try:
                async with timeout(180):
                    try:
                        self.current = await self.parse_and_get_the_next_song()
                    except NotFoundError as e:
                        await self.client.get_cog('ErrorHandling').on_error(e)
                        continue
                    else:
                        self.last_song = self.current

            except asyncio.TimeoutError:
                return await self.destroy()

            await self.play(self.current)

            # if loop is disabled or the song queue contains multiple songs
            if self.loop is False or len(self.song_queue) > 0:
                try:
                    await self.current.send_np_embed()
                except (discord.Forbidden, discord.NotFound):
                    pass

            await self.next.wait()

    def get_current_or_last_song(self) -> Song | None:
        return self.current or self.last_song


class BaseSong:
    def __init__(self, ctx: Context, title: str, duration_in_seconds: int, url: str):
        self.ctx = ctx

        self.title: str = title
        self.url: str = url
        self.duration: int = duration_in_seconds

    @property
    def duration_str(self) -> str:
        return Time.parse_seconds_to_str(self.duration, short=True, sep=':')

    @property
    def requester(self) -> discord.Member:
        return self.ctx.author

    @property
    def text_channel(self) -> discord.TextChannel:
        return self.ctx.channel

    @property
    def search_query(self) -> str:
        return self.title

    @classmethod
    def convert_from_spotify_track(cls, ctx: Context, track: dict) -> BaseSong | None:
        title = ", ".join(artist['name'] for artist in track['artists'])
        title += f" - {track['name']}"

        try:
            url = track["external_urls"]["spotify"]
        except KeyError:
            # no external url, meaning It's not actually playable on spotify
            return None

        duration = int(track["duration_ms"] / 1000)

        return cls(ctx, title, duration, url)


class Song(Track, BaseSong):
    def __init__(
            self,
            _id: str,
            info: dict[str, Any],
            ctx: Context
    ):
        super().__init__(_id, info)

        self.ctx: Context = ctx
        self.player: VoicePlayer = ctx.voice_client

    @property
    def url(self) -> str:
        return self.uri

    @classmethod
    def convert(cls,
                track: Track,
                ctx: Context):
        """Converts a native wavelink track object to a local Song object."""
        return cls(track.id, track.info, ctx)

    @property
    def thumbnail(self) -> str:
        return f"https://img.youtube.com/vi/{self.identifier}/maxresdefault.jpg"

    async def send_np_embed(self):
        e = self.create_np_embed()
        await self.text_channel.send(embed=e, delete_after=self.duration)

    def create_np_embed(self):
        e = discord.Embed(
            title=self.title,
            color=self.ctx.bot.color)

        e.set_author(
            icon_url=images.now_playing,
            name="Now Playing",
            url=self.url)

        e.add_field(name='Duration', value=f"{self.player.position_str}/{self.duration_str}")
        e.add_field(name='Requester', value=self.requester.mention)
        e.add_field(name='Uploader', value=self.author)

        # if self.source.upload_date:
        #     e.add_field(name="Upload Date", value=self.source.upload_date)
        #
        # e.add_field(name="View Count", value='{:,}'.format(self.source.views))
        #
        # if self.source.likes and self.source.dislikes:
        #     likes = self.source.likes
        #     dislikes = self.source.dislikes
        #     e.add_field(name="Like/Dislike Count",
        #                 value="{:,}/{:,}\n(**{:.2f}%**)".format(likes, dislikes, (likes * 100 / (likes + dislikes))))

        e.set_footer(text=f"Volume: {self.player.volume}%",
                     icon_url=images.volume)

        e.set_thumbnail(url=self.thumbnail)

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

    async def append_left(self, item):
        # self._queue.appendleft(item)  #
        await self.put(item)

        for _ in range(self.qsize() - 1):
            item = self.get_nowait()
            self.task_done()
            self.put_nowait(item)
