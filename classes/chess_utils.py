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
    # Initialisation de la bibliothèque d'ouvertures
    _op_lib = ChessOpeningsLibrary()
    _op_lib.load_builtin_openings()
    OPENIX_AVAILABLE = True
except ImportError:
    OPENIX_AVAILABLE = False
    Logger.debug_log("Bibliothèque Openix non trouvée. Utilisation du mode restreint.", "WARNING")

class ChessUtils:
    _translation_cache = {}

    @staticmethod
    def calculate_elo_from_details(details):
        """Calcule l'ELO estimé basé sur les précisions des coups (ACPL) avec une courbe exponentielle."""
        weights = {"opening": 0.7, "middlegame": 1.2, "endgame": 1.0}
        w_cpl, b_cpl = 0.0, 0.0
        w_sum, b_sum = 0.0, 0.0
        
        for ply in details:
            w = weights.get(ply.get("phase", "opening"), 1.0)
            # Utilise la précision stockée (loss) pour le calcul
            loss = min(1000, max(0, -ply.get("precision", 0)))
            if ply.get("color") == "white":
                w_cpl += (loss * w); w_sum += w
            else:
                b_cpl += (loss * w); b_sum += w
                
        # Paramètres du modèle exponentiel
        MAX_ELO = 3200
        FLOOR_ELO = 400
        DECAY_CONSTANT = 0.019
        
        # Fonction locale pour appliquer la courbe exponentielle
        def apply_exponential_curve(acpl):
            return int(FLOOR_ELO + (MAX_ELO - FLOOR_ELO) * math.exp(-DECAY_CONSTANT * acpl))

        # Calcul final des ELOs estimés
        est_w = apply_exponential_curve(w_cpl / w_sum) if w_sum > 0 else 1200
        est_b = apply_exponential_curve(b_cpl / b_sum) if b_sum > 0 else 1200
        
        return est_w, est_b

    @staticmethod
    @staticmethod
    def get_opening_name(board):
        """Récupère le nom de l'ouverture intelligemment avec Openix, traduit via LLM si nécessaire."""
        opening_name = "Ouverture Inconnue"
        
        if OPENIX_AVAILABLE:
            try:
                # CORRECTION : Reconstitution correcte de la liste des coups en SAN
                # On utilise un plateau temporaire pour générer les SAN selon l'historique
                temp_board = chess.Board()
                move_stack = []
                for move in board.move_stack:
                    move_stack.append(temp_board.san(move))
                    temp_board.push(move)
                
                # Recherche l'ouverture correspondante
                matches = _op_lib.find_openings_after_moves(move_stack)
                if matches:
                    opening_name = matches[0].name
            except Exception as e:
                Logger.debug_log(f"Erreur lookup Openix: {e}", "ERROR")

        if opening_name != "Ouverture Inconnue":
            # Import local pour éviter l'erreur d'import circulaire avec AIAnalyzer
            from classes.ai_analyzer import AIAnalyzer
            
            if opening_name not in ChessUtils._translation_cache:
                traduit = AIAnalyzer.translate_opening_name(opening_name)
                ChessUtils._translation_cache[opening_name] = traduit
            
            return ChessUtils._translation_cache[opening_name]

        # Fallback
        return opening_name

    @staticmethod
    def resolve_stockfish_depth(explicit_depth=None):
        return int(explicit_depth) if explicit_depth is not None else Config.DEFAULT_STOCKFISH_DEPTH

    @staticmethod
    def convert_french_to_english_notation(move):
        if not move: return move
        piece_map = {'D': 'Q', 'C': 'N', 'F': 'B', 'T': 'R', 'R': 'K'}
        if move[0] in piece_map:
            move = piece_map[move[0]] + move[1:]
        if '=' in move:
            parts = move.split('=')
            if len(parts) == 2 and len(parts[1]) > 0:
                promoted_piece = parts[1][0]
                if promoted_piece in piece_map:
                    move = parts[0] + '=' + piece_map[promoted_piece] + parts[1][1:]
        return move

    @staticmethod
    def convert_english_to_french_notation(move):
        if not move: return move
        piece_map = {'Q': 'D', 'N': 'C', 'B': 'F', 'R': 'T', 'K': 'R'}
        if move[0] in piece_map:
            move = piece_map[move[0]] + move[1:]
        if '=' in move:
            parts = move.split('=')
            if len(parts) == 2 and len(parts[1]) > 0:
                promoted_piece = parts[1][0]
                if promoted_piece in piece_map:
                    move = parts[0] + '=' + piece_map[promoted_piece] + parts[1][1:]
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
            chess.PAWN: "Pion", chess.KNIGHT: "Cavalier", chess.BISHOP: "Fou",
            chess.ROOK: "Tour", chess.QUEEN: "Dame", chess.KING: "Roi"
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
        if delta <= -400: return "??"
        if delta <= -120: return "?"
        if delta >= 400: return "!!"
        if delta >= 160: return "!"
        return ""

    @staticmethod
    def build_player_state_path(base_dir, player_name):
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", player_name).strip("_") or "player"
        return os.path.join(base_dir, "json", f"player_{safe_name}.json")

    @staticmethod
    def is_game_incomplete(game, require_deep):
        if not game or not game.get("is_complete", False) or not game.get("result") or game.get("result") == "*": return True
        if not game.get("date") or not game.get("end_time") or not game.get("analysis", {}).get("summary"): return True
        return require_deep and (not game.get("deep_analysis") or not game.get("analysis", {}).get("details"))

    @staticmethod
    def fetch_player_games(username, months=6):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChessDocs/1.0"}
        Logger.debug_log(f"Récupération des archives Chess.com pour {username} (mois={months})", "INFO")

        def request_with_retry(url, retries=3):
            for attempt in range(retries):
                try:
                    response = requests.get(url, timeout=25, headers=headers)
                    if response.status_code in {403, 429} and attempt < retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    response.raise_for_status()
                    return response
                except requests.RequestException as exc:
                    if attempt < retries - 1: time.sleep(2 ** attempt)
                    else: raise exc

        archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
        try:
            archives = request_with_retry(archives_url).json().get("archives", [])
        except Exception as e:
            Logger.debug_log(f"Erreur API archives: {e}", "ERROR")
            return []

        recent_archives = archives[-months:] if months and months > 0 else archives
        games = []
        for archive_url in recent_archives:
            try: games.extend(request_with_retry(archive_url).json().get("games", []))
            except Exception: pass
        return games
