import os
import re
import json
import chess
import chess.svg
import subprocess
import time
import ollama
import requests
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
OLLAMA_MODEL = "granite3.2:8b"  # Modèle recommandé : qwen2.5:7b, granite3.2:8b

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
            # Vérifie si le serveur tourne déjà (ex: lancé via systemd)
            if ollama.list_models():
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

def get_eval_value(eval_dict):
    """Extrait la valeur d'évaluation absolue du point de vue des Blancs."""
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
def detect_tactics(board_before, move_obj):
    """Analyse le plateau pour extraire le vocabulaire technique (Fourchette, Clouage, etc.)."""
    tactics = []
    
    if board_before.is_capture(move_obj):
        tactics.append("Capture")
    
    board_after = board_before.copy()
    board_after.push(move_obj)
    
    # --- Détection des Échecs et du Mat ---
    if board_after.is_checkmate():
        tactics.append("Mat")
    elif board_after.is_check():
        defender_color = board_after.turn
        attacker_color = not defender_color
        king_sq = board_after.king(defender_color)
        
        checkers = board_after.attackers(attacker_color, king_sq)
        
        if move_obj.to_square not in checkers and len(checkers) > 0:
            tactics.append("Échec à la découverte")
        elif len(checkers) > 1:
            tactics.append("Échec double")
        else:
            tactics.append("Échec")
        
    # --- Détection de Fourchette ---
    if not board_after.is_checkmate():
        attacks = board_after.attacks(move_obj.to_square)
        valuable_targets = 0
        for sq in attacks:
            piece = board_after.piece_at(sq)
            if piece and piece.color == board_after.turn and piece.piece_type != chess.PAWN:
                valuable_targets += 1
        if valuable_targets > 1:
            tactics.append("Fourchette")

    # --- Détection de Clouage (Pin) ---
    defender_color = board_after.turn
    has_new_pin = False
    for sq in chess.SQUARES:
        piece = board_after.piece_at(sq)
        if piece and piece.color == defender_color:
            if board_after.is_pinned(defender_color, sq):
                if not board_before.is_pinned(defender_color, sq):
                    has_new_pin = True
                    break
    if has_new_pin:
        tactics.append("Clouage")

    return ", ".join(tactics) if tactics else "Positionnel/Développement"


def format_eval(val, is_mate):
    if is_mate: return f"Mat en {abs(val)}"
    return f"{val/100:+.1f}"

