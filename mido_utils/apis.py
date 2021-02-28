from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from typing import List, Tuple, Union

import aiohttp
import anekos
import asyncpraw
import asyncprawcore
from aiohttp import ClientResponse, ClientSession
from anekos.client import Tag
from asyncpg.pool import Pool
from bs4 import BeautifulSoup
from discord.ext.commands import TooManyArguments

import mido_utils
from models.db import CachedImage, NSFWImage
from models.hearthstone import HearthstoneCard
from models.subreddits import LocalSubreddit

__all__ = ['MidoBotAPI', 'NekoAPI', 'RedditAPI', 'NSFW_DAPIs', 'SomeRandomAPI', 'Google', 'SpotifyAPI', 'BlizzardAPI']


class MidoBotAPI:
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \
                 "AppleWebKit/537.36 (KHTML, like Gecko) " \
                 "Chrome/88.0.4324.190 Safari/537.36"

    DEFAULT_HEADERS = {
        'User-Agent'     : USER_AGENT,
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self, session: ClientSession):
        self.session = session

    @classmethod
    def get_aiohttp_session(cls):
        return ClientSession(headers=cls.DEFAULT_HEADERS,
                             connector=aiohttp.TCPConnector(limit=0))

    async def _request_get(self,
                           url: str,
                           params: dict = None,
                           headers: dict = None,
                           return_url=False,
                           return_json=False) -> Union[str, dict, ClientResponse]:
        try:
            async with self.session.get(url=url, params=params, headers=headers) as response:
                if not response.status == 200:
                    raise mido_utils.APIError(f"{response.status} for URL: {response.url}")

                if return_url is True:
                    return str(response.url)

                elif return_json is True:
                    try:
                        js = await response.json()
                    except aiohttp.ContentTypeError:
                        try:
                            js = json.loads(await response.read())
                        except json.JSONDecodeError:
                            js = None

                    if not js:
                        raise mido_utils.NotFoundError
                    elif 'error' in js:
                        raise mido_utils.RateLimited

                    return js

                else:
                    return response
        except (aiohttp.ServerDisconnectedError, asyncio.TimeoutError):
            raise mido_utils.APIError


class CachedImageAPI(MidoBotAPI):
    def __init__(self, session: ClientSession, db: Pool):
        super(CachedImageAPI, self).__init__(session)

        self.db = db

    async def add_to_db(self, api_name: str, urls: List[str], tags: List[str] = None) -> None:
        if tags is None:
            tags = []

        if urls:
            await self.db.executemany(
                """INSERT INTO api_cache(api_name, url, tags) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING;""",
                ((api_name, url, tags) for url in urls)
            )


class NekoAPI(anekos.NekosLifeClient, CachedImageAPI):
    NSFW_NEKO_TAGS = [anekos.NSFWImageTags.NSFW_NEKO_GIF, anekos.NSFWImageTags.ERONEKO]
    SFW_NEKO_TAGS = [anekos.SFWImageTags.NEKOGIF, anekos.SFWImageTags.NEKO]

    def __init__(self, session: ClientSession, db: Pool):
        super().__init__(session=session)  # NekosLifeClient

        self.db = db  # CachedImageAPI

    async def image(self, tag: Tag, get_bytes: bool = False) -> anekos.result.ImageResult:
        while True:
            try:
                ret = await super(NekoAPI, self).image(tag, get_bytes)
            except (aiohttp.ContentTypeError, anekos.errors.NoResponse, asyncio.TimeoutError):
                raise mido_utils.APIError
            else:
                if ret.url == 'https://cdn.nekos.life/smallboobs/404.png':
                    continue

                # await self.add_to_db(api_name="nekos.life", urls=[ret.url], tags=[str(ret.tag)])
                return ret

    async def get_random_neko(self, nsfw=False):
        if nsfw is True:
            tags = self.NSFW_NEKO_TAGS
        else:
            tags = self.SFW_NEKO_TAGS

        return await self.image(tag=random.choice(tags))


