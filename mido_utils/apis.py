from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

import aiohttp
import asyncpraw
import asyncprawcore
from aiohttp import ClientResponse, ClientSession
from asyncpg.pool import Pool
from bs4 import BeautifulSoup

import mido_utils
import models

__all__ = ['MidoBotAPI', 'NekosLifeAPI', 'RedditAPI', 'NsfwDAPIs', 'SomeRandomAPI', 'Google', 'SpotifyAPI',
           'BlizzardAPI',
           'ExchangeAPI', 'PatreonAPI']

if TYPE_CHECKING:
    from shinobu import ShinobuBot


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
    async def get_aiohttp_session(cls) -> ClientSession:
        return ClientSession(headers=cls.DEFAULT_HEADERS,
                             connector=aiohttp.TCPConnector(limit=0),
                             timeout=aiohttp.ClientTimeout(total=15))

    async def _request_get(self,
                           url: str,
                           params: dict = None,
                           headers: dict = None,
                           return_url=False,
                           return_json=False,
                           return_text=False) -> str | dict | ClientResponse:
        try:
            async with self.session.get(url=url, params=params, headers=headers) as response:
                if not response.status == 200:
                    if response.status == 404:
                        raise mido_utils.NotFoundError(f"404 for URL: {response.url}")
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
                        raise mido_utils.NotFoundError(f"{response.url} returned an empty response.")
                    elif 'error' in js:
                        raise mido_utils.RateLimited(f"{response.url} responded with error: {js['error']}")

                    return js

                elif return_text is True:
                    return await response.text()
                else:
                    return response

        except (aiohttp.ServerDisconnectedError, asyncio.TimeoutError, aiohttp.ClientConnectorError) as e:
            raise mido_utils.APIError(f"An error occurred while trying to make a GET request to {url}: "
                                      f"{e.__name__ if hasattr(e, '__name__') else e}")


class CachedImageAPI(MidoBotAPI):
    def __init__(self, session: ClientSession, db: Pool):
        super().__init__(session)

        self.db = db

    async def add_to_db(self, api_name: str, urls: list[str], tags: list[str] = None) -> None:
        if tags is None:
            tags = []

        if urls:
            await self.db.executemany(
                """INSERT INTO api_cache(api_name, url, tags) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING;""",
                ((api_name, url, tags) for url in urls)
            )


class NekosLifeAPI(CachedImageAPI):
    # 03.05.2022 NSFW tags have been removed from NekosLifeAPI. reason unknown.
    BASE_URL = 'https://nekos.life/api/v2'
    NOT_FOUND_URL = 'https://cdn.nekos.life/smallboobs/404.png'

    NSFW_NEKO_TAGS = ['nsfw_neko_gif', 'eron']
    SFW_NEKO_TAGS = ['ngif', 'neko']

    def __init__(self, session: ClientSession, db: Pool):
        super().__init__(session=session, db=db)

    async def get_image(self, tag: str) -> models.NSFWImage:
        tag = tag.lower()
        if tag not in self.NSFW_NEKO_TAGS and tag not in self.SFW_NEKO_TAGS:
            raise mido_utils.APIError('Unknown tag!')

        while True:
            ret = await self._request_get(url=f'{self.BASE_URL}/img/{tag}', return_json=True)

            url = ret['url']

            if url == self.NOT_FOUND_URL:
                continue

            # await self.add_to_db(api_name="Nekos.Life", urls=[ret['url']], tags=[tag])
            return models.NSFWImage(url=url, tags=[tag.title()], api_name='Nekos.Life')

    async def get_random_neko(self, nsfw=False):
        if nsfw is True:
            tags = self.NSFW_NEKO_TAGS
        else:
            tags = self.SFW_NEKO_TAGS

        return await self.get_image(tag=random.choice(tags))


