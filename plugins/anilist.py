"""
AniList adapter — public GraphQL API, no API key required.
https://anilist.gitbook.io/anilist-apiv2-docs/
"""

import time

import requests

from config import Config
from plugins.base import AnimeSource

SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 5) {
    pageInfo { hasNextPage }
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english }
      startDate { year }
      coverImage { large }
    }
  }
}
"""

DETAILS_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title { romaji english }
    startDate { year }
    coverImage { large extraLarge }
    bannerImage
    description(asHtml: false)
    genres
    averageScore
  }
}
"""

DISCOVER_QUERY = """
query ($sort: [MediaSort]) {
  Page(page: 1, perPage: 10) {
    media(type: ANIME, sort: $sort) {
      id
      title { romaji english }
      coverImage { large }
      averageScore
    }
  }
}
"""


def _clean_description(html: str | None) -> str:
    if not html:
        return ""
    text = html.replace("<br>", "\n").replace("<br/>", "\n").replace("<i>", "").replace("</i>", "")
    return text.strip()


def _best_title(title_obj: dict) -> str:
    return title_obj.get("english") or title_obj.get("romaji") or "Untitled"


class AniListSource(AnimeSource):
    name = "anilist"

    def __init__(self):
        self._cache: dict[str, tuple[float, list]] = {}

    def _post(self, query: str, variables: dict) -> dict:
        resp = requests.post(
            Config.ANILIST_ENDPOINT,
            json={"query": query, "variables": variables},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def search(self, query: str, page: int = 1) -> dict:
        data = self._post(SEARCH_QUERY, {"search": query, "page": page})
        media = data["Page"]["media"]
        results = [
            {
                "source_id": m["id"],
                "title": _best_title(m["title"]),
                "year": (m.get("startDate") or {}).get("year"),
                "poster_url": (m.get("coverImage") or {}).get("large"),
            }
            for m in media
        ]
        return {"results": results, "has_next": data["Page"]["pageInfo"]["hasNextPage"]}

    def get_details(self, source_id) -> dict:
        data = self._post(DETAILS_QUERY, {"id": int(source_id)})
        m = data["Media"]
        score = m.get("averageScore")
        return {
            "source": self.name,
            "source_id": m["id"],
            "title": _best_title(m["title"]),
            "year": (m.get("startDate") or {}).get("year"),
            "poster_url": (m.get("coverImage") or {}).get("extraLarge") or (m.get("coverImage") or {}).get("large"),
            "banner_url": m.get("bannerImage"),
            "description": _clean_description(m.get("description")),
            "genres": m.get("genres") or [],
            "rating": round(score / 10, 1) if score else None,
        }

    # -- Extra: powers the "All" tab discovery feed (not part of the shared interface) --

    def _cached(self, key: str, fetch):
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < Config.CATALOG_CACHE_TTL:
            return cached[1]
        value = fetch()
        self._cache[key] = (now, value)
        return value

    def _discover(self, sort: str) -> list:
        def fetch():
            data = self._post(DISCOVER_QUERY, {"sort": [sort]})
            out = []
            for m in data["Page"]["media"]:
                score = m.get("averageScore")
                out.append({
                    "title": _best_title(m["title"]),
                    "poster_url": (m.get("coverImage") or {}).get("large"),
                    "rating": round(score / 10, 1) if score else None,
                    "anilist_id": m["id"],
                })
            return out

        return self._cached(sort, fetch)

    def get_trending(self) -> list:
        return self._discover("TRENDING_DESC")

    def get_popular(self) -> list:
        return self._discover("POPULARITY_DESC")
