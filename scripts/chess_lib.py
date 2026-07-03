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
import sys
from datetime import datetime
from io import StringIO
from reportlab.platypus import Flowable
from reportlab.lib import colors
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

# =====================================================================
# SYSTEME DE LOGS HARMONISÉ
# =====================================================================
DEBUG_LEVEL = 0  # 0: Pas de verbose (ESSENTIAL), 1: Info (INFO), 2: Debug (DEBUG)

def set_debug_enabled(enabled=True, level=1):
    global DEBUG_LEVEL
    if not enabled:
        DEBUG_LEVEL = 0
    else:
        try:
            DEBUG_LEVEL = int(level)
        except (TypeError, ValueError):
            DEBUG_LEVEL = 1
    if DEBUG_LEVEL < 0: DEBUG_LEVEL = 0
    if DEBUG_LEVEL > 2: DEBUG_LEVEL = 2

def debug_log(message, level="INFO"):
    normalized_level = str(level).upper()
    
    if DEBUG_LEVEL == 0 and normalized_level not in ["ALWAYS", "ERROR", "WARNING", "ESSENTIAL"]:
        return
    if DEBUG_LEVEL == 1 and normalized_level not in ["ALWAYS", "ERROR", "WARNING", "ESSENTIAL", "INFO"]:
        return
        
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"
    sys.stdout.write(f"[{timestamp}][{normalized_level}] {message}\n")
    sys.stdout.flush()

try:
    from stockfish import Stockfish
    STOCKFISH_AVAILABLE = True
except ImportError:
    STOCKFISH_AVAILABLE = False
    debug_log("Stockfish non disponible. Les commentaires seront générés sans analyse.", "WARNING")

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
                debug_log("Le serveur Ollama est déjà en cours d'exécution.", "INFO")
                return
        except Exception as e:
            debug_log(f"Erreur lors de la vérification du serveur Ollama: {e}", "ERROR")
            return

        debug_log("Démarrage du serveur Ollama en arrière-plan...", "INFO")
        try:
            # Démarrage du serveur Ollama via la librairie
            self.process = ollama.run()
            self.is_managed_by_us = True
        except FileNotFoundError:
            debug_log("Ollama n'est pas installé ou non trouvé dans le PATH.", "ERROR")
            return

    def stop(self):
        # 1. Forcer le déchargement immédiat du modèle de la VRAM
        debug_log(f"Nettoyage : Déchargement du modèle {OLLAMA_MODEL} de la VRAM...", "ESSENTIAL")
        try:
            ollama.stop()
        except Exception as e:
            debug_log(f"Erreur lors du déchargement du modèle: {e}", "ERROR")
        
        # 2. Tuer le processus serveur uniquement si notre script l'a démarré
        if self.is_managed_by_us and self.process:
            try:
                self.process.kill()
            except Exception as e:
                debug_log(f"Erreur lors de la fermeture du processus: {e}", "ERROR")

# =====================================================================
# COULEURS (Charte Graphique Commune)
# =====================================================================
COLOR_PRIMARY = colors.HexColor("#1e293b")
COLOR_SECONDARY = colors.HexColor("#0284c7")
COLOR_TEXT = colors.HexColor("#334155")
COLOR_BG_LIGHT = colors.HexColor("#f8fafc")
COLOR_BORDER = colors.HexColor("#e2e8f0")
COLOR_MINT = colors.HexColor("#0f766e")

DEFAULT_STOCKFISH_DEPTH = 18

# =====================================================================
# FONCTIONS DE TRADUCTION ET UTILITAIRES
# =====================================================================
def resolve_stockfish_depth(explicit_depth=None):
    if explicit_depth is not None:
        return int(explicit_depth)
    return DEFAULT_STOCKFISH_DEPTH

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
    if not move: return move
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

def remove_special_chars(input_string):
    translator = str.maketrans('', '', string.punctuation.replace('-', ''))
    return input_string.translate(translator)

