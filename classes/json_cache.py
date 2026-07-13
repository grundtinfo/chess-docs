import os
import orjson

class CacheManager:
    CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "json", "cache_analyses.json")

    @classmethod
    def load_cache(cls):
        if not os.path.exists(cls.CACHE_FILE):
            return {}
        try:
            with open(cls.CACHE_FILE, "rb") as f:
                return orjson.loads(f.read())
        except Exception:
            return {}

    @classmethod
    def save_cache(cls, cache_data):
        os.makedirs(os.path.dirname(cls.CACHE_FILE), exist_ok=True)
        with open(cls.CACHE_FILE, "wb") as f:
            f.write(orjson.dumps(cache_data, option=orjson.OPT_INDENT_2))

    @staticmethod
    def load_state(path):
        if not path or not os.path.exists(path): 
            return {"player": "", "games": {}}
        try:
            with open(path, "rb") as handle: # Mode binaire 'rb'
                data = orjson.loads(handle.read()) # orjson gère les bytes directement
                if isinstance(data.get("games"), list):
                    data["games"] = {g["id"]: g for g in data["games"] if "id" in g}
                elif not isinstance(data.get("games"), dict):
                    data["games"] = {}
                return data
        except Exception: 
            return {"player": "", "games": {}}

    @staticmethod
    def save_state(path, state):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle: # Mode binaire 'wb'
            # OPT_INDENT_2 remplace le paramètre 'indent=2' du module json standard
            handle.write(orjson.dumps(state, option=orjson.OPT_INDENT_2))