class RedditAPI(CachedImageAPI):
    def __init__(self, credentials: dict, session: ClientSession, db: Pool):
        super().__init__(session, db)

        if credentials:
            self.reddit = asyncpraw.Reddit(
                **credentials,
                user_agent=MidoBotAPI.USER_AGENT,
                requestor_kwargs={"session": self.session}
            )

    @staticmethod
    def parse_gfycat_to_red_gif(urls: list[str]):
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
                    for word_type, word_list in mido_utils.strings.gfycat_words.items():
                        word_list = sorted(word_list, key=lambda x: len(x), reverse=True)
                        for word in word_list:
                            if word in _id:
                                # check if it's replacing an already replaced word
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
        if not hasattr(self, 'reddit'):
            raise mido_utils.IncompleteConfigFile("Reddit credentials are not set, thus I can't pull from Reddit.")

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
                await asyncio.sleep(3)

        except asyncprawcore.ResponseException as e:
            if e.response.status in [404, 451]:
                logging.warning(
                    f"Got {e.response.status} while fetching images from {subreddit_name} "
                    f"with category: {submission_category}. Returning silently.")
                return

            logging.error(f"{e} from Reddit. You most likely entered wrong credentials.")
            raise

        except (asyncprawcore.NotFound, asyncprawcore.Forbidden, asyncprawcore.ServerError) as e:
            logging.error(f"Subreddit '{subreddit_name}' caused error: {e}")
            raise

        urls = self.parse_gfycat_to_red_gif(urls)

        await self.add_to_db(api_name=f'reddit_{subreddit_name}',
                             urls=urls,
                             tags=[subreddit_name])

    @staticmethod
    async def get_reddit_post_from_db(bot,
                                      category: str,
                                      tags: list[str] = None,
                                      limit: int = 1,
                                      allow_gif: bool = False) -> list[models.CachedImage]:
        subreddits = models.LocalSubreddit.get_with_related_tag(category=category, tags=tags)
        ret = await models.CachedImage.get_random(
            bot=bot,
            subreddits=subreddits,
            allow_gif=allow_gif,
            limit=limit)

        if not ret:
            raise mido_utils.IncompleteConfigFile(
                "Reddit cache in the database is empty. "
                "Please make sure you set up RedditAPI credentials properly in the config file "
                "(If you are sure that credentials are correct, please wait a bit for the database to be filled).")
        return ret

    async def fill_the_database(self, go_ham=False):
        # top
        # hot

        # all
        # year
        # month
        # week
        # day
        # hour
        all_subs = models.LocalSubreddit.get_all()
        random.shuffle(all_subs)

        for sub in all_subs:
            sub_name = sub.subreddit_name

            try:
                await self.get_images_from_subreddit(sub_name, 'top', 'day', limit=5)
                await self.get_images_from_subreddit(sub_name, 'hot', limit=1)

                if go_ham is True:
                    await self.get_images_from_subreddit(sub_name, 'top', 'all', limit=10000)
                    await self.get_images_from_subreddit(sub_name, 'top', 'year', limit=10000)
                    await self.get_images_from_subreddit(sub_name, 'top', 'month', limit=1000)
                    await self.get_images_from_subreddit(sub_name, 'top', 'week', limit=10)
            except Exception as e:
                logging.error(f"Error while fetching images from {sub_name}: {e}")
                continue

            finally:
                await asyncio.sleep(10.0)