# =====================================================================
# GESTIONNAIRE STOCKFISH INCÉMENTAL (AVEC CACHE FEN)
# =====================================================================
class StockfishAnalyzer:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.engine = None
            cls._instance._init_attempted = False
            cls._instance._eval_cache = {}
            cls._instance._best_move_cache = {}
        return cls._instance
    
    def get_engine(self, depth=None):
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
            
            depth = resolve_stockfish_depth(explicit_depth=depth)
            if stockfish_path:
                self.engine = Stockfish(path=stockfish_path, depth=depth, parameters={"Threads": 12, "Hash": 4096})
            else:
                self.engine = Stockfish(depth=depth, parameters={"Threads": 12, "Hash": 4096})
        except Exception:
            self.engine = None
        return self.engine

    def _get_cached_eval(self, fen):
        if fen in self._eval_cache:
            return self._eval_cache[fen]
        self.engine.set_fen_position(fen)
        evaluation = self.engine.get_evaluation()
        self._eval_cache[fen] = evaluation
        return evaluation

    def _get_cached_best_move(self, fen):
        if fen in self._best_move_cache:
            return self._best_move_cache[fen]
        self.engine.set_fen_position(fen)
        best_move = self.engine.get_best_move()
        self._best_move_cache[fen] = best_move
        return best_move
    
    def analyze_move(self, board, move_san):
        engine = self.get_engine()
        if not engine: return None, None, None
        try:
            fen_before = board.fen()
            eval_before = self._get_cached_eval(fen_before)
            move_obj = board.parse_san(move_san)
            board.push(move_obj)
            fen_after = board.fen()
            eval_after = self._get_cached_eval(fen_after)
            board.pop()
            return eval_before, eval_after, move_obj
        except Exception:
            return None, None, None
    
    def get_best_move_with_eval(self, board):
        engine = self.get_engine()
        if not engine: return None, None, None
        try:
            fen = board.fen()
            best_move_uci = self._get_cached_best_move(fen) 
            if not best_move_uci: return None, None, None
            move_obj = board.parse_uci(best_move_uci)
            best_move_san_en = board.san(move_obj) 
            best_move_french = convert_english_to_french_notation(best_move_san_en) 
            board_copy = board.copy()
            board_copy.push(move_obj)
            best_eval = self._get_cached_eval(board_copy.fen())
            return best_move_french, best_eval, best_move_uci
        except Exception:
            return None, None, None

    def clear_cache(self):
        self._eval_cache.clear()
        self._best_move_cache.clear()

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
    if not piece: return "Pièce"
    names = {
        chess.PAWN: "Pion", chess.KNIGHT: "Cavalier", chess.BISHOP: "Fou",
        chess.ROOK: "Tour", chess.QUEEN: "Dame", chess.KING: "Roi"
    }
    return names.get(piece.piece_type, "Pièce")