class RedditAPI(CachedImageAPI):
    def __init__(self, credentials: dict, session: ClientSession, db: Pool):
        super().__init__(session, db)

        self.reddit = asyncpraw.Reddit(
            **credentials,
            user_agent=MidoBotAPI.USER_AGENT,
            requestor_kwargs={"session": self.session}
        )

    @staticmethod
    def parse_gfycat_to_red_gif(urls: List[str]):
        def already_replaced(new_word, _replaced_words):
            for _word in _replaced_words:
                if new_word in _word:
                    return True

        ret = []
        for url in urls:
            if '/comments/' in url:  # reddit links that forward to comments are deleted
                continue

            if 'gfycat.com' in url or 'redgifs.com' in url:
                replaced_words = []

                _id = url.split('/')[-1].split('-')[0].split('?')[0]

                if not any(x.isupper() for x in _id):  # if capital letters are missing
                    for word_type, word_list in mido_utils.Resources.strings.gfycat_words.items():
                        word_list = sorted(word_list, key=lambda x: len(x), reverse=True)
                        for word in word_list:
                            if word in _id:
                                # check if its replacing an already replaced word
                                if already_replaced(word, replaced_words):
                                    continue
                                # make the first letter capital
                                _id = _id.replace(word, word[0].upper() + word[1:])
                                replaced_words.append(word)

                if 'gfycat.com' in url:
                    ret.append(f'https://thumbs.redgifs.com/{_id}-size_restricted.gif')
                elif "redgifs.com" in url:
                    ret.append(f'https://thcf7.redgifs.com/{_id}-size_restricted.gif')
            else:
                ret.append(url)

        return ret

    async def get_images_from_subreddit(self, subreddit_name: str, submission_category: str = 'top', *args, **kwargs):
        subreddit = await self.reddit.subreddit(subreddit_name)

        if submission_category == 'top':
            category = subreddit.top
        elif submission_category == 'hot':
            category = subreddit.hot
        else:
            raise Exception(f"Unknown category name: {submission_category}")

        urls = []
        try:
            async for submission in category(*args, **kwargs):
                urls.append(submission.url)
                await asyncio.sleep(0.1)
        except (asyncprawcore.NotFound, asyncprawcore.Forbidden) as e:
            logging.error(f"Subreddit '{subreddit_name}' caused error: {e}")
            return

        urls = self.parse_gfycat_to_red_gif(urls)

        await self.add_to_db(api_name=f'reddit_{subreddit_name}',
                             urls=urls,
                             tags=[subreddit_name])

    @staticmethod
    async def get_reddit_post_from_db(bot,
                                      category: str,
                                      tags: List[str] = None,
                                      limit: int = 1,
                                      allow_gif: bool = False) -> List[CachedImage]:
        subreddits = LocalSubreddit.get_with_related_tag(category=category, tags=tags)
        return await CachedImage.get_random(bot=bot,
                                            subreddits=subreddits,
                                            allow_gif=allow_gif,
                                            limit=limit)

    async def fill_the_database(self):
        async def _fill(sub_name: str, go_ham=False):
            # top
            # hot

            # all
            # year
            # month
            # week
            # day
            # hour

            await self.get_images_from_subreddit(sub_name, 'top', 'day', limit=5)
            await self.get_images_from_subreddit(sub_name, 'hot', limit=1)

            if go_ham is True:
                await self.get_images_from_subreddit(sub_name, 'top', 'all', limit=10000)
                await self.get_images_from_subreddit(sub_name, 'top', 'year', limit=10000)
                await self.get_images_from_subreddit(sub_name, 'top', 'month', limit=1000)
                await self.get_images_from_subreddit(sub_name, 'top', 'week', limit=10)

        for sub in LocalSubreddit.get_all():
            await _fill(sub.subreddit_name)

