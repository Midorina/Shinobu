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
                    return self.parse_results(soup.select(".r a"))
                else:
                    raise Exception('There has been an error. Please try again later.')

    @staticmethod
    def parse_results(results):
        search_results = []

        for result in results:

            if 'class' in result.attrs:
                if 'l' not in result['class']:
                    continue

            url = result["href"]
            title = next(result.stripped_strings)
            if not title:
                continue

            search_results.append(SearchResult(title, url))

        return search_results


class SearchResult:
    def __init__(self, title, url):
        self.title = title
        self.url = url
        self.__text = None
        self.__markup = None

    # def getText(self):
    #     if self.__text is None:
    #         soup = BeautifulSoup(self.getMarkup(), "lxml")
    #         for junk in soup(["script", "style"]):
    #             junk.extract()
    #             self.__text = soup.get_text()
    #     return self.__text
    #
    # def getMarkup(self):
    #     if self.__markup is None:
    #         opener = urllib2.build_opener()
    #         opener.addheaders = GoogleSearch.DEFAULT_HEADERS
    #         response = opener.open(self.url);
    #         self.__markup = response.read()
    #     return self.__markup

    def __str__(self):
        return str(self.__dict__)

    def __repr__(self):
        return self.__str__()
