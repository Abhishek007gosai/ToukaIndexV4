"""
Registry of available metadata sources, keyed by the same string used in
callback_data (e.g. "src:{session}:anilist") and stored in the database's
`source` column.
"""

from plugins.anilist import AniListSource
from plugins.myanimelist import MyAnimeListSource

anilist = AniListSource()
myanimelist = MyAnimeListSource()

SOURCES = {
    "anilist": anilist,
    "myanimelist": myanimelist,
}

__all__ = ["SOURCES", "anilist", "myanimelist"]
