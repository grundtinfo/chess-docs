import os
import re
import json
import chess
import chess.svg
import subprocess
import time
import ollama
import requests
import string
from io import StringIO
from reportlab.platypus import Flowable
from reportlab.lib import colors
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

try:
    from stockfish import Stockfish
    STOCKFISH_AVAILABLE = True
except ImportError:
    STOCKFISH_AVAILABLE = False
    print("[AVERTISSEMENT] Stockfish non disponible. Les commentaires seront générés sans analyse.")

# =====================================================================
# CONFIGURATION OLLAMA (LLM Local)
# =====================================================================
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:7b"
# Modèles testés :
# - granite3.2:8b quleques hallucinations et ne respecte pas toujours les consignes
# - mistral:7b français impecable, comprends et applique les consignes mais pas toujours très rapide
# - qwen2.5:7b le fançais n'est pas toujours très bon mais rigoureux et bons temps de réponse

# =====================================================================
# GESTIONNAIRE OLLAMA (Démarrage / Extinction automatique)
# =====================================================================
class OllamaManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.process = None
            cls._instance.is_managed_by_us = False
        return cls._instance
        
    def start(self):
        try:
            # Vérifie si le serveur tourne déjà (remplacer list_models par list)
            if ollama.list():
                print("[INFO] Le serveur Ollama est déjà en cours d'exécution.")
                return
        except Exception as e:
            print(f"[ERROR] Erreur lors de la vérification du serveur Ollama: {e}")
            return

        print("[INFO] Démarrage du serveur Ollama en arrière-plan...")
        try:
            # Démarrage du serveur Ollama via la librairie
            self.process = ollama.run()
            self.is_managed_by_us = True
        except FileNotFoundError:
            print("[ERROR] Ollama n'est pas installé ou non trouvé dans le PATH.")
            return

    def stop(self):
        # 1. Forcer le déchargement immédiat du modèle de la VRAM
        print(f"\n[INFO] Nettoyage : Déchargement du modèle {OLLAMA_MODEL} de la VRAM...")
        try:
            ollama.stop()
        except Exception as e:
            print(f"[ERROR] Erreur lors du déchargement du modèle: {e}")
        
        # 2. Tuer le processus serveur uniquement si notre script l'a démarré
        if self.is_managed_by_us and self.process:
            try:
                self.process.kill()
            except Exception as e:
                print(f"[ERROR] Erreur lors de la fermeture du processus: {e}")

# =====================================================================
# COULEURS (Charte Graphique Commune)
# =====================================================================
COLOR_PRIMARY = colors.HexColor("#1e293b")
COLOR_SECONDARY = colors.HexColor("#0284c7")
COLOR_TEXT = colors.HexColor("#334155")
COLOR_BG_LIGHT = colors.HexColor("#f8fafc")
COLOR_BORDER = colors.HexColor("#e2e8f0")
COLOR_MINT = colors.HexColor("#0f766e")

# =====================================================================
# FONCTIONS DE TRADUCTION ET UTILITAIRES
# =====================================================================
def convert_french_to_english_notation(move):
    piece_map = {'D': 'Q', 'C': 'N', 'F': 'B', 'T': 'R', 'R': 'K'}
    if '=' in move:
        parts = move.split('=')
        if len(parts) == 2 and parts[1] in piece_map:
            move = parts[0] + '=' + piece_map[parts[1]]
    if move and move[0] in piece_map and '=' not in move[:move.find('=') if '=' in move else len(move)]:
        move = piece_map[move[0]] + move[1:]
    return move

def convert_english_to_french_notation(move):
    if not move:
        return move
    piece_map = {'Q': 'D', 'N': 'C', 'B': 'F', 'R': 'T', 'K': 'R'}
    if move[0] in piece_map:
        move = piece_map[move[0]] + move[1:]
    if '=' in move:
        parts = move.split('=')
        if len(parts) == 2 and parts[1] in piece_map:
            move = parts[0] + '=' + piece_map[parts[1]]
    return move

def parse_moves(coups_str):
    pattern = r'(\d+)\.\s*([^\s]+)(?:\s+([^\s]+))?'
    matches = re.findall(pattern, coups_str)
    moves = []
    for num, white, black in matches:
        white_raw = white.strip()
        white_san = convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', white_raw))
        moves.append({"raw": white_raw, "san": white_san, "move_number": int(num), "color": "white"})
        if black:
            black_raw = black.strip()
            black_san = convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', black_raw))
            moves.append({"raw": black_raw, "san": black_san, "move_number": int(num), "color": "black"})
    return moves

