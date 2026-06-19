import os
import re
import chess
import chess.svg
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

def get_eval_value(eval_dict):
    """Extrait proprement la valeur d'évaluation en gérant les mats."""
    if not eval_dict: return 0
    if hasattr(eval_dict, 'value'):
        val = eval_dict.value if eval_dict.value is not None else 0
        t = getattr(eval_dict, 'type', 'cp')
    else:
        val = eval_dict.get('value', 0) if isinstance(eval_dict, dict) else 0
        t = eval_dict.get('type', 'cp') if isinstance(eval_dict, dict) else 'cp'
    
    if t == 'mate':
        return 10000 if val > 0 else -10000
    return val

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
            
            print("[INFO] Stockfish initialisé avec succès pour l'analyse")
        except Exception as e:
            print(f"[AVERTISSEMENT] Impossible d'initialiser Stockfish: {e}")
            self.engine = None
        return self.engine
    
    def analyze_move(self, board, move_san, depth=15):
        engine = self.get_engine()
        if not engine: return None, None, None
        
        try:
            fen_before = board.fen()
            engine.set_fen_position(fen_before)
            eval_before = engine.get_evaluation()
            
            move_obj = board.parse_san(move_san)
            board.push(move_obj)
            
            fen_after = board.fen()
            engine.set_fen_position(fen_after)
            eval_after = engine.get_evaluation()
            
            board.pop()
            return eval_before, eval_after, move_obj
        except Exception as e:
            print(f"[AVERTISSEMENT] Erreur lors de l'analyse du coup {move_san}: {e}")
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
        except Exception as e:
            print(f"[DEBUG] Erreur recherche du meilleur coup: {e}")
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
        self.error_message = None

    def wrap(self, availWidth, availHeight): return self.size, self.size

    def draw(self):
        try:
            if not self.fen: return
            try: board = chess.Board(self.fen)
            except ValueError: return

            arrows = []
            for notation in self.fleches_menace:
                try:
                    if len(notation) != 4: continue
                    arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:]), color="#FF0000"))
                except ValueError: pass

            for notation in self.fleches_defense:
                try:
                    if len(notation) != 4: continue
                    arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:]), color="#00AA00"))
                except ValueError: pass

            try:
                svg = chess.svg.board(board=board, size=self.size, arrows=arrows, orientation=self.orientation)
                drawing = svg2rlg(StringIO(svg))
                if drawing: renderPDF.draw(drawing, self.canv, 0, 0)
            except Exception: pass
        except Exception: pass

# =====================================================================
# GENERATION DE COMMENTAIRES PEDAGOGIQUES
# =====================================================================
def generate_move_comment(move_raw, move_san, board_state, is_trap=False):
    raw = move_raw.strip()
    raw_clean = re.sub(r'[?!+#x]+', '', raw).strip()
    board = chess.Board(board_state.fen())
    
    if "??" in raw: return "Erreur grave, c'est une gaffe."
    if "?!" in raw: return "Coup douteux. Les réponses existent."
    if "!?" in raw: return "Coup intéressant mais potentiellement risqué, soyez vigilant."
    if "!!" in raw: return "Coup exceptionnel, une trouvaille brillante."
    if "?" in raw: return "Coup douteux ou erreur."
    if "!" in raw: return "Coup fort, bonne découverte tactique."
    if "#" in raw: return "Mat direct, la combinaison fonctionne."
    if "+" in raw: return "Donne échec et met la pression sur le roi."
    
    analyzer = StockfishAnalyzer()
    if analyzer.get_engine():
        eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
        if eval_before and eval_after:
            try:
                val_before = get_eval_value(eval_before)
                val_after = get_eval_value(eval_after)
                
                # L'évaluation est relative au joueur dont c'est le tour.
                # Delta mathématiquement corrigé
                delta = -(val_after + val_before)
                
                # Évaluation absolue pour l'affichage (perspective des blancs)
                abs_eval_after = -val_after if board.turn == chess.WHITE else val_after
                
                # Récupération de l'UCI joué pour la comparaison stricte
                try: played_uci = board.parse_san(move_san).uci()
                except Exception: played_uci = None
                
                if abs(delta) < 20: return f"Coup égal. Évaluation stable ({abs_eval_after/100:+.1f})."
                elif delta > 50: return f"Coup excellent ! Améliore la position ({delta/100:+.1f})."
                elif delta > 20: return f"Coup solide et améliorant. Gain de {delta/100:.1f} de point."
                elif delta < -20:
                    board_copy = chess.Board(board_state.fen())
                    best_move, best_eval, best_move_uci = analyzer.get_best_move_with_eval(board_copy)
                    
                    if best_move and best_eval and played_uci != best_move_uci:
                        best_val = get_eval_value(best_eval)
                        best_delta = -(best_val + val_before)
                        if delta < -50: return f"Coup faible qui détériore la position ({delta/100:+.1f}). Préférez {best_move} ({best_delta/100:+.1f})."
                        return f"Coup questionnable (perte de {abs(delta)/100:.1f}). Meilleur : {best_move} ({best_delta/100:+.1f})."
                    else:
                        if delta < -50: return f"Coup faible qui détériore la position ({delta/100:+.1f})."
                        return f"Coup questionnable (perte de {abs(delta)/100:.1f})."
                else: return f"Coup égal. Évaluation stable ({abs_eval_after/100:+.1f})."
            except Exception as e:
                print(f"[DEBUG] Erreur lors du traitement de l'évaluation: {e}")
    
    if "x" in raw_clean: return "Capture une pièce ou un pion."
    if raw_clean.startswith("D"): return "Développe la Dame pour maintenir l'initiative."
    if raw_clean.startswith("C"): return "Développe le Cavalier vers une case active."
    if raw_clean.startswith("F"): return "Développe le Fou et cible le centre."
    if raw_clean.startswith("T"): return "Développe la Tour, souvent après l'ouverture du jeu."
    if raw_clean.startswith("R"): return "Sécurise le Roi ou prépare la défense."
    if raw_clean in ["e4", "d4", "e5", "d5"]: return "Prend le contrôle du centre."
    if raw_clean and raw_clean[0] in "abcdefgh": return "Avance un pion pour ouvrir le jeu."
    if board.is_check(): return "Ce coup donne échec et met la pression sur l'adversaire."
    
    context = "séquence" if is_trap else "position"
    return f"Coup de développement utile dans cette {context}."
