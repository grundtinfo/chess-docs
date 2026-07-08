import re
import string
import chess
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
    @staticmethod
    def get_opening_name(board):
        """Récupère le nom de l'ouverture intelligemment."""
        if OPENIX_AVAILABLE:
            try:
                # Récupère la séquence des coups joués
                move_stack = [move.san() for move in board.move_stack]
                # Recherche l'ouverture correspondante
                matches = _op_lib.find_openings_after_moves(move_stack)
                if matches:
                    return matches[0].name
            except Exception as e:
                Logger.debug_log(f"Erreur lookup Openix: {e}", "ERROR")
        
        # Fallback : utilise le header ECO si disponible dans l'objet board ou headers
        return "Ouverture Inconnue"

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