def get_eval_value(eval_dict, current_board=None):
    """Extrait la valeur mathématique absolue (perspective Blancs) avec lissage des mats."""
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
        if val > 0:
            return 10000 - val
        elif val < 0:
            return -10000 - val
        else:
            return 0
            
    return val

def remove_special_chars(input_string):
    translator = str.maketrans('', '', string.punctuation.replace('-', ''))
    no_special_chars = input_string.translate(translator)
    return no_special_chars

# =====================================================================
# GESTIONNAIRE STOCKFISH
# =====================================================================
class StockfishAnalyzer:
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.engine = None
            cls._instance._init_attempted = False
        return cls._instance
    
    def get_engine(self):
        if not STOCKFISH_AVAILABLE: return None
        if self._init_attempted: return self.engine
        
        self._init_attempted = True
        try:
            stockfish_path = None
            local_sf = os.path.join(os.path.dirname(__file__), "stockfish", "stockfish", "stockfish-ubuntu-x86-64-avx2")
            if os.path.exists(local_sf): stockfish_path = local_sf
            
            if not stockfish_path:
                import shutil
                stockfish_path = shutil.which("stockfish")
            
            if stockfish_path:
                self.engine = Stockfish(path=stockfish_path, depth=15, parameters={"Threads": 4, "Hash": 512})
            else:
                self.engine = Stockfish(depth=15, parameters={"Threads": 4, "Hash": 512})
        except Exception as e:
            self.engine = None
        return self.engine
    
    def analyze_move(self, board, move_san):
        engine = self.get_engine()
        if not engine: return None, None, None
        
        try:
            engine.set_fen_position(board.fen())
            eval_before = engine.get_evaluation()
            
            move_obj = board.parse_san(move_san)
            board.push(move_obj)
            
            engine.set_fen_position(board.fen())
            eval_after = engine.get_evaluation()
            board.pop()
            
            return eval_before, eval_after, move_obj
        except Exception:
            return None, None, None
    
    def get_best_move_with_eval(self, board):
        engine = self.get_engine()
        if not engine: return None, None, None
        try:
            engine.set_fen_position(board.fen())
            best_move_uci = engine.get_best_move() 
            if not best_move_uci: return None, None, None
            
            move_obj = board.parse_uci(best_move_uci)
            best_move_san_en = board.san(move_obj) 
            best_move_french = convert_english_to_french_notation(best_move_san_en) 
            
            board_copy = board.copy()
            board_copy.push(move_obj)
            engine.set_fen_position(board_copy.fen())
            best_eval = engine.get_evaluation()
            
            return best_move_french, best_eval, best_move_uci
        except Exception:
            return None, None, None

# =====================================================================
# CHESSBOARD FLOWABLE
# =====================================================================
class ChessboardFlowable(Flowable):
    def __init__(self, fen, size=150, fleches_defense=None, fleches_menace=None, orientation=chess.WHITE):
        Flowable.__init__(self)
        self.fen = fen
        self.size = size
        self.fleches_defense = fleches_defense or []
        self.fleches_menace = fleches_menace or []
        self.orientation = orientation

    def wrap(self, availWidth, availHeight): return self.size, self.size

    def draw(self):
        try:
            if not self.fen: return
            board = chess.Board(self.fen)
            arrows = []
            for notation in self.fleches_menace:
                try: arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:]), color="#FF0000"))
                except ValueError: pass
            for notation in self.fleches_defense:
                try: arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:]), color="#00AA00"))
                except ValueError: pass

            svg = chess.svg.board(board=board, size=self.size, arrows=arrows, orientation=self.orientation)
            drawing = svg2rlg(StringIO(svg))
            if drawing: renderPDF.draw(drawing, self.canv, 0, 0)
        except Exception: pass

# =====================================================================
# ANALYSE TACTIQUE ET APPEL LLM
# =====================================================================