def detect_tactics(board_before, move_obj, eval_after=None, future_moves=None):
    tactics = []
    moving_piece = board_before.piece_at(move_obj.from_square)
    moving_piece_name = get_piece_name_fr(moving_piece)
    to_square_name = chess.square_name(move_obj.to_square)
    
    # ==========================================
    # 1. ANALYSE STATIQUE (python-chess)
    # ==========================================
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
            # On cherche les pièces adverses attaquées (hors pions pour de vraies fourchettes)
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

    # ==========================================
    # 2. ANALYSE PROFONDE (Stockfish)
    # ==========================================
    if eval_after and not board_after.is_checkmate():
        # Normalisation du dictionnaire/objet d'évaluation Stockfish
        if hasattr(eval_after, 'value'):
            val = eval_after.value if eval_after.value is not None else 0
            t = getattr(eval_after, 'type', 'cp')
        else:
            val = eval_after.get('value', 0) if isinstance(eval_after, dict) else 0
            t = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else 'cp'

        # Définition de la perspective (positif = bon pour celui qui vient de jouer)
        player_multiplier = 1 if board_before.turn == chess.WHITE else -1

        if t == 'mate':
            mate_in = val * player_multiplier
            # On cible les mats forcés à très court terme (1 à 3 coups max)
            if 0 < mate_in <= 3: tactics.append(f"Rend un mat inévitable en {mate_in} coup(s)")
            elif -3 <= mate_in < 0: tactics.append(f"Gaffe autorisant un mat adverse en {abs(mate_in)} coup(s)")
        elif t == 'cp':
            cp_val = val * player_multiplier
            if cp_val >= 300 and "Capture" not in " ".join(tactics):
                tactics.append("Prépare un gain matériel décisif imminent")
            elif cp_val <= -300:
                queen_lost = False
                seq_eng = []
                seq_fr = []
                
                # S'il y a un différentiel proche de la valeur d'une Dame
                if cp_val <= -700:
                    sim_board = board_after.copy()
                    analyzer = StockfishAnalyzer()
                    sf = analyzer.get_engine()
                    original_color = board_after.turn 
                    
                    if sf:
                        # Simulation des 4 prochains demi-coups (2 coups)
                        for _ in range(4):
                            if sim_board.is_game_over(): break
                            sf.set_fen_position(sim_board.fen())
                            best_uci = sf.get_best_move()
                            if not best_uci: break
                            
                            move_obj_sim = sim_board.parse_uci(best_uci)
                            target_piece = sim_board.piece_at(move_obj_sim.to_square)
                            
                            if target_piece and target_piece.piece_type == chess.QUEEN and target_piece.color != original_color:
                                queen_lost = True
                                
                            san_eng = sim_board.san(move_obj_sim)
                            seq_eng.append(san_eng)
                            seq_fr.append(convert_english_to_french_notation(san_eng))
                            sim_board.push(move_obj_sim)
                            
                            if queen_lost: break
                            
                if queen_lost:
                    is_in_trap = False
                    if future_moves:
                        match_len = min(len(future_moves), len(seq_eng))
                        # Vérifier si la séquence forcée correspond aux coups restants du piège
                        if match_len > 0 and all(future_moves[i] == seq_eng[i] for i in range(match_len)):
                            is_in_trap = True
                            
                    if is_in_trap:
                        tactics.append("Expose la Dame à une perte matérielle forcée en 2 coups (suite illustrée dans le piège)")
                    else:
                        tactics.append(f"Expose la Dame à une perte matérielle forcée en 2 coups via : {' '.join(seq_fr)}")
                else:
                    tactics.append("Expose le joueur à une lourde perte matérielle (gaffe stratégique)")

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
        if mate_in > 0: return f"Mat en {mate_in} en votre faveur"
        elif mate_in < 0: return f"Mat en {abs(mate_in)} contre vous"
        else: return "Échec et Mat"
    else:
        cp_val = (val * player_multiplier) / 100.0
        return f"{cp_val:+.1f}"

