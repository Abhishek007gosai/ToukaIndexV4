"""
MyAnimeList adapter, via the free public Jikan API (unofficial MAL wrapper —
no API key or OAuth app required). https://docs.api.jikan.moe/
"""

import requests

from config import Config
from plugins.base import AnimeSource


class MyAnimeListSource(AnimeSource):
    name = "myanimelist"

    def search(self, query: str, page: int = 1) -> dict:
        resp = requests.get(
            f"{Config.JIKAN_ENDPOINT}/anime",
            params={"q": query, "page": page, "limit": 5},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        results = [
            {
                "source_id": item["mal_id"],
                "title": item.get("title") or "Untitled",
                "year": (item.get("aired") or {}).get("prop", {}).get("from", {}).get("year"),
                "poster_url": (item.get("images") or {}).get("jpg", {}).get("large_image_url"),
            }
            for item in payload.get("data", [])
        ]
        has_next = bool((payload.get("pagination") or {}).get("has_next_page"))
        return {"results": results, "has_next": has_next}

    def get_details(self, source_id) -> dict:
        resp = requests.get(f"{Config.JIKAN_ENDPOINT}/anime/{source_id}", timeout=10)
        resp.raise_for_status()
        m = resp.json()["data"]
        score = m.get("score")  # already out of 10 on MAL
        return {
            "source": self.name,
            "source_id": m["mal_id"],
            "title": m.get("title") or "Untitled",
            "year": (m.get("aired") or {}).get("prop", {}).get("from", {}).get("year"),
            "poster_url": (m.get("images") or {}).get("jpg", {}).get("large_image_url"),
            "banner_url": None,
            "description": (m.get("synopsis") or "").strip(),
            "genres": [g["name"] for g in (m.get("genres") or [])],
            "rating": round(score, 1) if score else None,
        }
