import base64
import json
import random
from typing import List, Tuple

from aiohttp import ClientSession
from asyncpg.pool import Pool
from bs4 import BeautifulSoup

from services.exceptions import InvalidURL, NotFoundError
from services.time_stuff import MidoTime


# TODO: make use of the cache for real in the future.

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

    async def add_to_db(self, api_name: str, urls: List[str]) -> None:
        if urls:
            await self.db.executemany(
                """INSERT INTO api_cache(api_name, url) VALUES ($1, $2) ON CONFLICT DO NOTHING;""",
                [(api_name, url) for url in urls])


class NSFWAPIs(CachedImageAPI):
    blacklisted_tags = [
        'loli',
        'shota',
        'child',
        'guro',
        'blood',
        'gore',
        'flat_chest'
    ]

    dapi_links = {
        'danbooru': 'https://danbooru.donmai.us/posts.json',
        'gelbooru': 'https://gelbooru.com/index.php',
        'rule34': 'https://rule34.xxx/index.php'
    }

    def __init__(self, session: ClientSession, db: Pool):
        super(NSFWAPIs, self).__init__(session, db)

    async def get(self, nsfw_type: str, tags=None):
        if nsfw_type in ('butts', 'boobs'):
            func = self._get_boobs_or_butts
            args = [nsfw_type]
        elif nsfw_type in ('rule34', 'gelbooru'):
            func = self._get_nsfw_dapi
            args = [nsfw_type, tags]

        elif nsfw_type == 'danbooru':
            func = self._get_danbooru
            args = [tags]

        else:
            raise Exception

        fetched_imgs = await func(*args)

        await self.add_to_db(nsfw_type, fetched_imgs)
        return random.choice(fetched_imgs)

    def _clean_tags(self, tags):
        cleaned_tags = []
        for tag in tags:
            tag = tag.replace(' ', '_').lower()
            if tag.lower() not in self.blacklisted_tags:
                cleaned_tags.append(tag)

        return cleaned_tags

    def is_blacklisted(self, tags):
        for tag in tags:
            if tag in self.blacklisted_tags:
                return True
        return False

    async def _get_boobs_or_butts(self, _type='boobs') -> List[str]:
        async with self.session.get(f'http://api.o{_type}.ru/noise/100/') as r:
            if r.status == 200:
                data = await r.json()
                return [f"http://media.o{_type}.ru/" + image['preview'] for image in data]
            else:
                raise Exception("Couldn't fetch image. Please try again later.")

    async def _get_nsfw_dapi(self, dapi='rule34', tags=None) -> List[str]:
        images = []

        tags = self._clean_tags(tags)
        max_range = 200 if dapi == 'gelbooru' else 2000

        while True:
            rand_page = random.randrange(max_range) if max_range else 0

            async with self.session.get(self.dapi_links[dapi], params={
                'page' : 'dapi',
                's'    : 'post',
                'q'    : 'index',
                'tags' : " ".join(tags),
                'limit': 100,
                'json' : 1,
                'pid'  : rand_page,
                # **self.bot.config['gelbooru_credentials']
            }) as response:
                # lower the range
                max_range = rand_page

                if dapi == 'gelbooru':
                    response_jsond = await response.json() or []
                    filtered = list(filter(
                        lambda x: x['rating'] != 's' and not x['file_url'].endswith('.webm'),
                        response_jsond))

                    if not filtered:
                        # if we're at the last page
                        if rand_page == 0:
                            raise NotFoundError
                        else:
                            continue

                    for data in filtered:
                        image_url = data.get('file_url')
                        image_tags = data.get('tags').split(' ')
                        if self.is_blacklisted(image_tags):
                            continue
                        else:
                            images.append(image_url)

                elif dapi == 'rule34':
                    r = await response.text()

                    if not r:
                        raise NotFoundError

                    response_jsond = json.loads(r)
                    filtered = list(filter(
                        lambda x: not x['image'].endswith('.webm'),
                        response_jsond))

                    if not filtered:
                        # if we're at the last page
                        if rand_page == 0:
                            raise NotFoundError
                        else:
                            continue

                    for data in filtered:
                        image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"
                        image_tags = data.get('tags').split(' ')
                        if self.is_blacklisted(image_tags):
                            continue
                        else:
                            images.append(image_url)

                return images

    async def _get_danbooru(self, tags=None):
        images = []

        if tags:
            params = {
                'limit': 200,
                'tags': " ".join(tags)
            }
        else:
            params = {
                'limit' : 200,
                'random': 'true'
            }

        async with self.session.get(self.dapi_links['danbooru'], params=params) as r:
            response = await r.json()

            for data in response:
                if 'file_url' not in data.keys() \
                        or data['rating'] == 's' \
                        or data['file_url'].endswith('.webm') \
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

    async def get_lyrics(self, title: str) -> Tuple[str, List[str], str]:
        async with self.session.get(self.URLs['lyrics'], params={'title': title}) as r:
            response = await r.json()

            if 'error' in response:
                raise NotFoundError

            title = f"{response['author']} - {response['title']}"
            lyrics = self.parse_lyrics_for_discord(response['lyrics'])
            thumbnail = list(response['thumbnail'].values())[0]

            return title, lyrics, thumbnail


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
