import asyncio
import base64
import json
import math
import random
from typing import List, Tuple

import aiohttp
import asyncpraw
from aiohttp import ClientSession
from anekos import NSFWImageTags, NekosLifeClient, SFWImageTags
from anekos.client import Tag
from asyncpg.pool import Pool
from bs4 import BeautifulSoup

from models.db_models import CachedImage
from services.exceptions import InvalidURL, NotFoundError
from services.resources import Resources
from services.time_stuff import MidoTime


class MidoBotAPI:
    USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; WOW64) " \
                 "AppleWebKit/537.36 (KHTML, like Gecko) " \
                 "Chrome/ 58.0.3029.81 Safari/537.36"

    DEFAULT_HEADERS = {
        'User-Agent'     : USER_AGENT,
        "Accept-Language": "en-US,en;q=0.5",
    }

    def __init__(self, session: ClientSession):
        self.session = session

    @classmethod
    def get_aiohttp_session(cls):
        return ClientSession(headers=cls.DEFAULT_HEADERS)


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
                [(api_name, url, tags) for url in urls])


class NekoAPI(NekosLifeClient, CachedImageAPI):
    NSFW_NEKO_TAGS = [NSFWImageTags.NSFW_NEKO_GIF, NSFWImageTags.ERONEKO]
    SFW_NEKO_TAGS = [SFWImageTags.NEKOGIF, SFWImageTags.NEKO]

    def __init__(self, session: ClientSession, db: Pool):
        super().__init__(session=session)  # NekosLifeClient

        self.db = db  # CachedImageAPI

    async def image(self, tag: Tag, get_bytes: bool = False):
        while True:
            ret = await super(NekoAPI, self).image(tag, get_bytes)
            if ret.url == 'https://cdn.nekos.life/smallboobs/404.png':
                continue

            await self.add_to_db(api_name="nekos.life", urls=[ret.url], tags=[str(ret.tag)])
            return ret

    async def get_random_neko(self, nsfw=False):
        if nsfw is True:
            tags = self.NSFW_NEKO_TAGS
        else:
            tags = self.SFW_NEKO_TAGS

        return await self.image(tag=random.choice(tags))