def get_piece_name_fr(piece):
    if not piece:
        return "Pièce"
    names = {
        chess.PAWN: "Pion",
        chess.KNIGHT: "Cavalier",
        chess.BISHOP: "Fou",
        chess.ROOK: "Tour",
        chess.QUEEN: "Dame",
        chess.KING: "Roi"
    }
    return names.get(piece.piece_type, "Pièce")

def detect_tactics(board_before, move_obj):
    tactics = []
    moving_piece = board_before.piece_at(move_obj.from_square)
    moving_piece_name = get_piece_name_fr(moving_piece)
    to_square_name = chess.square_name(move_obj.to_square)
    
    if board_before.is_capture(move_obj):
        captured_piece = board_before.piece_at(move_obj.to_square)
        if captured_piece:
            captured_name = get_piece_name_fr(captured_piece)
            tactics.append(f"Capture de {captured_name} par {moving_piece_name} en {to_square_name}")
        else:
            tactics.append(f"Capture en passant par {moving_piece_name} en {to_square_name}")
    
    board_after = board_before.copy()
    board_after.push(move_obj)
    
    if board_after.is_checkmate():
        tactics.append(f"Mat par {moving_piece_name} en {to_square_name}")
    elif board_after.is_check():
        defender_color = board_after.turn
        attacker_color = not defender_color
        king_sq = board_after.king(defender_color)
        checkers = board_after.attackers(attacker_color, king_sq)
        
        if move_obj.to_square not in checkers and len(checkers) > 0:
            checker_sq = list(checkers)[0]
            checker_piece = board_after.piece_at(checker_sq)
            checker_name = get_piece_name_fr(checker_piece)
            tactics.append(f"Échec à la découverte par {checker_name} (démasqué par {moving_piece_name})")
        elif len(checkers) > 1:
            tactics.append(f"Échec double impliquant {moving_piece_name} en {to_square_name}")
        else:
            tactics.append(f"Échec par {moving_piece_name} en {to_square_name}")
        
    if not board_after.is_checkmate():
        attacks = board_after.attacks(move_obj.to_square)
        targets = []
        for sq in attacks:
            piece = board_after.piece_at(sq)
            if piece and piece.color == board_after.turn and piece.piece_type != chess.PAWN:
                targets.append(f"{get_piece_name_fr(piece)} en {chess.square_name(sq)}")
        
        if len(targets) > 1:
            targets_str = ", ".join(targets)
            tactics.append(f"Fourchette par {moving_piece_name} en {to_square_name} sur : {targets_str}")

    defender_color = board_after.turn
    pinned_pieces = []
    for sq in chess.SQUARES:
        piece = board_after.piece_at(sq)
        if piece and piece.color == defender_color:
            if board_after.is_pinned(defender_color, sq):
                if not board_before.is_pinned(defender_color, sq):
                    pinned_pieces.append(f"{get_piece_name_fr(piece)} en {chess.square_name(sq)}")
                    
    if pinned_pieces:
        tactics.append(f"Clouage imposé sur : {', '.join(pinned_pieces)}")

    return " | ".join(tactics) if tactics else "Développement"


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
        if mate_in > 0:
            return f"Mat en {mate_in} en votre faveur"
        elif mate_in < 0:
            return f"Mat en {abs(mate_in)} contre vous"
        else:
            return "Échec et Mat"
    else:
        cp_val = (val * player_multiplier) / 100.0
        return f"{cp_val:+.1f}"