class NsfwDAPIs(CachedImageAPI):
    class DAPI(Enum):
        danbooru = 'https://danbooru.donmai.us/posts.json'
        gelbooru = 'https://gelbooru.com/index.php'
        rule34 = 'https://rule34.xxx/index.php'
        sankaku_complex = 'https://capi-v2.sankakucomplex.com/posts'

        @property
        def url(self) -> str:
            return str(self.value)

        @classmethod
        def get_all_as_dict(cls) -> dict[str, str]:
            return {_dapi.name: _dapi.value for _dapi in cls if _dapi.name not in NsfwDAPIs.DISABLED}

        @classmethod
        def get_all(cls) -> list[NsfwDAPIs.DAPI]:
            return [_dapi for _dapi in cls if _dapi.name not in NsfwDAPIs.DISABLED]

    DISABLED = [DAPI.rule34.name]

    BLACKLISTED_TAGS = [
        'loli',
        'shota',
        'child',
        'kid',
        'underage',
        'guro',
        'blood',
        'gore',
        'flat_chest',
        'small breasts',
        'small nipples'
    ]

    def __init__(self, session: ClientSession, bot):
        super().__init__(session, bot.db)

        self.bot = bot

        self.danbooru_credentials = self.bot.config.danbooru_credentials
        self.gelbooru_credentials = self.bot.config.gelbooru_credentials

    async def get(
            self, nsfw_type: NsfwDAPIs.DAPI,
            tags: str = None,
            limit: int = 1,
            allow_video=True,
            guild_id: int = None
    ) -> list[models.NSFWImage]:
        tags = await self._parse_tags(tags, guild_id)

        # disabled score filtering for gelbooru due to rate limits
        # and Sankaku doesn't support score filtering
        score = 100 if nsfw_type is NsfwDAPIs.DAPI.rule34 else 0

        # compare names instead of objects due to importlib.reload bug
        if nsfw_type.name in (NsfwDAPIs.DAPI.rule34.name, NsfwDAPIs.DAPI.gelbooru.name):
            tags.extend(('rating:explicit', 'sort:random'))

            func = self._get_nsfw_dapi
            args = [nsfw_type, tags, allow_video, limit, score, guild_id]

        elif nsfw_type.name == NsfwDAPIs.DAPI.sankaku_complex.name:
            # max 5 args
            tags = [*tags[:3], 'rating:explicit', 'order:random']

            func = self._get_nsfw_dapi
            args = [nsfw_type, tags, allow_video, limit, score, guild_id]

        elif nsfw_type.name == NsfwDAPIs.DAPI.danbooru.name:
            # max 2 args
            tags = [tags[0], 'rating:explicit']

            func = self._get_danbooru
            args = [tags, allow_video, limit, guild_id]

        else:
            raise Exception(f"Unknown NSFW type: {nsfw_type}")

        try:
            fetched_images = await func(*args)

            if not fetched_images:
                raise mido_utils.NotFoundError
        except mido_utils.NotFoundError:  # suspend status.url message
            raise mido_utils.NotFoundError(f"Could not find any content with tags: {tags}")

        # await self.add_to_db(nsfw_type, fetched_images, tags=tags)

        try:
            return random.sample(fetched_images, limit)
        except ValueError:
            return fetched_images

    async def get_bomb(self, tags, limit=3, allow_video: bool = True, guild_id: int = None, return_all: bool = False) -> \
            list[models.NSFWImage]:
        dapi_links = self.DAPI.get_all()

        sample = limit if limit <= len(dapi_links) else len(dapi_links)

        images = []
        aws = []
        for dapi in random.sample(dapi_links, sample):
            aws.append(self.get(nsfw_type=dapi,
                                tags=tags,
                                limit=limit,
                                allow_video=allow_video,
                                guild_id=guild_id))

        for result in await asyncio.gather(*aws, return_exceptions=True):
            if isinstance(result, list):  # ignore exceptions
                images.extend(result)

        try:
            # raise same error as random.sample() would raise if "return_all" is requested
            # because it will be handled below
            if return_all:
                raise ValueError

            return random.sample(images, limit)
        except ValueError:
            if not images:
                raise mido_utils.NotFoundError

            return images

    async def get_blacklisted_tags(self, guild_id: int = None):
        if not guild_id:
            return self.BLACKLISTED_TAGS

        nsfw_db = await models.GuildNSFWDB.get_or_create(self.bot, guild_id)

        return nsfw_db.blacklisted_tags + self.BLACKLISTED_TAGS

    async def _parse_tags(self, tags: str, guild_id: int = None) -> list[str]:
        if tags is None:
            return []

        tags = tags.replace(' ', '_').lower().split('+')

        blacklisted_tags = await self.get_blacklisted_tags(guild_id)

        return list(filter(lambda x: x not in blacklisted_tags, tags))

    async def is_blacklisted(self, tags: list[str], guild_id: int = None):
        blacklisted_tags = await self.get_blacklisted_tags(guild_id)

        for tag in tags:
            if tag in blacklisted_tags:
                return True
        return False

    @staticmethod
    def is_video(url: str):
        return url.endswith('.webm') or url.endswith('.mp4')

    async def _get_nsfw_dapi(self,
                             dapi: NsfwDAPIs.DAPI,
                             tags: list[str],
                             allow_video: bool = True,
                             limit: int = 100,
                             score: int = 100,
                             guild_id: int = None) -> list[models.NSFWImage]:
        images: list[models.NSFWImage] = []

        if f'score:>={score}' in tags:
            pass
        else:
            for tag in tags:
                if tag.startswith('score'):
                    tags.remove(tag)

            if score > 0:
                tags.append(f'score:>={score}')

        if self.gelbooru_credentials and dapi is NsfwDAPIs.DAPI.gelbooru:
            key_params = {'api_key': self.gelbooru_credentials['api_key'],
                          'user_id': self.gelbooru_credentials['user_id']}
        else:
            key_params = {}

        # add tags that we don't want
        if dapi is not NsfwDAPIs.DAPI.sankaku_complex:
            tags.extend((f'-{_tag}' for _tag in await self.get_blacklisted_tags(guild_id)) if guild_id else ())

        try:
            response_jsond = await self._request_get(dapi.url, params={
                'page' : 'dapi',
                's'    : 'post',
                'q'    : 'index',
                'tags' : " ".join(tags),
                'limit': limit,
                'json' : 1,
                **key_params
            }, return_json=True)

        except mido_utils.NotFoundError:
            if score >= 10:
                return await self._get_nsfw_dapi(dapi, tags, allow_video, score=score - 10, limit=limit)
            else:
                raise mido_utils.NotFoundError

        if dapi is NsfwDAPIs.DAPI.gelbooru:
            if 'post' in response_jsond:
                response_jsond = response_jsond['post']
            else:
                raise mido_utils.NotFoundError

        for data in response_jsond:
            if dapi is NsfwDAPIs.DAPI.gelbooru or dapi is NsfwDAPIs.DAPI.sankaku_complex:
                image_url = data.get('file_url')
                # Sankaku can sometimes give null for file urls
                if not image_url:
                    continue

            elif dapi is NsfwDAPIs.DAPI.rule34:
                image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"
            else:
                raise Exception(f"Unknown DAPI: {dapi}")

            if dapi is NsfwDAPIs.DAPI.sankaku_complex:
                image_tags = [x['name'] for x in data.get('tags')]
            else:
                image_tags = data.get('tags').split(' ')

            if await self.is_blacklisted(image_tags, guild_id) or (not allow_video and self.is_video(image_url)):
                continue
            else:
                images.append(models.NSFWImage(image_url, tags=image_tags, api_name=dapi.name))

        if not images:
            raise mido_utils.NotFoundError

        return images

    async def _get_danbooru(self,
                            tags=None,
                            allow_video: bool = True,
                            limit: int = 100,
                            guild_id: int = None) -> list[models.NSFWImage]:
        if self.danbooru_credentials:
            key_params = {'api_key': self.danbooru_credentials['api_key'],
                          'login'  : self.danbooru_credentials['username']}
        else:
            key_params = {}

        images: list[models.NSFWImage] = []

        response: dict = await self._request_get(NsfwDAPIs.DAPI.danbooru.value, params={
            'limit' : limit,
            'tags'  : " ".join(tags),
            'random': 'true',
            **key_params
        }, return_json=True)

        if 'success' in response and response['success'] is False:
            raise mido_utils.NotFoundError

        # make it a list if it isn't
        # https://github.com/danbooru/danbooru/issues/4867
        response = [response] if isinstance(response, dict) else response

        for data in response:
            try:
                img_url = data.get('large_file_url', data['file_url'])
            except KeyError:
                # gold post (loli, shota, banned etc.)
                continue

            tags = data['tag_string'].split()

            if await self.is_blacklisted(tags, guild_id) or (not allow_video and self.is_video(img_url)):
                continue

            images.append(models.NSFWImage(img_url, tags, api_name=NsfwDAPIs.DAPI.danbooru.name))

        if not images:
            raise mido_utils.NotFoundError

        return images