def generate_move_comment(move_raw, move_san, board_state, is_trap=False, future_moves=None):
    """Orchestre l'analyse Stockfish, la détection tactique et la rédaction par Ollama."""
    raw = remove_special_chars(move_raw.strip())
    board = chess.Board(board_state.fen())
    turn_color = "Blancs" if board.turn == chess.WHITE else "Noirs"
    
    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine()
    
    if engine:
        try:
            debug_log(f"Stockfish : Analyse du coup {raw} (Évaluation position)", "INFO")
            eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
            debug_log(f"Stockfish : Évaluation du meilleur coup alternatif pour {raw}", "INFO")
            best_move_fr, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
            
            if eval_before and eval_after and best_move_fr:
                board_after = board.copy()
                board_after.push(move_obj)
                board_best = board.copy()
                if best_uci: board_best.push(chess.Move.from_uci(best_uci))
                
                # --- CALCUL MATHÉMATIQUE SÉCURISÉ ---
                val_after = get_eval_value(eval_after, board_after)
                val_best = get_eval_value(best_eval, board_best)
                
                player_multiplier = 1 if board.turn == chess.WHITE else -1
                eval_player_after = val_after * player_multiplier
                eval_player_best = val_best * player_multiplier
                
                delta = eval_player_after - eval_player_best
                if move_obj and best_uci and move_obj.uci() == best_uci: delta = 0
                
                debug_log(f"Analyse tactique automatique pour {raw}", "DEBUG")
                tactics = detect_tactics(board, move_obj, eval_after, future_moves)
                
                if delta > -10: status = "C'est un bon coup, le plus précis pour maintenir l'avantage."
                elif delta <= -300: status = "C'est une gaffe majeure entraînant une perte catastrophique."
                elif delta <= -150: status = "C'est une erreur sérieuse qui fait perdre un avantage significatif."
                elif delta <= -80: status = "C'est une imprécision qui dégrade légèrement la position."
                elif delta <= -30: status = "C'est un coup jouable, mais il existe une alternative légèrement plus précise."
                else: status = "C'est un coup solide et tout à fait correct."
                
                if raw != best_move_fr and delta < -20: 
                    alt_context = f"- Meilleure alternative : {best_move_fr}\n"
                    alt_rule = "6. Mentionne brièvement la 'Meilleure alternative'.\n"
                else:
                    alt_context = ""
                    alt_rule = ""

                # --- PROMPT STRICT AVEC EXEMPLES (FEW-SHOT) ---
                prompt = f"""Tu es une IA de résumé factuel. Ton rôle est de traduire les faits fournis en une phrase pédagogique simple.

                RÈGLES D'OR :
                1. RÈGLE ABSOLUE : Si le "Coup joué" contient le symbole '#', ta réponse doit STRICTEMENT se limiter à la phrase : "Échec et mat. La partie est terminée." Interdiction de faire d'autres commentaires.
                2. N'utilise QUE les informations fournies dans la section FAITS.
                3. NE PAS inventer de stratégies, de menaces ou de justifications qui ne sont pas explicitement listées.
                4. Si une tactique est "Développement", ne cherche pas à justifier une attaque inexistante.
                5. Rédige en français, 1 à 2 phrases max.{alt_rule}

                EXEMPLES DE RÉPONSE :
                - FAITS : 
                  Coup joué : e4
                  Qualité du coup : C'est un bon coup, le plus précis pour maintenir l'avantage.
                  Événement tactique : Développement
                RÉPONSE : e4 est un bon coup qui permet de maintenir l'avantage et favorise le développement.
                
                - FAITS : 
                  Coup joué : Cxf7
                  Qualité du coup : C'est un bon coup, le plus précis pour maintenir l'avantage.
                  Événement tactique : Capture de Pion par Cavalier en f7 | Fourchette par Cavalier en f7 sur : Dame en d8, Tour en h8
                RÉPONSE : Cxf7 est un bon coup tactique capturant un pion et créant une fourchette sur la Dame en d8 et la Tour en h8.
                
                - FAITS : 
                  Coup joué : Dxb7#
                  Qualité du coup : C'est un bon coup, le plus précis pour maintenir l'avantage.
                  Événement tactique : Capture de Pion par Dame en b7 | Mat par Dame en b7
                RÉPONSE : Échec et mat. La partie est terminée.

                FAITS SUR LA POSITION :
                - Joueur : {turn_color}
                - Coup joué : {raw}
                {alt_context}- Qualité du coup : {status}
                - Événement tactique : {tactics}

                RÉPONSE :
                """
                
                try:
                    debug_log(f"Prompt envoyé au LLM pour le coup {raw} :\n{prompt}", "DEBUG")
                    debug_log(f"Appel d'Ollama ({OLLAMA_MODEL}) pour rédiger le commentaire de {raw}...", "INFO")
                    result = ollama.generate(model=OLLAMA_MODEL, prompt=prompt)
                    debug_log(f"Retour brut d'Ollama : {result}", "DEBUG")
                    
                    if result and hasattr(result, 'response'):
                        comment = result['response'].strip().replace("\n", " ")
                        debug_log(f"Résultat du prompt LLM pour {raw} : {comment}", "INFO")
                        return comment
                except requests.exceptions.RequestException as e:
                    debug_log(f"Ollama injoignable sur {OLLAMA_URL}: {str(e)}. Fallback.", "WARNING")
                    
                if delta < -50: return "Coup très mauvais : menace grave non évitée."
                elif delta == 0 or delta > -10: return "Coup bon : maintient la pression."
                else: return "Coup neutre : pas de menace immédiate."
            
            return "Analyse incomplète : données manquantes."
        except Exception as e:
            debug_log(f"Analyse Stockfish échouée : {str(e)}. Fallback.", "ERROR")
            return "Analyse impossible : erreur de calcul."
    
    if "x" in raw: return "Coup de prise : attention à la position des pièces."
    elif "+" in raw: return "Coup de mat : menace immédiate."
    else: return "Coup neutre : pas de menace immédiate."