def generate_move_comment(move_raw, move_san, board_state, is_trap=False):
    """Orchestre l'analyse Stockfish, la détection tactique et la rédaction par Ollama."""
    raw = remove_special_chars(move_raw.strip())
    board = chess.Board(board_state.fen())
    turn_color = "Blancs" if board.turn == chess.WHITE else "Noirs"
    
    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine()
    
    if engine:
        try:
            eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
            best_move_fr, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
            
            if eval_before and eval_after and best_move_fr:
                board_after = board.copy()
                board_after.push(move_obj)
                
                board_best = board.copy()
                if best_uci:
                    board_best.push(chess.Move.from_uci(best_uci))
                
                # --- CALCUL MATHÉMATIQUE SÉCURISÉ ---
                val_after = get_eval_value(eval_after, board_after)
                val_best = get_eval_value(best_eval, board_best)
                
                player_multiplier = 1 if board.turn == chess.WHITE else -1
                eval_player_after = val_after * player_multiplier
                eval_player_best = val_best * player_multiplier
                
                delta = eval_player_after - eval_player_best
                
                if move_obj and best_uci and move_obj.uci() == best_uci:
                    delta = 0
                
                tactics = detect_tactics(board, move_obj)
                
                # --- NOUVEAUX SEUILS OPTIMISÉS ---
                if delta > -10:  # Tolérance de 0.1 pion (négligeable)
                    status = "C'est un excellent coup, le plus précis pour maintenir l'avantage."
                elif delta <= -300:
                    status = "C'est une gaffe majeure entraînant une perte catastrophique."
                elif delta <= -150:
                    status = "C'est une erreur sérieuse qui fait perdre un avantage significatif."
                elif delta <= -80:
                    status = "C'est une imprécision qui dégrade légèrement la position."
                elif delta <= -30:
                    status = "C'est un coup jouable, mais il existe une alternative légèrement plus précise."
                else:
                    status = "C'est un coup solide et tout à fait correct."
                
                # Formatage du coup alternatif de manière plus naturelle
                if raw != best_move_fr and delta != 0:
                    better_move_comment = f" (L'alternative conseillée était {best_move_fr})"
                else:
                    better_move_comment = ""
                    
                # --- GESTION CONDITIONNELLE DE L'ALTERNATIVE ---
                if raw != best_move_fr and delta < -20: # On n'affiche l'alternative que si l'erreur est réelle
                    alt_context = f"- Meilleure alternative : {best_move_fr}\n"
                    alt_rule = "5. Mentionne brièvement la 'Meilleure alternative'.\n"
                else:
                    alt_context = ""
                    alt_rule = ""

                # --- PROMPT STRICT AVEC EXEMPLES (FEW-SHOT) ---
                prompt = f"""Tu es une IA de résumé factuel. Ton rôle est de traduire les faits fournis en une phrase pédagogique simple.

                RÈGLES D'OR :
                1. N'utilise QUE les informations fournies dans la section FAITS.
                2. NE PAS inventer de stratégies, de menaces ou de justifications qui ne sont pas explicitement listées.
                3. Si une tactique est "Développement", ne cherche pas à justifier une attaque inexistante.
                4. Rédige en français, 1 à 2 phrases max.{alt_rule}

                EXEMPLES DE RÉPONSE :
                - FAITS : Coup: e4, Qualité: Excellent, Tactique: Positionnel/Développement.
                RÉPONSE : e4 est un excellent coup qui favorise une bonne position et le développement.
                - FAITS : Coup: Cxf7, Qualité: Bon, Tactique: Fourchette sur Dame et Tour.
                RÉPONSE : Cxf7 est un bon coup tactique créant une fourchette menaçant la dame et la tour adverses.

                FAITS SUR LA POSITION :
                - Joueur : {turn_color}
                - Coup joué : {raw}
                {alt_context}- Qualité du coup : {status}
                - Événement tactique : {tactics}

                RÉPONSE :
                """
                
                try:
                    print(f"  [LLM] Analyse du coup {raw} à l'aide du prompt optimisé...")
                    result = ollama.generate(
                        model=OLLAMA_MODEL,
                        prompt=prompt
                    )
                    if result and hasattr(result, 'response'):
                        comment = result['response'].strip()
                        comment = comment.replace("\n", " ")
                        print(f"  [LLM] Commentaire généré :\n    {comment}")
                        return comment
                except requests.exceptions.RequestException as e:
                    print(f"  [AVERTISSEMENT] Ollama injoignable sur {OLLAMA_URL}: {str(e)}. Passage au fallback.")
                    
                if delta < -50:
                    return "Coup très mauvais : menace grave non évitée."
                elif delta == 0 or delta > -10:
                    return "Coup excellent : maintient la pression."
                else:
                    return "Coup neutre : pas de menace immédiate."
            
            return "Analyse incomplète : données manquantes."
        
        except Exception as e:
            print(f"  [ERREUR] Analyse Stockfish échouée : {str(e)}. Passage au fallback.")
            return "Analyse impossible : erreur de calcul."
    
    if "x" in raw:
        return "Coup de prise : attention à la position des pièces."
    elif "+" in raw:
        return "Coup de mat : menace immédiate."
    else:
        return "Coup neutre : pas de menace immédiate."