class NSFW_DAPIs(CachedImageAPI):
    BLACKLISTED_TAGS = [
        'loli',
        'shota',
        'child',
        'kid',
        'underage',
        'guro',
        'blood',
        'gore',
        'flat_chest'
    ]

    DAPI_LINKS = {
        'danbooru': 'https://danbooru.donmai.us/posts.json',
        'gelbooru': 'https://gelbooru.com/index.php',
        'rule34'  : 'https://rule34.xxx/index.php'
        # 'sankaku_complex': 'https://capi-v2.sankakucomplex.com/posts'
    }

    def __init__(self, session: ClientSession, db: Pool):
        super(NSFW_DAPIs, self).__init__(session, db)

    async def get(self, nsfw_type: str, tags: str = None, limit: int = 1, allow_video=False) -> List[NSFWImage]:
        base_tags = tags
        tags = self._parse_tags(tags)

        if nsfw_type in ('rule34', 'gelbooru'):
            tags.extend(('rating:explicit', 'sort:random', 'score:>=50'))

            func = self._get_nsfw_dapi
            args = [nsfw_type, tags, allow_video, limit]

        elif nsfw_type == 'sankaku_complex':
            # max 2 args
            tags = tags[:2]
            tags.extend(('rating:explicit', 'order:random', 'score:>=50'))

            func = self._get_nsfw_dapi
            args = [nsfw_type, tags, allow_video, limit]

        elif nsfw_type == 'danbooru':
            # max 2 args
            tags = tags[:2]
            tags.append('rating:explicit')

            func = self._get_danbooru
            args = [tags, allow_video, limit]

        else:
            raise Exception(f"Unknown nsfw type: {nsfw_type}")

        fetched_imgs = await func(*args)

        if not fetched_imgs:
            raise mido_utils.NotFoundError

        # await self.add_to_db(nsfw_type, fetched_imgs, tags=tags)

        fetched_imgs = [NSFWImage(x, tags=base_tags, api_name=nsfw_type) for x in fetched_imgs]

        try:
            return random.sample(fetched_imgs, limit)
        except ValueError:
            return fetched_imgs

    async def get_bomb(self, tags, limit=3, allow_video: bool = True) -> List[NSFWImage]:
        urls = []

        for dapi in random.sample(self.DAPI_LINKS.keys(), len(self.DAPI_LINKS.keys())):
            try:
                urls.extend(await self.get(dapi, tags, limit=limit, allow_video=allow_video))
            except (mido_utils.NotFoundError, TooManyArguments, mido_utils.APIError):
                pass

        try:
            return random.sample(urls, limit)
        except ValueError:
            if not urls:
                raise mido_utils.NotFoundError
            else:
                return urls

    def _parse_tags(self, tags: str) -> List[str]:
        if tags is None:
            return []

        tags = tags.replace(' ', '_').lower().split('+')

        return list(filter(lambda x: x not in self.BLACKLISTED_TAGS, tags))

    def is_blacklisted(self, tags):
        for tag in tags:
            if tag in self.BLACKLISTED_TAGS:
                return True
        return False

    @staticmethod
    def is_video(url: str):
        return url.endswith('.webm') or url.endswith('.mp4')

    async def _get_nsfw_dapi(self, dapi_name, tags: List[str], allow_video=False, score: int = 10, limit: int = 100) -> \
    List[str]:
        images = []

        if f'score:>={score}' in tags:
            pass
        else:
            for tag in tags:
                if tag.startswith('score'):
                    tags.remove(tag)

            tags.append(f'score:>={score}')

        while True:
            try:
                response_jsond = await self._request_get(self.DAPI_LINKS[dapi_name], params={
                    'page' : 'dapi',
                    's'    : 'post',
                    'q'    : 'index',
                    'tags' : " ".join(tags),
                    'limit': limit,
                    'json' : 1
                }, return_json=True)
            except mido_utils.NotFoundError:
                if score > 1:
                    return await self._get_nsfw_dapi(dapi_name, tags, allow_video, score=score - 5, limit=limit)
                else:
                    raise mido_utils.NotFoundError

            for data in response_jsond:
                if dapi_name in ('gelbooru', 'sankaku_complex'):
                    image_url = data.get('file_url')
                    # sankaku can sometimes give null for file urls
                    if not image_url:
                        continue

                # elif dapi_name == 'sankaku_complex':
                #     image_url = data.get('sample_url')

                elif dapi_name == 'rule34':
                    image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"
                else:
                    raise Exception(f"Unknown DAPI name: {dapi_name}")

                if dapi_name == 'sankaku_complex':
                    image_tags = [x['name'] for x in data.get('tags')]
                else:
                    image_tags = data.get('tags').split(' ')

                if self.is_blacklisted(image_tags) or (not allow_video and self.is_video(image_url)):
                    continue
                else:
                    images.append(image_url)

            return images

    async def _get_danbooru(self, tags=None, allow_video=False, limit: int = 100):
        images = []

        response = await self._request_get(self.DAPI_LINKS['danbooru'], params={
            'limit' : limit,
            'tags'  : " ".join(tags),
            'random': 'true'
        }, return_json=True)

        if 'success' in response and response['success'] is False:
            raise mido_utils.NotFoundError

        for data in response:
            if ('file_url' not in data
                    or (not allow_video and self.is_video(data['file_url']))
                    or self.is_blacklisted(data['tag_string'].split())):
                continue

            images.append(data.get('large_file_url', data['file_url']))

        if not images:
            raise mido_utils.NotFoundError
        else:
            return images


