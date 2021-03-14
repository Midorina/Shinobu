from __future__ import annotations

from typing import List

from mido_utils.exceptions import NotFoundError

__all__ = ['LocalSubreddit']


class LocalSubreddit:
    def __init__(self, exact_subreddit_name: str, tags: List[str]):
        self.subreddit_name = exact_subreddit_name

        self.tags = tags

    @property
    def db_name(self):
        return f'reddit_{self.subreddit_name}'

    @classmethod
    def get_with_related_tag(cls, category: str, tags: List[str] = None) -> List[LocalSubreddit]:
        if category == 'porn':
            subreddits = _PORN_SUBREDDITS
        elif category == 'hentai':
            subreddits = _HENTAI_SUBREDDITS
        elif category == 'meme':
            subreddits = _MEME_SUBREDDITS
        else:
            raise Exception("Invalid NSFW category!")

        if not tags:
            return list(subreddits)

        ret = []
        for subreddit in subreddits:
            for tag in tags:
                if tag in subreddit.tags:
                    ret.append(subreddit)
                    break

        if not ret:
            raise NotFoundError

        return ret

    @classmethod
    def get_all(cls) -> List[LocalSubreddit]:
        base = list(_PORN_SUBREDDITS)
        base.extend(_HENTAI_SUBREDDITS)
        base.extend(_MEME_SUBREDDITS)
        return base


_PORN_SUBREDDITS = (
    # boobs
    LocalSubreddit('boobs', ['boobs', 'boob', 'boobies', 'titty', 'titties', 'huge_boobs']),
    LocalSubreddit('Boobies', ['boobs', 'boob', 'boobies', 'titty', 'titties', 'huge_boobs']),
    LocalSubreddit('TittyDrop', ['boobs', 'boob', 'boobies', 'titty', 'titties', 'huge_boobs']),
    LocalSubreddit('hugeboobs', ['boobs', 'boob', 'boobies', 'titty', 'titties', 'huge_boobs']),
    LocalSubreddit('BustyPetite', ['boobs', 'boob', 'boobies', 'titty', 'titties', 'huge_boobs', 'teen', 'petite']),

    # ass
    LocalSubreddit('ass', ['ass', 'butt', 'butts', 'huge_ass', 'asses', 'big_ass', 'fat_ass']),
    LocalSubreddit('bigasses', ['ass', 'butt', 'butts', 'huge_ass', 'asses', 'big_ass', 'fat_ass']),
    LocalSubreddit('pawg', ['ass', 'butt', 'butts', 'huge_ass', 'asses', 'big_ass', 'fat_ass']),
    LocalSubreddit('asstastic', ['ass', 'butt', 'butts', 'huge_ass', 'asses', 'big_ass', 'fat_ass']),
    LocalSubreddit('CuteLittleButts', ['ass', 'butt', 'butts', 'asses', 'cute_ass', 'cute_butt', 'cute_little_butt']),

    # both
    LocalSubreddit('BiggerThanYouThought', ['huge', 'big']),

    # pussy
    LocalSubreddit('pussy', ['pussy']),
    LocalSubreddit('LipsThatGrip', ['pussy']),
    LocalSubreddit('GodPussy', ['pussy']),

    # asian
    LocalSubreddit('AsianHotties', ['asian']),
    LocalSubreddit('juicyasians', ['asian']),
    LocalSubreddit('AsiansGoneWild', ['asian']),

    # teen
    LocalSubreddit('gonewild', ['nude', 'teen']),
    LocalSubreddit('RealGirls', ['nude', 'teen']),
    LocalSubreddit('LegalTeens', ['teen', 'nude']),
    LocalSubreddit('collegesluts', ['slut', 'college', 'teen', 'slutty']),
    LocalSubreddit('cumsluts', ['cum', 'slut', 'teen']),
    LocalSubreddit('PetiteGoneWild', ['small', 'petite', 'teen']),
    LocalSubreddit('adorableporn', ['adorable', 'nude', 'teen']),
    LocalSubreddit('Amateur', ['amateur', 'teen']),
    LocalSubreddit('BreedingMaterial', ['adorable', 'beautiful', 'nude', 'teen']),

    LocalSubreddit('milf', ['milf', 'old']),

    # blowjob
    LocalSubreddit('GirlsFinishingTheJob', ['blowjob', 'cum']),
    LocalSubreddit('Blowjobs', ['blowjob']),

    LocalSubreddit('GWCouples', ['couple']),
    LocalSubreddit('lesbians', ['lesbian']),

    # video
    LocalSubreddit('porninfifteenseconds', ['porn', 'gif', 'video']),
    LocalSubreddit('NSFW_GIF', ['porn', 'gif', 'video']),
    LocalSubreddit('nsfw_gifs', ['porn', 'gif', 'video']),
    LocalSubreddit('nsfwhardcore', ['hardcore', 'porn', 'gif', 'video']),
    LocalSubreddit('porn_gifs', ['porn', 'gif', 'video']),
    LocalSubreddit('anal', ['anal', 'porn', 'gif', 'video']),

    # general
    LocalSubreddit('nsfw', ['porn', 'nude']),
    LocalSubreddit('OnOff', ['nude']),
    # LocalSubreddit('JizzedToThis', ['hot']),
    LocalSubreddit('holdthemoan', ['public']),
)

_HENTAI_SUBREDDITS = (
    LocalSubreddit('hentai', ['hentai']),
    LocalSubreddit('rule34', ['hentai']),
    LocalSubreddit('HENTAI_GIF', ['hentai', 'gif', 'video']),
    LocalSubreddit('ecchi', ['ecchi', 'hentai']),
    LocalSubreddit('yuri', ['hentai', 'yuri']),
    LocalSubreddit('AnimeBooty', ['hentai', 'butt', 'ass', 'booty']),
)

_MEME_SUBREDDITS = (
    LocalSubreddit('dankmemes', ['meme', 'memes', 'dankmemes']),
    LocalSubreddit('2meirl4meirl', ['meme', 'memes', 'me_irl']),
    LocalSubreddit('MemeEconomy', ['meme', 'memes']),
    # LocalSubreddit('DeepFriedMemes', ['meme', 'memes', 'deep_fried', 'deepfried'])
)
