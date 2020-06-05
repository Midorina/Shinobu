import json
import random
from typing import List

import aiohttp
from asyncpg.pool import Pool

from services.exceptions import NotFoundError


# TODO: make use of the cache for real in the future.


class CachedAPI:
    def __init__(self, db: Pool):
        self.db = db

    async def add_to_db(self, api_name: str, urls: List[str]) -> None:
        if urls:
            await self.db.executemany(
                """INSERT INTO api_cache(api_name, url) VALUES ($1, $2) ON CONFLICT DO NOTHING;""",
                [(api_name, url) for url in urls])


class NSFWAPIs(CachedAPI):
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

    def __init__(self, db: Pool):
        super(NSFWAPIs, self).__init__(db)

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

    @staticmethod
    async def _get_boobs_or_butts(_type='boobs') -> List[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://api.o{_type}.ru/noise/100/') as r:
                if r.status == 200:
                    data = await r.json()
                    return [f"http://media.o{_type}.ru/" + image['preview'] for image in data]
                else:
                    raise Exception('Couldn\t fetch image. Please try again later.')

    async def _get_nsfw_dapi(self, dapi='rule34', tags=None) -> List[str]:
        images = []

        tags = self._clean_tags(tags)
        max_range = 200 if dapi == 'gelbooru' else 2000

        async with aiohttp.ClientSession() as session:
            while True:
                rand_page = random.randrange(max_range) if max_range else 0

                async with session.get(self.dapi_links[dapi], params={
                    'page': 'dapi',
                    's': 'post',
                    'q': 'index',
                    'tags': " ".join(tags),
                    'limit': 100,
                    'json': 1,
                    'pid': rand_page,
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
                'limit': 200,
                'random': 'true'
            }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.dapi_links['danbooru'], params=params) as r:
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