class SomeRandomAPI(MidoBotAPI):
    URLs = {
        # animals
        "dog"      : "https://some-random-api.ml/img/dog",
        "cat"      : "https://some-random-api.ml/img/cat",
        "panda"    : "https://some-random-api.ml/img/panda",
        "fox"      : "https://some-random-api.ml/img/fox",
        "bird"     : "https://some-random-api.ml/img/birb",

        # shitposting
        "gay"      : "https://some-random-api.ml/canvas/gay",
        "wasted"   : "https://some-random-api.ml/canvas/wasted",

        "triggered": "https://some-random-api.ml/canvas/triggered",
        "youtube"  : "https://some-random-api.ml/canvas/youtube-comment",

        "meme"     : "https://some-random-api.ml/meme",  # shit memes
        "joke"     : "https://some-random-api.ml/joke",  # shit jokes

        # searches
        'lyrics'   : 'https://some-random-api.ml/lyrics',
        "pokemon"  : "https://some-random-api.ml/pokedex",
        "color"    : "https://some-random-api.ml/canvas/colorviewer"
    }

    class Pokemon:
        class Stats:
            def __init__(self, data: dict):
                self.hp: int = int(data.pop('hp'))
                self.attack: int = int(data.pop('attack'))
                self.defense: int = int(data.pop('defense'))
                self.sp_atk: int = int(data.pop('sp_atk'))
                self.sp_def: int = int(data.pop('sp_def'))
                self.speed: int = int(data.pop('speed'))
                self.total: int = int(data.pop('total'))

        def __init__(self, data: dict):
            self.name: str = data.pop('name')
            self.id: int = int(data.pop('id'))

            self.type: List[str] = data.pop('type')
            self.species: List[str] = data.pop('species')
            self.abilities: List[str] = data.pop('abilities')

            self.height: str = data.pop('height')
            self.weight: str = data.pop('weight')

            self.base_experience: int = int(data.pop('base_experience'))
            self.gender: List[str] = data.pop('gender')

            self.egg_groups: List[str] = data.pop('egg_groups')
            self.stats = self.Stats(data.pop('stats'))
            self.family: dict = data.pop('family')

            sprites = data.pop('sprites')
            self.static_image: str = sprites.pop('normal')
            self.animated_image: str = sprites.pop('animated')

            self.description: str = data.pop('description')
            self.generation: int = int(data.pop('generation'))

    def __init__(self, session: ClientSession):
        super(SomeRandomAPI, self).__init__(session)

    async def get_lyrics(self, title: str) -> Tuple[str, List[str], str]:
        response = await self._request_get(self.URLs['lyrics'], params={'title': title}, return_json=True)

        title = f"{response['author']} - {response['title']}"
        lyrics = self.parse_lyrics_for_discord(response['lyrics'])
        thumbnail = list(response['thumbnail'].values())[0]

        return title, lyrics, thumbnail

    async def get_animal(self, animal_name: str) -> str:
        response = await self._request_get(self.URLs[animal_name], return_json=True)
        return response['link']

    async def view_color(self, color: str):
        return await self._request_get(self.URLs['color'], params={'hex': color}, return_url=True)

    async def get_pokemon(self, pokemon_name: str) -> Pokemon:
        pokemon = await self._request_get(self.URLs["pokemon"], params={"pokemon": pokemon_name}, return_json=True)

        return self.Pokemon(pokemon)

    async def get_meme(self) -> str:
        response = await self._request_get(self.URLs["meme"], return_json=True)
        return response['image']

    async def get_joke(self) -> str:
        response = await self._request_get(self.URLs["joke"], return_json=True)
        return response['joke']

    async def wasted_gay_or_triggered(self, avatar_url: str, _type: str = "wasted") -> str:
        return await self._request_get(self.URLs[_type], params={'avatar': avatar_url}, return_url=True)

    async def youtube_comment(self, avatar_url: str, username: str, comment: str):
        return await self._request_get(self.URLs["youtube"], params={'avatar'  : avatar_url,
                                                                     "username": username,
                                                                     "comment" : comment,
                                                                     "dark"    : 'true'},
                                       return_url=True)

    @staticmethod
    def parse_lyrics_for_discord(lyrics: str) -> List[str]:
        def split_lyrics(_lyrics: str):
            pages = []

            lyric_list = _lyrics.split('\n\n')

            temp_page = ""
            for paragraph in lyric_list:
                if len(temp_page) + len(paragraph) > 2000:
                    pages.append(temp_page)
                    temp_page = paragraph
                else:
                    temp_page += '\n\n' + paragraph

            pages.append(temp_page)

            return pages

        lyrics = lyrics.replace('[', '**[').replace(']', ']**')
        if len(lyrics) > 2000:
            lyrics_pages = split_lyrics(lyrics)
        else:
            lyrics_pages = [lyrics]

        return lyrics_pages