class RedditAPI(CachedImageAPI):
    SUBREDDITS = {
        "boobs"  : [
            "boobs",
            "Boobies",
            "TittyDrop",
            "hugeboobs"
        ],
        "butts"  : [
            "ass",
            "bigasses",
            "pawg",
            "asstastic",
            "CuteLittleButts"
        ],
        "pussy"  : [
            "pussy",
            "LipsThatGrip",
            "GodPussy"
        ],
        "asian"  : [
            "AsianHotties",
            "juicyasians",
            "AsiansGoneWild"
        ],
        "general": [
            "gonewild",
            "nsfw",
            "RealGirls",
            "NSFW_GIF",
            "LegalTeens",
            "cumsluts",
            "BustyPetite",
            "holdthemoan",
            "PetiteGoneWild",
            "collegesluts",
            "porn",
            "GirlsFinishingTheJob",
            "adorableporn",
            "nsfw_gifs",
            "BiggerThanYouThought",
            "Amateur",
            "porninfifteenseconds",
            "milf",
            "OnOff",
            "JizzedToThis",
            "nsfwhardcore",
            "BreedingMaterial",
            "GWCouples",
            "lesbians",
            "porn_gifs",
            "anal",
            "Blowjobs"
        ],
        "hentai" : [
            "hentai",
            "rule34",
            "HENTAI_GIF",
            "ecchi",
            "yuri",
            "AnimeBooty"
        ]
    }

    def __init__(self, credentials: dict, session: ClientSession, db: Pool):
        super().__init__(session, db)

        self.reddit = asyncpraw.Reddit(
            **credentials,
            user_agent=MidoBotAPI.USER_AGENT
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
                    for word_type, word_list in Resources.strings.gfycat_words.items():
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
        async for submission in category(*args, **kwargs):
            urls.append(submission.url)

        urls = self.parse_gfycat_to_red_gif(urls)

        await self.add_to_db(api_name=f'reddit_{subreddit_name}',
                             urls=urls,
                             tags=[subreddit_name])

    async def get_from_the_db(self, category: str, redgif=False) -> CachedImage:
        if category not in self.SUBREDDITS:
            raise Exception(f"Invalid category: {category}")

        subreddit_names = [f'reddit_{sub}' for sub in self.SUBREDDITS[category]]

        return await CachedImage.get_random(self.db, subreddit_names, redgif)

    async def fill_the_database(self):
        async def _fill(sub_name: str):
            # top
            # hot

            # all
            # year
            # month
            # week
            # day
            # hour
            # await self.get_images_from_subreddit(sub_name, 'top', 'all', limit=10000)
            # await self.get_images_from_subreddit(sub_name, 'top', 'year', limit=10000)
            # await self.get_images_from_subreddit(sub_name, 'top', 'month', limit=1000)
            # await self.get_images_from_subreddit(sub_name, 'top', 'week', limit=10)
            await self.get_images_from_subreddit(sub_name, 'top', 'day', limit=5)
            await self.get_images_from_subreddit(sub_name, 'hot', limit=1)

        for sub_names in self.SUBREDDITS.values():
            for sub in sub_names:
                await _fill(sub)
                await asyncio.sleep(5.0)


class NSFW_DAPIs(CachedImageAPI):
    BLACKLISTED_TAGS = [
        'loli',
        'shota',
        'child',
        'guro',
        'blood',
        'gore',
        'flat_chest'
    ]

    DAPI_LINKS = {
        'danbooru': 'https://danbooru.donmai.us/posts.json',
        'gelbooru': 'https://gelbooru.com/index.php',
        'rule34'  : 'https://rule34.xxx/index.php'
    }

    def __init__(self, session: ClientSession, db: Pool):
        super(NSFW_DAPIs, self).__init__(session, db)

    async def get(self, nsfw_type: str, tags: str = None, limit: int = 1, allow_video=False) -> List[str]:
        tags = self._parse_tags(tags)

        if nsfw_type in ('rule34', 'gelbooru'):
            func = self._get_nsfw_dapi
            args = [nsfw_type, tags, allow_video]

        elif nsfw_type == 'danbooru':
            func = self._get_danbooru
            args = [tags, allow_video]

        else:
            raise Exception(f"Unknown nsfw type: {nsfw_type}")

        fetched_imgs = await func(*args)

        await self.add_to_db(nsfw_type, fetched_imgs, tags=tags)

        try:
            return random.sample(fetched_imgs, limit)
        except ValueError:
            return fetched_imgs

    async def get_bomb(self, tags, limit=3) -> List[str]:
        urls = []
        limit = math.floor(limit / len(self.DAPI_LINKS.keys()))

        for dapi in self.DAPI_LINKS.keys():
            try:
                urls.extend(await self.get(dapi, tags, limit=limit, allow_video=True))
            except NotFoundError:
                pass

        return urls

    def _parse_tags(self, tags: str):
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

    async def _get_nsfw_dapi(self, dapi='rule34', tags=None, allow_video=False, score: int = 10) -> List[str]:
        images = []

        tags.extend(('rating:explicit', 'sort:random', f'score:>={10}'))

        while True:
            async with self.session.get(self.DAPI_LINKS[dapi], params={
                'page' : 'dapi',
                's'    : 'post',
                'q'    : 'index',
                'tags' : " ".join(tags),
                'limit': 100,
                'json' : 1
            }) as response:
                try:
                    response_jsond = await response.json() or []
                except aiohttp.ContentTypeError:
                    response_jsond = json.loads(await response.read())

                if not response_jsond:
                    if score > 1:
                        return await self._get_nsfw_dapi(dapi, tags, allow_video, score=score - 1)
                    else:
                        raise NotFoundError

                for data in response_jsond:
                    if dapi == 'gelbooru':
                        image_url = data.get('file_url')
                    elif dapi == 'rule34':
                        image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"

                    image_tags = data.get('tags').split(' ')
                    if self.is_blacklisted(image_tags) or (not allow_video and self.is_video(image_url)):
                        continue
                    else:
                        images.append(image_url)

                return images

    async def _get_danbooru(self, tags=None, allow_video=False):
        images = []

        tags.extend(('rating:explicit', f'score:>={10}'))

        async with self.session.get(self.DAPI_LINKS['danbooru'], params={
            'limit' : 100,
            'tags'  : " ".join(tags),
            'random': 'true'
        }) as r:
            response = await r.json()

            for data in response:
                if (not allow_video and self.is_video(data['file_url'])) \
                        or self.is_blacklisted(data['tag_string'].split()):
                    continue

                images.append(data.get('large_file_url', data['file_url']))

            if not images:
                raise NotFoundError
            else:
                return images


class SpotifyAPI(MidoBotAPI):
    # noinspection PyTypeChecker
    def __init__(self, session: ClientSession, credentials: dict):
        super(SpotifyAPI, self).__init__(session)

        self.client_id: str = credentials.get('client_id')
        self.client_secret: str = credentials.get('client_secret')

        self.token: str = None
        self.token_type: str = None
        self.expire_date: MidoTime = None

    @property
    def auth_header(self):
        return {'Authorization': f'{self.token_type.title()} {self.token}'}

    @staticmethod
    def get_search_query_from_track_obj(track: dict):
        query = ", ".join(artist['name'] for artist in track['artists'])
        query += f" - {track['name']}"

        return query

    async def _request(self, link: str) -> dict:
        if not self.token or self.expire_date.end_date_has_passed:
            await self.get_token()

        async with self.session.get(link, headers=self.auth_header) as r:
            return await r.json()

    async def get_token(self):
        param = {'grant_type': 'client_credentials'}

        base_64 = base64.b64encode(
            f'{self.client_id}:{self.client_secret}'.encode('ascii'))

        header = {'Authorization': f'Basic {base_64.decode("ascii")}'}

        async with self.session.post('https://accounts.spotify.com/api/token', data=param, headers=header) as r:
            token_dict = await r.json()

            self.token = token_dict['access_token']
            self.token_type = token_dict['token_type']
            self.expire_date = MidoTime.add_to_current_date_and_get(token_dict['expires_in'])

    async def get_song_names(self, url: str):
        url_type = url.split('/')[3]
        _id = url.split('/')[-1]

        if url_type in ('track', 'playlist', 'album'):
            url_type += 's'
        else:
            raise InvalidURL

        response = await self._request(f'https://api.spotify.com/v1/{url_type}/{_id}')

        if url_type == 'tracks':
            track_list = [response]
        elif url_type == 'albums':
            track_list = response['tracks']['items']
        elif url_type == 'playlists':
            track_list = [item['track'] for item in response['tracks']['items']]
        else:
            raise InvalidURL

        return [self.get_search_query_from_track_obj(track) for track in track_list]


class SomeRandomAPI(MidoBotAPI):
    URLs = {
        'lyrics': 'https://some-random-api.ml/lyrics'
    }

    def __init__(self, session: ClientSession):
        super(SomeRandomAPI, self).__init__(session)

    async def get_lyrics(self, title: str) -> Tuple[str, List[str], str]:
        async with self.session.get(self.URLs['lyrics'], params={'title': title}) as r:
            response = await r.json()

            if 'error' in response:
                raise NotFoundError

            title = f"{response['author']} - {response['title']}"
            lyrics = self.parse_lyrics_for_discord(response['lyrics'])
            thumbnail = list(response['thumbnail'].values())[0]

            return title, lyrics, thumbnail

    @staticmethod
    def split_lyrics(lyrics: str):
        pages = []

        lyric_list = lyrics.split('\n\n')

        temp_page = ""
        for paragraph in lyric_list:
            if len(temp_page) + len(paragraph) > 2000:
                pages.append(temp_page)
                temp_page = paragraph
            else:
                temp_page += '\n\n' + paragraph

        pages.append(temp_page)

        return pages

    def parse_lyrics_for_discord(self, lyrics: str) -> List[str]:
        lyrics = lyrics.replace('[', '**[').replace(']', ']**')
        if len(lyrics) > 2000:
            lyrics_pages = self.split_lyrics(lyrics)
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
        async with self.session.get(f"https://www.google.com/search?q={query}&hl=en") as r:
            if r.status == 200:
                soup = BeautifulSoup(await r.read(), "lxml")
                return self.parse_results(soup.find_all("div", {'class': ['r', 's']}))

            else:
                raise Exception('There has been an error. Please try again later.')

    def parse_results(self, results):
        actual_results = []

        # migrate the r and s classes
        for i in range(0, len(results), 2):
            try:
                r = next(results[i].children)
                s = None

                # find the span
                for children in results[i + 1].children:
                    if children.span:
                        s = children
                        break

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
