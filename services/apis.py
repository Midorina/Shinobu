import json
import random

import aiohttp
from asyncpg.pool import Pool


class NotFoundError(Exception):
    pass


# TODO: make use of the cache for real in the future.


class CachedAPI:
    def __init__(self, db: Pool):
        self.db = db

    async def add_to_db(self, api_name: str, url: str) -> None:
        await self.db.execute("""INSERT INTO api_cache(api_name, url) VALUES ($1, $2) ON CONFLICT DO NOTHING;""",
                              api_name, url)


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

        else:
            raise Exception

        try:
            fetched_img = await func(*args)
        except Exception as e:
            raise e
        else:
            await self.add_to_db(nsfw_type, fetched_img)
            return fetched_img

    def _clean_tags(self, tags):
        cleaned_tags = []
        for tag in tags:
            tag = tag.replace(' ', '_').lower()
            if tag.lower() not in self.blacklisted_tags:
                cleaned_tags.append(tag)

        return cleaned_tags

    @staticmethod
    async def _get_boobs_or_butts(_type='boobs') -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://api.o{_type}.ru/noise/1/') as r:
                if r.status == 200:
                    data = await r.json()
                    return f"http://media.o{_type}.ru/" + data[0]['preview']
                else:
                    raise Exception('Couldn\t fetch image. Please try again later.')

    async def _get_nsfw_dapi(self, dapi='rule34', tags=None) -> str:
        tags = self._clean_tags(tags)
        max_range = 200 if dapi == 'gelbooru' else 2000

        async with aiohttp.ClientSession() as session:
            while True:
                rand_page = random.randrange(max_range) if max_range else 0

                async with session.get(self.dapi_links[dapi], params={
                    'page': 'dapi',
                    's': 'post',
                    'q': 'index',
                    'tags': "+".join(tags),
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

                        data = random.choice(filtered)

                        image_url = data.get('file_url')
                        image_tags = data.get('tags').split(' ')

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

                        data = random.choice(filtered)
                        image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"
                        image_tags = data.get('tags').split(' ')

                    # check if it contains a blacklisted tag
                    blacklisted = False
                    for tag in image_tags:
                        if tag in self.blacklisted_tags:
                            blacklisted = True
                            break

                    if blacklisted:
                        continue
                    else:
                        return image_url