class Google(MidoBotAPI):
    class SearchResult:
        def __init__(self, title, url, description):
            self.title = title
            self.url = url
            self.description = description

        @property
        def url_simple(self):
            simple = '/'.join(self.url.split('/')[2:])

            # if there's a slash at the end, remove it for clarity
            if simple[-1] == '/':
                simple = simple[:-1]

            # if its too long, cut it and add 3 dots to the end
            if len(simple) > 63:
                simple = simple[:60] + '...'

            return simple

        def __str__(self):
            return str(self.__dict__)

        def __repr__(self):
            return self.__str__()

    def __init__(self, session: ClientSession):
        super(Google, self).__init__(session)

    async def search(self, query: str):
        async with self.session.get(f"https://google.com/search?q={query}&hl=en") as r:
            if r.status == 200:
                soup = BeautifulSoup(await r.text(), "html.parser")

                return self.parse_results(soup.find_all("div", {'class': ['r', 's']}))

            else:
                raise mido_utils.APIError

    def parse_results(self, results):
        actual_results = []

        # migrate the r and s classes
        for i in range(0, len(results), 2):
            try:
                r = next(results[i].children)
                s = None

                # find the span
                for children in results[i + 1].children:
                    try:
                        if children.span:
                            s = children
                            break
                    except AttributeError:
                        pass

                if not s:  # its probably a book or something at this point
                    continue
                else:
                    actual_results.append((r, s))

            except IndexError:
                break

        search_results = []

        for main, description in actual_results:
            try:
                url = main["href"]
                title = next(main.stripped_strings)
                description = description.span.get_text()
                if not title:
                    continue

            except KeyError:
                continue

            else:
                search_results.append(self.SearchResult(title, url, description))

        return search_results


class OAuthAPI(MidoBotAPI):
    # noinspection PyTypeChecker
    def __init__(self, session: ClientSession, credentials: dict):
        super().__init__(session)

        self.url_to_get_token = None

        self.client_id: str = credentials.get('client_id')
        self.client_secret: str = credentials.get('client_secret')

        self.token: str = None
        self.token_type: str = None
        self.expire_date: mido_utils.Time = None

    @property
    def auth_header(self):
        return {'Authorization': f'{self.token_type.title()} {self.token}'}

    async def _request_get(self, link: str, *args, **kwargs) -> Union[str, dict, ClientResponse]:
        """This overwrites the base method"""
        if not self.token or self.expire_date.end_date_has_passed:
            await self.get_token()

        return await super()._request_get(link, headers=self.auth_header, *args, **kwargs)

    async def get_token(self):
        param = {'grant_type': 'client_credentials'}

        base_64 = base64.b64encode(
            f'{self.client_id}:{self.client_secret}'.encode('ascii'))

        header = {'Authorization': f'Basic {base_64.decode("ascii")}'}

        async with self.session.post(self.url_to_get_token, data=param, headers=header) as r:
            token_dict = await r.json()

            self.token = token_dict['access_token']
            self.token_type = token_dict['token_type']
            self.expire_date = mido_utils.Time.add_to_current_date_and_get(token_dict['expires_in'])


