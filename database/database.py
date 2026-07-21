"""
MongoDB data layer for Anime Index.

IDs are kept as small sequential integers (via a `counters` collection)
rather than raw Mongo ObjectIds — Flask's route converters (e.g.
<int:anime_id>) and the bot's callback_data parsing (e.g. "req:{id}:accept")
both expect plain integers, and this keeps that working unchanged.

Every function here mirrors the shape app.py already expects: dicts with
plain keys (anime "id", not "_id"), lists for genres, etc.
"""

import time

from pymongo import ASCENDING, MongoClient

from config import Config

_client = MongoClient(Config.MONGODB_URL)
_db = _client[Config.MONGODB_NAME]

anime_col = _db["anime"]
users_col = _db["users"]
requests_col = _db["requests"]
reports_col = _db["reports"]
counters_col = _db["counters"]


def init_db():
    anime_col.create_index([("source", ASCENDING), ("source_id", ASCENDING)], unique=True)
    anime_col.create_index([("title", ASCENDING)])
    requests_col.create_index([("status", ASCENDING)])


def _next_id(counter_name: str) -> int:
    doc = counters_col.find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["seq"]


# ---------------------------------------------------------------------------
# Anime catalog
# ---------------------------------------------------------------------------

def _to_anime(doc) -> dict | None:
    if not doc:
        return None
    d = dict(doc)
    d["id"] = d.pop("_id")
    d["genres"] = d.get("genres") or []
    d["available"] = bool(d.get("join_link"))
    return d


def upsert_anime(details: dict, added_by: int | None = None) -> int:
    """Insert a new catalog entry from a normalized source dict, or update
    the existing one if this (source, source_id) was already posted."""
    now = time.time()
    existing = anime_col.find_one({"source": details["source"], "source_id": str(details["source_id"])})

    if existing:
        anime_col.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "title": details["title"],
                "year": details.get("year"),
                "poster_url": details.get("poster_url"),
                "banner_url": details.get("banner_url"),
                "description": details.get("description"),
                "genres": details.get("genres", []),
                "rating": details.get("rating"),
                "updated_at": now,
            }},
        )
        return existing["_id"]

    new_id = _next_id("anime")
    anime_col.insert_one({
        "_id": new_id,
        "source": details["source"],
        "source_id": str(details["source_id"]),
        "title": details["title"],
        "year": details.get("year"),
        "poster_url": details.get("poster_url"),
        "banner_url": details.get("banner_url"),
        "description": details.get("description"),
        "genres": details.get("genres", []),
        "rating": details.get("rating"),
        "join_link": None,
        "added_by": added_by,
        "created_at": now,
        "updated_at": now,
    })
    return new_id


def delete_anime(anime_id: int):
    anime_col.delete_one({"_id": anime_id})


def get_anime(anime_id: int) -> dict | None:
    return _to_anime(anime_col.find_one({"_id": anime_id}))


def list_available() -> list[dict]:
    """Every post in the local library — a post appears here as soon as
    /addpost creates it, whether or not a join link has been set yet."""
    docs = anime_col.find().collation({"locale": "en", "strength": 2}).sort("title", ASCENDING)
    return [_to_anime(d) for d in docs]


def search_local(query: str) -> list[dict]:
    docs = (
        anime_col.find({"title": {"$regex": query, "$options": "i"}})
        .collation({"locale": "en", "strength": 2})
        .sort("title", ASCENDING)
    )
    return [_to_anime(d) for d in docs]


def update_link(anime_id: int, link: str):
    anime_col.update_one(
        {"_id": anime_id},
        {"$set": {"join_link": link or None, "updated_at": time.time()}},
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None,
                        is_admin: bool) -> dict:
    role = "admin" if is_admin else "member"
    existing = users_col.find_one({"_id": telegram_id})

    if existing:
        users_col.update_one(
            {"_id": telegram_id},
            {"$set": {"username": username, "first_name": first_name, "role": role}},
        )
        existing.update(username=username, first_name=first_name, role=role)
        existing["telegram_id"] = existing.pop("_id")
        return existing

    now = time.time()
    doc = {
        "_id": telegram_id, "username": username, "first_name": first_name,
        "role": role, "access": "active", "registered_at": now,
    }
    users_col.insert_one(dict(doc))
    doc["telegram_id"] = doc.pop("_id")
    return doc


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def create_request(anime_title: str, requested_by: int | None, requested_by_name: str | None) -> int:
    new_id = _next_id("requests")
    requests_col.insert_one({
        "_id": new_id,
        "anime_title": anime_title,
        "requested_by": requested_by,
        "requested_by_name": requested_by_name,
        "status": "pending",
        "created_at": time.time(),
    })
    return new_id


def get_request(request_id: int) -> dict | None:
    doc = requests_col.find_one({"_id": request_id})
    if not doc:
        return None
    d = dict(doc)
    d["id"] = d.pop("_id")
    return d


def update_request_status(request_id: int, status: str):
    requests_col.update_one({"_id": request_id}, {"$set": {"status": status}})


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def create_report(anime_id: int | None, anime_title: str, reason: str, details: str,
                   reported_by: int | None, reported_by_name: str | None) -> int:
    new_id = _next_id("reports")
    reports_col.insert_one({
        "_id": new_id,
        "anime_id": anime_id,
        "anime_title": anime_title,
        "reason": reason,
        "details": details,
        "reported_by": reported_by,
        "reported_by_name": reported_by_name,
        "created_at": time.time(),
    })
    return new_id
