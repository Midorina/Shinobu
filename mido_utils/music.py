from __future__ import annotations

import asyncio
import collections
import itertools
import random
import time
from typing import List, Union

import discord
from async_timeout import timeout
from wavelink import InvalidIDProvided, Node, Player, Track

from mido_utils.context import Context
from mido_utils.resources import Resources
from mido_utils.time_stuff import Time


class VoicePlayer(Player):
    def __init__(self, bot, guild_id: int, node: Node, **kwargs):
        super().__init__(bot, guild_id, node, **kwargs)

        self.song_queue: SongQueue = SongQueue()
        self.next = asyncio.Event()

        self.loop = False
        self.skip_votes = []

        self.last_song = self.current

        self.bot.loop.create_task(self.player_loop())

    @property
    def position(self):
        if not self.is_playing or not self.current or not self.last_update:
            return 0

        if self.paused:
            return min(self.last_position, self.current.duration)

        difference = (time.time() * 1000) - self.last_update
        position = self.last_position + difference

        return min(position, self.current.duration)

    @property
    def position_in_seconds(self) -> int:
        return int(self.position / 1000)

    @property
    def position_str(self):
        return Time.parse_seconds_to_str(self.position_in_seconds, short=True, sep=':')

    async def destroy(self) -> None:
        await self.stop()

        try:
            await self.disconnect()
        except InvalidIDProvided:
            pass

        await self.node._send(op='destroy', guildId=str(self.guild_id))

        try:
            del self.node.players[self.guild_id]
        except KeyError:
            pass

    async def add_songs(self, song_or_songs: Union[Union[Song, Track], List[Union[Song, Track]]], ctx: Context):
        async def _convert_and_add(_song):
            if not isinstance(_song, Song):
                _song = Song.convert(_song, ctx)

            await self.song_queue.put(_song)

        if isinstance(song_or_songs, list):
            for song in song_or_songs:
                await _convert_and_add(song)
        else:
            await _convert_and_add(song_or_songs)

    async def skip(self):
        await self.stop()

    async def player_loop(self):
        while True:
            self.next.clear()
            self.skip_votes.clear()

            if self.loop is False:
                try:
                    async with timeout(180):
                        self.current: Song = await self.song_queue.get()
                        self.last_song = self.current
                except asyncio.TimeoutError:
                    return await self.destroy()
            else:
                self.current: Song = self.last_song

            await self.play(self.current)

            if not self.loop:
                await self.current.send_np_embed()

            await self.next.wait()


class Song(Track):
    def __init__(self, _id: str,
                 info: dict,
                 player: VoicePlayer,
                 requester: discord.Member,
                 text_channel:
                 discord.TextChannel,
                 query: str = None):
        super().__init__(_id, info, query)

        self.text_channel: discord.TextChannel = text_channel
        self.player: VoicePlayer = player
        self.requester: discord.Member = requester

        self.duration_str: str = Time.parse_seconds_to_str(self.duration_in_seconds, short=True, sep=':')

    @property
    def duration_in_seconds(self) -> int:
        return int(self.duration / 1000)

    @classmethod
    def convert(cls,
                track: Track,
                ctx: Context):
        """Converts a native wavelink track object to a local Song object."""
        return cls(track.id, track.info, ctx.voice_player, ctx.author, ctx.channel, track.query)

    async def send_np_embed(self):
        e = self.create_np_embed()
        await self.text_channel.send(embed=e)

    def create_np_embed(self):
        e = discord.Embed(
            title=self.title,
            color=0x15a34a)

        e.set_author(
            icon_url=Resources.images.now_playing,
            name="Now Playing",
            url=self.uri)

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
                     icon_url=Resources.images.volume)

        if self.thumb:
            e.set_thumbnail(url=self.thumb)

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