class SpotifyAPI(OAuthAPI):
    API_URL = "https://api.spotify.com/v1"

    # noinspection PyTypeChecker
    def __init__(self, session: ClientSession, credentials: dict):
        super().__init__(session, credentials)

        self.url_to_get_token = 'https://accounts.spotify.com/api/token'

    async def _pagination_get(self, url, params, **kwargs):
        first_page = await self._request_get(url, params, **kwargs)
        yield first_page

        if 'tracks' in first_page and 'next' in first_page['tracks']:
            next_page_url = first_page['tracks']['next']
            while next_page_url:
                next_page_content = await self._request_get(next_page_url, params, **kwargs)
                yield next_page_content
                next_page_url = next_page_content['next']

    async def get_songs(self, ctx, url: str) -> List[mido_utils.BaseSong]:
        def track_or_item(item):
            return item['track'] if 'track' in item else item

        url_type = url.split('/')[3]
        _id = url.split('/')[-1]

        # remove the 'si' tag if its an artist
        # because spotify api gives no tracks if si exists
        if url_type == 'artist':
            _id = _id.split('?')[0]

        # provide a market if 'si' param does not exist in the id or its an artist
        params = {'market': 'DE'} if '?si=' not in _id else None

        if url_type in ('track', 'playlist', 'album', 'artist'):
            url_type += 's'
        else:
            raise mido_utils.InvalidURL("Invalid Spotify URL. Please specify a playlist, track, album or artist link.")

        if url_type == 'artists':
            extra_query = 'top-tracks'
        elif url_type == 'tracks':
            extra_query = ''
        else:
            extra_query = 'tracks'

        request_url = f'{self.API_URL}/{url_type}/{_id}/{extra_query}'
        responses = self._pagination_get(request_url, params=params, return_json=True)

        track_list = []
        async for response in responses:
            if 'tracks' in response:
                if 'items' in response['tracks']:
                    track_list.extend([track_or_item(track) for track in response['tracks']['items']])
                else:
                    track_list.extend([track_or_item(track) for track in response['tracks']])
            elif 'items' in response:
                track_list.extend([track_or_item(track) for track in response['items']])
            else:
                track_list.extend([response])

        return [mido_utils.BaseSong.convert_from_spotify_track(ctx, track) for track in track_list if track is not None]


class BlizzardAPI(OAuthAPI):
    API_URL = "https://eu.api.blizzard.com"

    def __init__(self, session: ClientSession, credentials: dict):
        super().__init__(session, credentials)

        self.url_to_get_token = "https://eu.battle.net/oauth/token"

    async def get_hearthstone_card(self, keyword: str = None) -> HearthstoneCard:
        if keyword:
            r = await self._request_get(f'{self.API_URL}/hearthstone/cards',
                                        params={"locale"    : "en_US",
                                                "textFilter": keyword,
                                                "pageSize"  : 1},
                                        return_json=True)
            if not r['cards']:
                r = await self._request_get(f'{self.API_URL}/hearthstone/cards',
                                            params={"locale"  : "en_US",
                                                    "keyword" : keyword,
                                                    "pageSize": 1},
                                            return_json=True)
        else:  # get random
            r = await self._request_get(f'{self.API_URL}/hearthstone/cards',
                                        params={"locale"  : "en_US",
                                                "pageSize": 1,
                                                "page"    : random.randint(1, 2710)  # total amount of cards
                                                },
                                        return_json=True)

        cards = r['cards']
        if not cards:
            raise mido_utils.NotFoundError

        return HearthstoneCard(cards[0])  # get the first result
