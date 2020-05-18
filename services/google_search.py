import aiohttp
from bs4 import BeautifulSoup


class Google:
    USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/ 58.0.3029.81 Safari/537.36"
    DEFAULT_HEADERS = {
        'User-Agent': USER_AGENT,
        "Accept-Language": "en-US,en;q=0.5",
    }

    async def search(self, query: str):
        async with aiohttp.ClientSession(headers=self.DEFAULT_HEADERS) as session:

            async with session.get(f"https://www.google.com/search?q={query}&hl=en") as r:

                if r.status == 200:
                    soup = BeautifulSoup(await r.read(), "lxml")
                    return self.parse_results(soup.find_all("div", {'class': ['r', 's']}))

                else:
                    raise Exception('There has been an error. Please try again later.')

    @staticmethod
    def parse_results(results):
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
                search_results.append(SearchResult(title, url, description))

        return search_results


class SearchResult:
    def __init__(self, title, url, description):
        self.title = title
        self.url = url
        self.description = description

    @property
    def url_simple(self):
        simple = '/'.join(self.url.split('/')[2:])

        # if its too long, cut it and add 3 dots to the end
        if len(simple) > 60:
            simple = simple[:60] + '...'

        return simple

    def __str__(self):
        return str(self.__dict__)

    def __repr__(self):
        return self.__str__()