def generate_move_comment(move_raw, move_san, board_state, is_trap=False):
    """Orchestre l'analyse Stockfish, la détection tactique et la rédaction par Ollama."""
    raw = move_raw.strip()
    board = chess.Board(board_state.fen())
    turn_color = "Blancs" if board.turn == chess.WHITE else "Noirs"
    
    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine()
    
    if engine:
        try:
            eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
            best_move_fr, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
            
            if eval_before and eval_after and best_move_fr:
                val_before = get_eval_value(eval_before)
                val_after = get_eval_value(eval_after)
                
                # Évaluations absolues pour faciliter la compréhension du LLM
                abs_before = val_before if board.turn == chess.WHITE else -val_before
                abs_after = val_after if board.turn == chess.BLACK else -val_after
                
                is_mate_before = eval_before.get('type') == 'mate' if isinstance(eval_before, dict) else getattr(eval_before, 'type', '') == 'mate'
                is_mate_after = eval_after.get('type') == 'mate' if isinstance(eval_after, dict) else getattr(eval_after, 'type', '') == 'mate'
                
                str_before = format_eval(abs_before, is_mate_before)
                str_after = format_eval(abs_after, is_mate_after)
                
                tactics = detect_tactics(board, move_obj)
                
                # --- CALCUL DU DELTA ET VERDICT AFFINÉ ---
                # val_before et val_after sont du point de vue des Blancs (positif = avantage Blanc)
                # On calcule la différence du point de vue du joueur au trait
                if board.turn == chess.WHITE:
                    delta = val_after - val_before
                else:
                    delta = val_before - val_after
                
                # Catégorisation détaillée pour guider le LLM
                if delta <= -300:
                    status = "Gaffe majeure (Perte catastrophique, souvent matérielle ou donne un mat)"
                elif delta <= -150:
                    status = "Gaffe (Grosse erreur, perdant un avantage significatif)"
                elif delta <= -80:
                    status = "Erreur (Coup qui dégrade la position, rate une tactique évidente)"
                elif delta <= -30:
                    status = "Imprécision (Coup sous-optimal, donne une légère opportunité à l'adversaire)"
                elif delta > 50:
                    status = "Coup brillant / Excellent coup (Trouve une ressource inattendue ou punit l'adversaire)"
                else:
                    status = "Bon coup (Développement logique, solide ou positionnel)"
                
                # Prompt dynamique optimisé pour Qwen2.5:7b
                prompt = f"""Tu es un Grand Maître International d'échecs expert en pédagogie.
Ton but est de commenter le coup suivant.

CONTEXTE DE LA POSITION :
- Coup joué : {raw}
- Joué par : {turn_color}
- Évaluation avant : {str_before}
- Évaluation après : {str_after}
- Meilleur coup alternatif : {best_move_fr}
- Verdict : {status}
- Tactique(s) impliquée(s) : {tactics}

INSTRUCTIONS STRICTES :
1. FORMAT : Rédige uniquement le commentaire final. Aucune formule de politesse, d'introduction (ne dis pas "Voici l'explication") ou de conclusion.
2. LANGUE : Rédige en français, avec un style clair, concis et pédagogique. Utilise des phrases simples et directes.
2. REPETITIONS : NE METIONE PAS le Meilleur coup alternatif si c'est le même que le Coup joué.
3. LONGUEUR : 1 ou 2 phrases maximum. Sois percutant et va à l'essentiel.
4. CHIFFRES : Ne mentionne JAMAIS les scores numériques d'évaluation (comme {str_before} ou {str_after}). Traduis-les obligatoirement en mots (ex: "avantage décisif", "position égale", "retournement de situation").
5. ANALYSE : Si le verdict est une erreur ou une gaffe, explique brièvement pourquoi la position est dégradée, et mentionne l'alternative conseillée ({best_move_fr})
6.TACTIQUE : Intègre les éléments tactiques ({tactics}) de façon fluide dans ton explication sans faire de liste.
"""
                
                # Appel à Ollama avec gestion des erreurs
                try:
                    print(f"  [LLM] Analyse du coup {raw}...")
                    result = ollama.generate(
                        model=OLLAMA_MODEL,
                        prompt=prompt
                    )
                    if result and hasattr(result, 'response'):
                        comment = result['response'].strip()
                        # Sécurité pour éviter que le LLM ne bavarde trop
                        return comment.replace("\n", " ")
                except requests.exceptions.RequestException as e:
                    print(f"  [AVERTISSEMENT] Ollama injoignable sur {OLLAMA_URL}: {str(e)}. Passage au fallback classique.")
                    
                # FALLBACK CLASSIQUE (Si Ollama n'est pas disponible)
                if delta < -50:
                    return "Coup très mauvais : menace grave non évitée."
                elif delta > 50:
                    return "Coup excellent : avantage significatif."
                else:
                    return "Coup neutre : pas de menace immédiate."
            
            # Gestion des cas où l'analyse ne retourne pas de données
            return "Analyse incomplète : données manquantes."
        
        except Exception as e:
            print(f"  [ERREUR] Analyse Stockfish échouée : {str(e)}. Passage au fallback.")
            return "Analyse impossible : erreur de calcul."
    
    # FALLBACK SANS STOCKFISH
    if "x" in raw:
        return "Coup de prise : attention à la position des pièces."
    elif "+" in raw:
        return "Coup de mat : menace immédiate."
    else:
        return "Coup neutre : pas de menace immédiate."
