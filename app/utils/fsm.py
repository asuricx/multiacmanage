import json
from typing import Any, Dict, Optional, Tuple
from app.core.redis import get_redis


class FSMManager:
    """
    Finite State Machine manager for Telegram Admin Bot conversation flows.
    Backed by Redis with memory fallback.
    """

    _memory_cache: Dict[int, Dict[str, Any]] = {}

    @classmethod
    async def set_state(cls, user_id: int, state: str, data: Optional[Dict[str, Any]] = None, ttl: int = 600) -> None:
        """Sets state and associated data for a user with TTL in seconds."""
        payload = {
            "state": state,
            "data": data or {},
        }
        try:
            r = await get_redis()
            await r.set(f"fsm:{user_id}", json.dumps(payload), ex=ttl)
        except Exception:
            cls._memory_cache[user_id] = payload

    @classmethod
    async def get_state(cls, user_id: int) -> Tuple[Optional[str], Dict[str, Any]]:
        """Returns tuple (state, data) for a user."""
        try:
            r = await get_redis()
            raw = await r.get(f"fsm:{user_id}")
            if raw:
                parsed = json.loads(raw)
                return parsed.get("state"), parsed.get("data", {})
        except Exception:
            pass

        cached = cls._memory_cache.get(user_id)
        if cached:
            return cached.get("state"), cached.get("data", {})
        return None, {}

    @classmethod
    async def update_data(cls, user_id: int, **kwargs) -> Dict[str, Any]:
        """Updates arbitrary key-value pairs in the user's state data."""
        state, data = await cls.get_state(user_id)
        if not state:
            return {}
        data.update(kwargs)
        await cls.set_state(user_id, state, data)
        return data

    @classmethod
    async def clear_state(cls, user_id: int) -> None:
        """Clears state and data for a user."""
        try:
            r = await get_redis()
            await r.delete(f"fsm:{user_id}")
        except Exception:
            pass
        cls._memory_cache.pop(user_id, None)
