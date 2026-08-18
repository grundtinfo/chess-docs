import os
import re
import orjson
from classes.logger import Logger

class CacheManager:
    CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "json", "cache_analyses.json")

    @classmethod
    def load_cache(cls):
        Logger.debug_log(f"Étape Cache : Lecture du cache global depuis {cls.CACHE_FILE}", "DEBUG")
        if not os.path.exists(cls.CACHE_FILE):
            Logger.debug_log("Étape Cache : Fichier cache introuvable, initialisation d'un cache vide.", "DEBUG")
            return {}
        try:
            with open(cls.CACHE_FILE, "rb") as f:
                data = orjson.loads(f.read())
                Logger.debug_log(f"Étape Cache : Cache chargé avec succès ({len(data)} entrées).", "DEBUG")
                return data
        except Exception as e:
            Logger.debug_log(f"Erreur lors de la lecture du cache : {e}", "ERROR")
            return {}

    @classmethod
    def save_cache(cls, cache_data):
        os.makedirs(os.path.dirname(cls.CACHE_FILE), exist_ok=True)
        with open(cls.CACHE_FILE, "wb") as f:
            f.write(orjson.dumps(cache_data, option=orjson.OPT_INDENT_2))

    @staticmethod
    def load_state(path):
        # 'path' est désormais un dossier : json/player_<nom>
        player_name = os.path.basename(path).replace("player_", "")
        state = {"player": player_name, "games": {}}
        
        # RÉTROCOMPATIBILITÉ : Gérer l'ancien fichier unique pour ne pas perdre l'historique
        old_file = f"{path}.json"
        if os.path.exists(old_file):
            try:
                with open(old_file, "rb") as handle:
                    data = orjson.loads(handle.read())
                    if isinstance(data.get("games"), list):
                        state["games"] = {g["id"]: g for g in data["games"] if "id" in g}
                    elif isinstance(data.get("games"), dict):
                        state["games"] = data["games"]
            except Exception:
                pass

        if not os.path.exists(path) or not os.path.isdir(path):
            return state

        # Chargement de la nouvelle structure éclatée
        for filename in os.listdir(path):
            if filename.startswith("game_") and filename.endswith(".json"):
                try:
                    filepath = os.path.join(path, filename)
                    with open(filepath, "rb") as handle:
                        game_data = orjson.loads(handle.read())
                        # Fallback sur l'URL complète si l'ID n'est pas explicite
                        game_id = game_data.get("id", game_data.get("url", filename)) 
                        state["games"][game_id] = game_data
                except Exception as e:
                    Logger.debug_log(f"Erreur de lecture du fichier {filename}: {e}", "ERROR")
        
        return state

    @staticmethod
    def save_state(path, state):
        # Sauvegarde globale (fin de processus)
        os.makedirs(path, exist_ok=True)
        games = state.get("games", {})
        for game_id, game_data in games.items():
            CacheManager.save_game(path, game_id, game_data)

    @staticmethod
    def save_game(path, game_id, game_data):
        # Sauvegarde isolée pour une seule partie
        os.makedirs(path, exist_ok=True)
        # On extrait la fin de l'URL pour avoir un ID propre (ex: live/12345678 -> 12345678)
        clean_id = str(game_id).split('/')[-1]
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", clean_id).strip("_")
        
        filepath = os.path.join(path, f"game_{safe_id}.json")
        with open(filepath, "wb") as handle:
            handle.write(orjson.dumps(game_data, option=orjson.OPT_INDENT_2))