class SomeRandomAPI(MidoBotAPI):
    URLs = {
        # animals
        "dog"      : "https://some-random-api.com/img/dog",
        "cat"      : "https://some-random-api.com/img/cat",
        "panda"    : "https://some-random-api.com/img/panda",
        "fox"      : "https://some-random-api.com/img/fox",
        "bird"     : "https://some-random-api.com/img/birb",

        # shitposting
        "gay"      : "https://some-random-api.com/canvas/gay",
        "wasted"   : "https://some-random-api.com/canvas/wasted",

        "triggered": "https://some-random-api.com/canvas/triggered",
        "youtube"  : "https://some-random-api.com/canvas/youtube-comment",

        "meme"     : "https://some-random-api.com/meme",  # shit memes
        "joke"     : "https://some-random-api.com/joke",  # shit jokes

        # searches
        'lyrics'   : 'https://some-random-api.com/lyrics',
        "pokemon"  : "https://some-random-api.com/pokedex",
        "color"    : "https://some-random-api.com/canvas/colorviewer"
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

            self.type: list[str] = data.pop('type')
            self.species: list[str] = data.pop('species')
            self.abilities: list[str] = data.pop('abilities')

            self.height: str = data.pop('height')
            self.weight: str = data.pop('weight')

            self.base_experience: int = int(data.pop('base_experience'))
            self.gender: list[str] = data.pop('gender')

            self.egg_groups: list[str] = data.pop('egg_groups')
            self.stats = self.Stats(data.pop('stats'))
            self.family: dict = data.pop('family')

            sprites = data.pop('sprites')
            self.static_image: str = sprites.pop('normal')
            self.animated_image: str = sprites.pop('animated')

            self.description: str = data.pop('description')
            self.generation: int = int(data.pop('generation'))

    def __init__(self, session: ClientSession):
        super().__init__(session)

    async def get_lyrics(self, title: str) -> tuple[str, list[str], str]:
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
        return await self._request_get(self.URLs["youtube"],
                                       params={'avatar'  : avatar_url,
                                               "username": username[:25],
                                               "comment" : comment,
                                               "dark"    : 'true'},
                                       return_url=True)

    @staticmethod
    def parse_lyrics_for_discord(lyrics: str) -> list[str]:
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
    LINK_AND_TITLE_CLASS = 'yuRUbf'
    DESCRIPTION_CLASS = 'IsZvec'

    class SearchResult:
        def __init__(self, title, url, description):
            self.title = title
            self.url = url
            self.description = description

        @property
        def url_simple(self):
            # remove http/https
            simple = '/'.join(self.url.split('/')[2:])

            # if there's a slash at the end, remove it for clarity
            if simple[-1] == '/':
                simple = simple[:-1]

            # if it's too long, cut it and add 3 dots to the end
            if len(simple) > 63:
                simple = simple[:60] + '...'

            return simple

        def __str__(self):
            return str(self.__dict__)

        def __repr__(self):
            return self.__str__()

    def __init__(self, session: ClientSession):
        super().__init__(session)

    async def search(self, query: str):
        async with self.session.get(f"https://google.com/search?q={query}&hl=en") as r:
            if r.status == 200:
                soup = BeautifulSoup(await r.text(), "html.parser")

                # FIXME this
                return self.parse_results(soup.find_all("div",
                                                        {'class': [self.LINK_AND_TITLE_CLASS, self.DESCRIPTION_CLASS]}))

            else:
                raise mido_utils.APIError

    def parse_results(self, results):
        links_and_titles = []
        descriptions = []

        # put results into respective arrays
        for result in results:
            if result['class'][0] == self.LINK_AND_TITLE_CLASS:
                links_and_titles.append(result)
            else:
                descriptions.append(result)

        ret = []
        # extract information
        for i, link_and_title in enumerate(links_and_titles):
            # url and title
            url = link_and_title.a['href']
            title = next(link_and_title.stripped_strings)

            # for descriptions, just use the longest one
            try:
                description = max(list(map(lambda x: x.get_text(), descriptions[i].find_all('span'))), key=len)
            except ValueError:
                # sometimes the description is there as a normal string instead of a span.
                # in that case, just use the string
                description = descriptions[i].string

            ret.append(self.SearchResult(title, url, description))

        return ret


class ExchangeAPI(MidoBotAPI):
    class Response:
        def __init__(self, data: dict):
            self.base: str = data.get('base')
            self.rates: dict = data.get('rates')
            self.updated = mido_utils.Time.from_timestamp(data.get('updated'))

    def __init__(self, session: ClientSession, api_key: str):
        super().__init__(session)

        self.api_key = api_key
        self.rate_cache: ExchangeAPI.Response | None = None

    @property
    def api_url(self) -> str:
        return "https://currencyapi.net/api/v1/rates"

    async def convert(self, amount: float, base_currency: str, target_currency: str) -> tuple[float, float]:
        """Converts any amount of currency to the other one and returns both the result and the exchange rate."""
        if not self.rate_cache or self.rate_cache.updated.passed_seconds > 60 * 60:
            await self.update_rate_cache()

        base_currency = base_currency.upper()
        target_currency = target_currency.upper()

        if base_currency not in self.rate_cache.rates.keys():
            raise mido_utils.UnknownCurrency(f'Base currency `{base_currency}` is unknown.')
        if target_currency not in self.rate_cache.rates.keys():
            raise mido_utils.UnknownCurrency(f'Target currency `{target_currency}` is unknown.')

        exchange_rate = self.rate_cache.rates[target_currency] / self.rate_cache.rates[base_currency]

        return exchange_rate * amount, exchange_rate

    async def update_rate_cache(self):
        try:
            if not self.api_key:
                raise mido_utils.APIError

            r = await self._request_get(url=self.api_url, params={'key': self.api_key}, return_json=True)
        except mido_utils.APIError:
            # probably the api key is invalid. update it :)
            try:
                r = await self._request_get(url='https://currencyapi.net/documentation#rates', return_text=True)
            except mido_utils.APIError:
                # even if this fails, we're either banned or the website is down
                return
            else:
                tag = BeautifulSoup(r, features="html.parser").find(
                    lambda _tag: _tag.name == 'a' and 'https://currencyapi.net/api/v1/rates?key=' in _tag.text)

                self.api_key = tag.attrs['href'].split('=')[-1]
                return await self.update_rate_cache()

        self.rate_cache = self.Response(r)


class OAuthAPI(MidoBotAPI):
    # noinspection PyTypeChecker
    def __init__(self, session: ClientSession, credentials: dict):
        super().__init__(session)

        self.client_id: str = credentials.get('client_id')
        self.client_secret: str = credentials.get('client_secret')

        self.token: str = None
        self.token_type: str = None
        self.expire_date: mido_utils.Time = None

    @property
    def token_grant_type(self) -> str:
        return 'client_credentials'

    @property
    def api_url(self) -> str:
        raise NotImplementedError

    @property
    def url_to_get_token(self) -> str:
        raise NotImplementedError

    @property
    def auth_header(self):
        return {'Authorization': f'{self.token_type.title()} {self.token}'}

    async def _request_get(self, link: str, *args, **kwargs) -> str | dict | ClientResponse:
        """This overwrites the base method"""
        if not self.token or self.expire_date.end_date_has_passed:
            await self.get_token()

        return await super()._request_get(link, headers=self.auth_header, *args, **kwargs)

    async def get_token(self):
        param = {'grant_type': self.token_grant_type}

        base_64 = base64.b64encode(
            f'{self.client_id}:{self.client_secret}'.encode('ascii'))

        header = {'Authorization': f'Basic {base_64.decode("ascii")}'}

        async with self.session.post(self.url_to_get_token, data=param, headers=header) as r:
            token_dict = await r.json()

            self.token = token_dict['access_token']
            self.token_type = token_dict['token_type']
            self.expire_date = mido_utils.Time.add_to_current_date_and_get(token_dict['expires_in'])


class SpotifyAPI(OAuthAPI):
    # noinspection PyTypeChecker
    def __init__(self, session: ClientSession, credentials: dict):
        super().__init__(session, credentials)

    @property
    def api_url(self) -> str:
        return "https://api.spotify.com/v1"

    @property
    def url_to_get_token(self) -> str:
        return 'https://accounts.spotify.com/api/token'

    async def _pagination_get(self, url, *args, **kwargs):
        first_page: dict = await self._request_get(url, *args, **kwargs)
        yield first_page

        if 'tracks' in first_page and 'next' in first_page['tracks']:
            next_page_url = first_page['tracks']['next']
            while next_page_url:
                next_page_content = await self._request_get(next_page_url, *args, **kwargs)
                yield next_page_content
                next_page_url = next_page_content['next']

    async def get_songs(self, ctx: mido_utils.Context, url: str) -> list[mido_utils.BaseSong]:
        def track_or_item(item):
            return item['track'] if 'track' in item else item

        if 'intl-' in url:  # if it's a spotify link with a country code (like intl-tr), skip it
            url_type = url.split('/')[4]
        else:
            url_type = url.split('/')[3]

        _id = url.split('/')[-1]

        # remove the 'si' tag if it's an artist
        # because spotify api gives no tracks if si exists
        if url_type == 'artist':
            _id = _id.split('?')[0]

        # provide a market if 'si' param does not exist in the id, or it's an artist
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

        request_url = f'{self.api_url}/{url_type}/{_id}/{extra_query}'
        responses = self._pagination_get(request_url, params=params, return_json=True)

        track_list = []
        async for response in responses:
            response: dict

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
    def __init__(self, session: ClientSession, credentials: dict):
        super().__init__(session, credentials)

    @property
    def api_url(self) -> str:
        return "https://eu.api.blizzard.com"

    @property
    def url_to_get_token(self) -> str:
        return "https://eu.battle.net/oauth/token"

    async def get_hearthstone_card(self, keyword: str = None) -> models.HearthstoneCard:
        if keyword:
            r: dict = await self._request_get(f'{self.api_url}/hearthstone/cards',
                                              params={"locale"    : "en_US",
                                                      "textFilter": keyword,
                                                      "pageSize"  : 1},
                                              return_json=True)
            if not r['cards']:
                r: dict = await self._request_get(f'{self.api_url}/hearthstone/cards',
                                                  params={"locale"  : "en_US",
                                                          "keyword" : keyword,
                                                          "pageSize": 1},
                                                  return_json=True)
        else:  # get random
            r: dict = await self._request_get(f'{self.api_url}/hearthstone/cards',
                                              params={"locale"  : "en_US",
                                                      "pageSize": 1,
                                                      "page"    : random.randint(1, 2710)  # total amount of cards
                                                      },
                                              return_json=True)

        cards = r['cards']
        if not cards:
            raise mido_utils.NotFoundError

        return models.HearthstoneCard(cards[0])  # get the first result


class PatreonAPI(OAuthAPI):
    def __init__(self, bot: ShinobuBot, credentials: dict):
        super().__init__(bot.http_session, credentials)

        self.bot = bot

        self.campaign_id = credentials.get('campaign_id')
        self.refresh_token = credentials.get('creator_refresh_token')

        # todo: get access token dynamically
        # we set these manually, because patreon api is confusing af.
        self.token = credentials.get('creator_access_token')
        self.token_type = 'Bearer'
        self.expire_date = mido_utils.Time(end_date=datetime.now(timezone.utc) + timedelta(days=30))

        self.cache: list[models.PatreonPledger] = []

        self.cache_task = self.bot.loop.create_task(self.refresh_patron_cache_loop())

    # async def get_token(self):
    #     param = {'grant_type': 'refresh_token',
    #              'refresh_token': self.refresh_token,
    #              'client_id': self.client_id,
    #              'client_secret': self.client_secret}
    #
    #     # base_64 = base64.b64encode(
    #     #     f'{self.client_id}:{self.client_secret}'.encode('ascii'))
    #     #
    #     # header = {'Authorization': f'Basic {base_64.decode("ascii")}'}
    #
    #     async with self.session.post(self.url_to_get_token, data=param) as r:
    #         print("made request. response:", r)
    #         token_dict = await r.json()
    #         print(token_dict)
    #
    #         self.token = token_dict['access_token']
    #         self.refresh_token = token_dict['refresh_token']
    #         self.expire_date = mido_utils.Time.add_to_current_date_and_get(token_dict['expires_in'])
    #         self.token_type = token_dict['token_type']
    #
    #         print("GOT TOKEN!!!", self.token)
    #         print(token_dict)

    @property
    def api_url(self) -> str:
        return "https://www.patreon.com/api/oauth2/v2"

    @property
    def url_to_get_token(self) -> str:
        return "https://www.patreon.com/api/oauth2/token"

    @property
    def url_to_get_code(self) -> str:
        return "https://www.patreon.com/oauth2/authorize"

    async def refresh_patron_cache_loop(self):
        await self.bot.wait_until_ready()

        while True:
            await self.refresh_patron_cache()
            await asyncio.sleep(60 * 30)  # sleep 30 minutes

    async def _pagination_get(self, url, **kwargs):
        first_page: dict = await self._request_get(url, **kwargs)
        yield first_page

        temp_page: dict = first_page
        while 'links' in temp_page and 'next' in temp_page['links']:
            temp_page = await self._request_get(temp_page['links']['next'], **kwargs)
            yield temp_page

    async def refresh_patron_cache(self) -> list[models.PatreonPledger]:
        # I fucking hate Patreon's API so fucking much.
        responses = self._pagination_get(
            f'{self.api_url}/campaigns/{self.campaign_id}/members'
            f'?include=user'
            f'&fields%5Buser%5D=social_connections'
            f'&fields%5Bmember%5D=patron_status,currently_entitled_amount_cents,full_name',
            return_json=True
        )

        ret: list[models.PatreonPledger] = []

        async for page in responses:
            page: dict
            active_pledgers = [x for x in page['data']
                               if x['type'] == 'member'
                               and x['attributes']['patron_status'] == 'active_patron']

            for active_pledger in active_pledgers:
                active_pledger_id = active_pledger['relationships']['user']['data']['id']
                active_pledger_full_name = active_pledger['attributes']['full_name']
                active_pledger_pledge_amount = active_pledger['attributes']['currently_entitled_amount_cents']
                active_pledger_discord_id = next(
                    (x['attributes']['social_connections']['discord']['user_id']
                     for x in page['included']
                     if x['id'] == active_pledger_id
                     and x['attributes']['social_connections']['discord'] is not None),
                    None
                )

                ret.append(
                    models.PatreonPledger(
                        active_pledger_full_name,
                        active_pledger_discord_id,
                        active_pledger_pledge_amount
                    )
                )

        self.cache = ret
        return ret

    def get_with_discord_id(self, discord_id: int) -> models.PatreonPledger | None:
        try:
            return next(x for x in self.cache if str(x.discord_id) == str(discord_id))
        except StopIteration:
            return None

    def is_patron_and_can_claim_daily(self, discord_id) -> bool:
        patron = self.get_with_discord_id(discord_id)
        if not patron or not patron.can_claim_daily_without_ads:
            return False

    def is_patron_and_can_use_music_premium(self, discord_id) -> bool:
        patron = self.get_with_discord_id(discord_id)
        if not patron or not patron.can_use_premium_music:
            return False
