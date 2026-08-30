import re
import string
import chess
import math
import os
import time
import requests
from datetime import datetime
from classes.config import Config
from classes.logger import Logger

try:
    from Openix import ChessOpeningsLibrary
    _op_lib = ChessOpeningsLibrary()
    _op_lib.load_builtin_openings()
    OPENIX_AVAILABLE = True
except ImportError:
    OPENIX_AVAILABLE = False
    Logger.debug_log("Bibliothèque Openix non trouvée. Utilisation du mode restreint.", "WARNING")

_FR_TO_EN_MAP = {'D': 'Q', 'C': 'N', 'F': 'B', 'T': 'R', 'R': 'K'}
_EN_TO_FR_MAP = {'Q': 'D', 'N': 'C', 'B': 'F', 'R': 'T', 'K': 'R'}
_HTTP_SESSION = requests.Session()

class ChessUtils:

    @staticmethod
    def calculate_elo_from_details(details):
        if not details:
            return 1200, 1200
            
        w_acc, b_acc = [], []
        
        for ply in details:
            prec = ply.get("precision", -9999)
            # Ignorer la précision des coups non encore analysés
            if prec == -9999: 
                continue
                
            loss = min(1000, max(0, -prec))
            
            # Ancrage d'Accuracy (type CAPS Lichess/Chess.com approximation via centipions)
            move_accuracy = max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * (loss / 10.0))))
            
            if ply.get("color") == "white":
                w_acc.append(move_accuracy)
            else:
                b_acc.append(move_accuracy)
                
        avg_w_acc = sum(w_acc) / len(w_acc) if w_acc else 0
        avg_b_acc = sum(b_acc) / len(b_acc) if b_acc else 0
        
        # Mapping linéaire basé sur l'Accuracy: 95% = 2325, 90% = 2150, 70% = 1450, 50% = 750
        def accuracy_to_elo(acc):
            if acc == 0: return 400
            elo = int((acc * 35) - 1000)
            return max(400, min(3200, elo))

        est_w = accuracy_to_elo(avg_w_acc) if w_acc else 1200
        est_b = accuracy_to_elo(avg_b_acc) if b_acc else 1200
        
        return est_w, est_b

    @staticmethod
    def get_opening_name(board):
        Logger.debug_log("Étape Analyse : Recherche du nom de l'ouverture en cours...", "DEBUG")
        opening_name = "Ouverture Inconnue"
        
        if OPENIX_AVAILABLE:
            try:
                temp_board = chess.Board()
                move_stack = []
                for move in board.move_stack:
                    move_stack.append(temp_board.san(move))
                    temp_board.push(move)
                
                matches = _op_lib.find_openings_after_moves(move_stack)
                if matches:
                    opening_name = matches[0].name
                    Logger.debug_log(f"Étape Analyse : Ouverture identifiée par Openix -> {opening_name}", "DEBUG")
            except Exception as e:
                Logger.debug_log(f"Erreur lookup Openix: {e}", "ERROR")

        if opening_name != "Ouverture Inconnue":
            from classes.ai_analyzer import AIAnalyzer
            from classes.json_cache import CacheManager
            
            cache_global = CacheManager.load_cache()
            cache_key = f"opening_{opening_name}"
            
            if cache_key not in cache_global:
                Logger.debug_log(f"Étape Analyse : Traduction de l'ouverture '{opening_name}' (non mise en cache).", "DEBUG")
                traduit = AIAnalyzer.translate_opening_name(opening_name)
                cache_global[cache_key] = traduit
                CacheManager.save_cache(cache_global)
            else:
                Logger.debug_log("Étape Analyse : Nom d'ouverture traduit récupéré depuis le cache.", "DEBUG")
                
            return cache_global[cache_key]

        Logger.debug_log("Étape Analyse : Aucune ouverture formelle reconnue.", "DEBUG")
        return opening_name
    
    @staticmethod
    def is_raw_opening(name):
        if not name or name in ["Ouverture Inconnue", "None", ""]: return True
        if re.match(r'^[A-E]\d{2}$', str(name)): return True
        return False

    @staticmethod
    def resolve_stockfish_depth(explicit_depth=None):
        return int(explicit_depth) if explicit_depth is not None else Config.DEFAULT_STOCKFISH_DEPTH

    @staticmethod
    def convert_french_to_english_notation(move):
        if not move: return move
        if move[0] in _FR_TO_EN_MAP:
            move = _FR_TO_EN_MAP[move[0]] + move[1:]
        if '=' in move:
            parts = move.split('=')
            if len(parts) == 2 and len(parts[1]) > 0:
                promoted_piece = parts[1][0]
                if promoted_piece in _FR_TO_EN_MAP:
                    move = parts[0] + '=' + _FR_TO_EN_MAP[promoted_piece] + parts[1][1:]
        return move

    @staticmethod
    def convert_english_to_french_notation(move):
        if not move: return move
        move = move.strip()
        if move[0] in _EN_TO_FR_MAP:
            move = _EN_TO_FR_MAP[move[0]] + move[1:]
        if '=' in move:
            parts = move.split('=')
            if len(parts) == 2 and len(parts[1]) > 0:
                promoted_piece = parts[1][0]
                if promoted_piece in _EN_TO_FR_MAP:
                    move = parts[0] + '=' + _EN_TO_FR_MAP[promoted_piece] + parts[1][1:]
        return move

    @staticmethod
    def parse_moves(coups_str):
        pattern = r'(\d+)\.\s*([^\s]+)(?:\s+([^\s]+))?'
        matches = re.findall(pattern, coups_str)
        moves = []
        clean_pattern = r'[?!]+' 
        for num, white, black in matches:
            white_raw = white.strip()
            white_san = ChessUtils.convert_french_to_english_notation(re.sub(clean_pattern, '', white_raw))
            moves.append({"raw": white_raw, "san": white_san, "move_number": int(num), "color": "white"})
            if black:
                black_raw = black.strip()
                black_san = ChessUtils.convert_french_to_english_notation(re.sub(clean_pattern, '', black_raw))
                moves.append({"raw": black_raw, "san": black_san, "move_number": int(num), "color": "black"})
        return moves

    @staticmethod
    def get_eval_value(eval_dict, current_board=None):
        if current_board and current_board.is_checkmate():
            return 10000 if current_board.turn == chess.BLACK else -10000
        if not eval_dict: return 0
        if hasattr(eval_dict, 'value'):
            val = eval_dict.value if eval_dict.value is not None else 0
            t = getattr(eval_dict, 'type', 'cp')
        else:
            val = eval_dict.get('value', 0) if isinstance(eval_dict, dict) else 0
            t = eval_dict.get('type', 'cp') if isinstance(eval_dict, dict) else 'cp'
        if t == 'mate':
            if val > 0: return 10000 - val
            elif val < 0: return -10000 - val
            else: return 0
        return val

    @staticmethod
    def remove_special_chars(input_string):
        translator = str.maketrans('', '', string.punctuation.replace('-', '').replace('#', ''))
        return input_string.translate(translator)

    @staticmethod
    def get_piece_name_fr(piece):
        if not piece: return "Pièce"
        names = {
            chess.PAWN: "Pion",
            chess.KNIGHT: "Cavalier",
            chess.BISHOP: "Fou",
            chess.ROOK: "Tour",
            chess.QUEEN: "Dame",
            chess.KING: "Roi"
        }
        return names.get(piece.piece_type, "Pièce")

    @staticmethod
    def format_eval_string(eval_dict, is_white_turn):
        if not eval_dict: return "0.0"
        if hasattr(eval_dict, 'value'):
            val = eval_dict.value if eval_dict.value is not None else 0
            t = getattr(eval_dict, 'type', 'cp')
        else:
            val = eval_dict.get('value', 0) if isinstance(eval_dict, dict) else 0
            t = eval_dict.get('type', 'cp') if isinstance(eval_dict, dict) else 'cp'
            
        player_multiplier = 1 if is_white_turn else -1
        if t == 'mate':
            mate_in = val * player_multiplier
            if mate_in > 0: return f"Mat en {mate_in} en votre faveur"
            elif mate_in < 0: return f"Mat en {abs(mate_in)} contre vous"
            else: return "Échec et Mat"
        else:
            cp_val = (val * player_multiplier) / 100.0
            return f"{cp_val:+.1f}"

    @staticmethod
    def classify_opponent_type(username):
        if not username: return "humain"
        return "robot" if any(token in username.lower() for token in ["bot", "engine", "stockfish", "computer", "ai", "chess.com"]) else "humain"

    @staticmethod
    def infer_move_suffix(is_check=False, is_checkmate=False, delta=None):
        if is_checkmate: return "#"
        if is_check: return "+"
        if delta is None: return ""
        if delta <= -300: return "??"
        if delta <= -150: return "?"
        if delta <= -80: return "?!"
        if delta <= -30: return "!?"
        if delta >= 400: return "!!"
        if delta >= 160: return "!"
        return ""

    @staticmethod
    def build_player_state_path(base_dir, player_name):
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", player_name).strip("_") or "player"
        # Renvoie désormais un chemin de DOSSIER (retrait de l'extension .json)
        return os.path.join(base_dir, "json", f"player_{safe_name}")

    @staticmethod
    def is_game_incomplete(game, require_deep):
        if not game or not game.get("is_complete", False) or not game.get("result") or game.get("result") == "*": return True
        if not game.get("date") or not game.get("end_time") or not game.get("analysis", {}).get("summary"): return True
        return require_deep and (not game.get("deep_analysis") or not game.get("analysis", {}).get("details"))

    @staticmethod
    def fetch_player_games(username, months=6):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChessDocs/1.0"}
        Logger.debug_log(f"Récupération des archives Chess.com pour {username} (mois={months})", "INFO")

        def request_with_retry(url, retries=5, base_delay=1):
            for attempt in range(retries):
                try:
                    # Réutilisation de la session HTTP globale
                    response = _HTTP_SESSION.get(url, timeout=20, headers=headers)
                    
                    if response.status_code in {403, 404, 429, 500, 502, 503, 504} and attempt < retries - 1:
                        attente = base_delay * (2 ** attempt) # 1s, 2s, 4s, 8s...
                        Logger.debug_log(f"HTTP {response.status_code} sur l'API. Nouvelle tentative {attempt + 1}/{retries} dans {attente}s...", "WARNING")
                        time.sleep(attente)
                        continue
                        
                    response.raise_for_status()
                    return response
                except requests.RequestException as exc:
                    if attempt < retries - 1: 
                        attente = base_delay * (2 ** attempt)
                        Logger.debug_log(f"Exception réseau ({exc}). Nouvelle tentative {attempt + 1}/{retries} dans {attente}s...", "WARNING")
                        time.sleep(attente)
                    else: 
                        raise exc

        archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
        try:
            archives = request_with_retry(archives_url).json().get("archives", [])
        except Exception as e:
            Logger.debug_log(f"Erreur API archives: {e}", "ERROR")
            return []
            
        recent_archives = archives[-months:] if months and months > 0 else archives
        games = []
        for archive_url in recent_archives:
            try:
                archive_games = request_with_retry(archive_url).json().get("games", [])
                # Conserver uniquement les parties disposant d'un PGN avec un résultat final
                finished_games = [
                    g for g in archive_games 
                    if g.get("pgn") and not g.get("pgn").strip().endswith("*")
                ]
                games.extend(finished_games)
            except Exception: 
                pass
        return games

    @staticmethod
    def parse_stockfish_pv(pv_str, is_white_turn=True, start_move_number=1):
        """Convertit une séquence de coups (ex: Bb6 a4 a6) en notation classique."""
        if not pv_str: return pv_str
        
        moves = pv_str.split()
        formatted_moves = []
        current_move = int(start_move_number)
        white_to_move = bool(is_white_turn)
        
        for i, move_eng in enumerate(moves):
            move_fr = ChessUtils.convert_english_to_french_notation(move_eng)
            
            if white_to_move:
                # Coup des blancs : ajout du point et d'un espace typographique
                formatted_moves.append(f"{current_move}. {move_fr}")
            else:
                # Coup des noirs
                if i == 0:
                    # C'est le tout premier coup de la séquence
                    formatted_moves.append(f"{current_move}... {move_fr}")
                else:
                    # Suite normale
                    formatted_moves.append(move_fr)
                
                # Le tour complet est terminé, on incrémente le numéro de coup
                current_move += 1
                
            white_to_move = not white_to_move
            
        return " ".join(formatted_moves)
