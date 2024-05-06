from __future__ import annotations

import asyncio
import collections
import itertools
import logging
import random
from typing import TYPE_CHECKING, List

import discord
import wavelink
from async_timeout import timeout
from wavelink import Player, Playable

from .exceptions import IncompleteConfigFile, NotFoundError, OnCooldownError
from .resources import images
from .time import Time

if TYPE_CHECKING:
    from wavelink.types.tracks import TrackPayload
    from .context import Context


class VoicePlayer(Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.song_queue: SongQueue = SongQueue()
        self.next = asyncio.Event()
        self.last_song: Song | None = None

        self.skip_votes = []
        self.loop = False

        self._mido_autoplay = False  # wavelink's own autoplay feature uses their own queue, but we have our own queue
        self.autoplay_queue: List[Song] = []

        self.task = self.client.loop.create_task(self.player_loop(), name=f"Music Player of {self.channel.guild.id}")

    @property
    def position(self):
        if not self.playing \
                or not self.current \
                or not self._last_update \
                or self._last_update == 0:
            return 0

        return super().position

    @property
    def current(self) -> Song | None:
        return super().current

    @current.setter
    def current(self, current: Song | None) -> None:
        self._current = current

    @property
    def mido_autoplay(self) -> bool:
        return self._mido_autoplay

    @mido_autoplay.setter
    def mido_autoplay(self, autoplay_active: bool) -> None:
        self._mido_autoplay = autoplay_active
        self.autoplay_queue.clear()

    @property
    def position_str(self):
        return Time.parse_seconds_to_str(self.position / 1000, short=True, sep=':')

    async def destroy(self) -> None:
        try:
            await super().disconnect(force=True)
        except KeyError:
            pass
        finally:
            self.task.cancel()

    async def add_songs(self, ctx: Context, *songs: Song, add_to_beginning=False):
        for i, song in enumerate(reversed(songs) if add_to_beginning is True else songs):
            if len(self.song_queue) > 5000:
                raise OnCooldownError("You can't add more than 5000 songs.")

            if isinstance(song, Playable):
                song = Song.convert(song, ctx)

            if add_to_beginning is True:
                await self.song_queue.append_left(song)
            else:
                await self.song_queue.put(song)

    async def _get_tracks_from_query(self, ctx: Context, query: str) -> list[Song]:
        original_query = query
        if not query.startswith('http'):  # if not a link
            # query = f'ytsearch:{query} Audio'
            query = f'ytsearch:{query}'

        song = None
        while not song:
            attempt = 0
            while attempt < 5:
                if song := await wavelink.Pool.fetch_tracks(query):
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

        songs: List[Playable]
        if isinstance(song, wavelink.Playlist):
            songs = song.tracks
        elif isinstance(song, list):
            songs = [song[0]]
        else:
            raise Exception(f"Unexpected song type: {type(song)}")

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

    async def parse_and_get_the_next_song(self) -> Song:
        song = await self.song_queue.get()

        if not isinstance(song, Song):
            song: Song = (await self._get_tracks_from_query(song.ctx, song.search_query))[0]

        return song

    async def get_recommended_song(self) -> Song:
        """Gets a recommended song from the last song that was played. This is usually used if autoplay is enabled."""
        if not self.last_song:
            raise NotFoundError("No song has been played yet.")

        # if the autoplay queue is empty, get the recommended songs from the last song
        if len(self.autoplay_queue) == 0:
            seed = self.last_song.identifier
            self.autoplay_queue = (await self._get_tracks_from_query(
                self.last_song.ctx,
                f"https://music.youtube.com/watch?v={seed}8&list=RD{seed}"
            ))[1:]  # remove the first song, because it's the same song

        # return the first song in the autoplay queue
        return self.autoplay_queue.pop(0)

    async def player_loop(self):
        await self.client.wait_until_ready()

        while True:
            self.next.clear()
            self.skip_votes.clear()

            if self.mido_autoplay is True and len(self.song_queue) == 0:
                try:
                    song = await self.get_recommended_song()
                except NotFoundError:
                    pass
                else:
                    await self.add_songs(song.ctx, song)

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

            try:
                await self.play(self.current)
            except Exception as e:
                await self.client.get_cog('ErrorHandling').on_error(e)
                continue

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

        self._title: str = title
        self._uri: str = url
        self.duration: int = duration_in_seconds

    @property
    def title(self) -> str:
        return self._title

    @property
    def url(self) -> str:
        return self._uri

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
        return self._title

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


class Song(Playable, BaseSong):
    def __init__(
            self,
            info: TrackPayload,
            ctx: Context
    ):
        Playable.__init__(self, info)
        BaseSong.__init__(self, ctx, info['info']['title'], int(info['info']['length'] / 1000), info['info']['uri'])

        self.ctx: Context = ctx
        self.player: VoicePlayer = ctx.voice_client

    @property
    def url(self) -> str:
        return self.uri

    @classmethod
    def convert(cls,
                track: Playable,
                ctx: Context):
        """Converts a native wavelink playable object to a local Song object."""
        return cls(track._raw_data, ctx)

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
