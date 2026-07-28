import json
import chess
import requests
import re
import time
import ollama
from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer

class AIAnalyzer:
    # CORRECTION 2 : Suppression stricte des balises HTML (ex: <b>) dans la banque de Few-Shots
    FEW_SHOT_BANK = {
        "bon_coup": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est un bon coup, le plus précis actuellement. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. C'est le coup le plus précis."}
        ],
        "imprecision": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est une imprécision qui dégrade légèrement la position. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. C'est une imprécision."}
        ],
        "suite_stockfish": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est une gaffe majeure entraînant un mat inévitable contre le joueur. Tactique détectée : Mat inévitable. Séquence prédictive de l'ordinateur : [SÉQUENCE]"},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. C'est une gaffe majeure entraînant un mat inévitable. Séquence prédictive de l'ordinateur : [SÉQUENCE]."}
        ],
        "gaffe_tactique_alternative": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est une gaffe majeure. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. C'est une gaffe majeure."}
        ],
        "erreur_avec_alternative": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est une erreur sérieuse. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. C'est une erreur sérieuse."}
        ],
        "perte_materielle": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est une erreur sérieuse causant une perte matérielle. Tactique détectée : [PIÈCE] en [CASE] est exposée à une perte matérielle en quelques coups."},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. C'est une erreur sérieuse causant une perte matérielle."}
        ],
        "echec_geometrique": [
            {"role": "user", "content": "Coup : [PIÈCE] des [COULEUR] vers la case [CASE]. Évaluation : C'est un bon coup, le plus précis actuellement. Tactique détectée : Échec direct par [PIÈCE] en [CASE]."},
            {"role": "assistant", "content": "La [PIÈCE] s'est déplacée en [CASE]. Elle met le Roi adverse en échec."}
        ]
    }

    @staticmethod
    def query_llm(messages, options=None, context_log="LLM", fallback="", cache_key=None):
        if cache_key:
            from classes.json_cache import CacheManager
            cache_global = CacheManager.load_cache()
            if cache_key in cache_global:
                Logger.debug_log(f"Réponse récupérée depuis le cache pour : {context_log}", "INFO")
                return cache_global[cache_key]
                
        Logger.debug_log(f"Appel d'Ollama ({Config.OLLAMA_MODEL}) pour : {context_log}...", "INFO")
        Logger.debug_log(f"Prompt envoyé au LLM : {json.dumps(messages, ensure_ascii=False)}", "DEBUG")
        
        # CORRECTION 2 : Gestion robuste des exceptions et mécanisme de retry (erreurs 500, CUDA, connexion)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = ollama.chat(
                    model=Config.OLLAMA_MODEL,
                    messages=messages,
                    options=options or {'temperature': 0.0}
                )
                if result and 'message' in result and 'content' in result['message']:
                    content = result['message']['content']
                    
                    refusals_regex = r"(?i)(je suis désolé|désolé|en tant qu'IA|en tant que modèle|je ne peux pas répondre|je ne suis pas autorisé)"
                    if re.search(refusals_regex, content):
                        Logger.debug_log(f"Refus IA intercepté ({context_log}). Fallback appliqué.", "WARNING")
                        Logger.debug_log(f"Réponse brute du LLM ayant entraîné le refus : {content}", "DEBUG")
                        return fallback
                    
                    content = re.sub(r'\(?Note\s*:.*?\)?', '', content, flags=re.IGNORECASE).strip()
                    content = re.sub(r'\n+', ' ', content)
                    content = content.strip(' "\'')
                    content = content.replace("Commentaire : ", "").replace("Commentaire :", "").strip()
                    content = re.sub(r'[\$~]', '', content)
                    
                    # Respect strict du lexique français SAN
                    content = re.sub(r'(?i)\bévêques?\b', 'Fou', content)
                    content = re.sub(r'(?i)\bécureuils?\b', 'Pion', content)
                    content = re.sub(r'(?i)\bcarré(s)?\b', r'case\1', content)
                    content = re.sub(r'(?i)\bpiège mortel\b', 'menace critique', content)
                    content = re.sub(r'(?i)\bcheval(aux)?\b', 'Cavalier', content)
                    content = re.sub(r'(?i)\bson tour\b', 'sa Tour', content)
                    content = re.sub(r'(?i)\bson pièce\b', 'sa pièce', content)
                    content = re.sub(r'(?i)\ba déplacé vers\b', 's\'est déplacé vers', content)
                    content = re.sub(r'(?i)attaque directe contre le [a-zA-ZÀ-ÿ]+ (Blanc|Noir) en [a-h][1-8]', 'capture sur la case', content)
                    content = re.sub(r'(?i)attaquant\s+simultanément\s*(?::)?\s*([a-zA-ZÀ-ÿ0-9\s,]+(?:et\s+[a-zA-ZÀ-ÿ0-9\s]+)?)', r'attaquant \1', content)
                    content = re.sub(r'(?i)(mettant|met)\s+en\s+échec\s+(le|la|les)\s+(?!Roi)[a-zA-Z]+', r'attaquant \2', content)
                    content = re.sub(r'\b([L|l])e\s+Tour\b', lambda m: f"{m.group(1)}a Tour", content)
                    content = re.sub(r'\b([L|l])e\s+Dame\b', lambda m: f"{m.group(1)}a Dame", content)
                    content = re.sub(r'(?i)Roi\s+(Blanc|Noir)\s+en\s+[a-h][1-8]', 'Roi adverse', content)
                    content = re.sub(r'\bC-C([a-h][1-8])\b', r'Cavalier en \1', content)
                    content = re.sub(r'\bF-F([a-h][1-8])\b', r'Fou en \1', content)
                    content = re.sub(r'\bT-T([a-h][1-8])\b', r'Tour en \1', content)
                    content = re.sub(r'\bD-D([a-h][1-8])\b', r'Dame en \1', content)
                    content = re.sub(r'\bR-R([a-h][1-8])\b', r'Roi en \1', content)

                    content = content.strip()
                    if not content.endswith('.'):
                        content += '.'

                    Logger.debug_log(f"Résultat brut LLM ({context_log}) : {content}", "DEBUG")
                    
                    if cache_key and content and content != fallback:
                        cache_global = CacheManager.load_cache()
                        cache_global[cache_key] = content
                        CacheManager.save_cache(cache_global)
                        
                    return content
            except (requests.exceptions.RequestException, Exception) as e:
                err_str = str(e)
                is_retryable = any(err in err_str for err in ["500", "CUDA", "connection", "timeout", "Ollama"])
                if is_retryable and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    Logger.debug_log(f"Erreur Ollama temporaire ({err_str}). Nouvelle tentative dans {wait_time}s...", "WARNING")
                    time.sleep(wait_time)
                    continue
                else:
                    Logger.debug_log(f"Erreur Ollama critique ({context_log}) : {err_str}", "ERROR")
                    break
                    
        return fallback

    @staticmethod
    def get_stockfish_theory_summary(opening_name, bad_move, stockfish_line):
        messages = [
            {
                "role": "system", 
                "content": (
                    "Tu es un Analyste Technique d'échecs générant une description purement factuelle. "
                    "RÈGLE STRICTE : Limite ton output à une description séquentielle et factuelle des coups "
                    "(ex: 'Les Noirs jouent Fb6, les Blancs répondent par a4...'). "
                    "INTERDICTION FORMELLE d'inventer des plans stratégiques incohérents ou de générer un narratif unifié."
                )
            },
            {
                "role": "user", 
                "content": (
                    f"Dans l'ouverture '{opening_name}', suite au coup '{bad_move}', "
                    f"l'ordinateur préconise la variante suivante : {stockfish_line}. "
                    "Décris factuellement et séquentiellement cette ligne alternative."
                )
            }
        ]
        
        fallback_text = "Ligne recommandée par le moteur pour rééquilibrer la position."
        content = AIAnalyzer.query_llm(messages, context_log=f"Théorie {opening_name}", fallback=fallback_text, cache_key=None)
        return f"Ligne Stockfish : {stockfish_line}<br/><br/>{content}"

    @staticmethod
    def translate_opening_name(opening_name):
        if not opening_name or opening_name == "Ouverture Inconnue":
            return opening_name

        translations = {
            "Defense": "Défense", "Variation": "Variante", "Attack": "Attaque",
            "Gambit": "Gambit", "System": "Système", "Accepted": "Accepté",
            "Declined": "Refusé", "English": "Anglaise", "Opening": "Ouverture", 
            "Symmetrical": "Symétrique", "Bishop's": "du Fou", "King's": "du Roi", 
            "Queen's": "de la Dame", "Sicilian": "Sicilienne", "Zukertort": "de Zukertort", 
            "Tennison": "Tennison", "Jalalabad": "Jalalabad"
        }

        result = opening_name
        for eng, fr in translations.items():
            result = result.replace(eng, fr)
            
        result = result.replace(":", " : ").replace("  ", " ")
        result = re.sub(r'\b(\w+)\s+(Défense|Ouverture|Variante|Attaque|Gambit|Système)\b', r'\2 \1', result, flags=re.IGNORECASE)

        result = result.title()
        mots_de_liaison = [" De ", " Du ", " Des ", " La ", " Le ", " Les ", " À ", " En ", " Et ", " D'"]
        for mot in mots_de_liaison:
            result = result.replace(mot, mot.lower())
            
        result = re.sub(r'\s+', ' ', result)
        result = result.replace(" :", " :").replace(":", " : ")
        result = re.sub(r'\s+', ' ', result).strip()

        return result

    @staticmethod
    def detect_tactics(board_before, move_obj, eval_after=None, future_moves=None):
        Logger.debug_log(f"Détection des tactiques pour le coup {move_obj.uci()}...", "INFO")
        tactics = []
        moving_piece = board_before.piece_at(move_obj.from_square)
        moving_piece_name = ChessUtils.get_piece_name_fr(moving_piece)
        to_square_name = chess.square_name(move_obj.to_square)
        
        if board_before.is_capture(move_obj):
            captured_piece = board_before.piece_at(move_obj.to_square)
            if captured_piece:
                captured_name = ChessUtils.get_piece_name_fr(captured_piece)
                tactics.append(f"Capture de {captured_name} par {moving_piece_name} en {to_square_name}")
            else:
                tactics.append(f"Capture en passant par {moving_piece_name} en {to_square_name}")
        
        board_after = board_before.copy()
        board_after.push(move_obj)
        
        if board_after.is_checkmate():
            tactics.append(f"Mat par {moving_piece_name} en {to_square_name}")
        else:
            if board_after.is_check():
                defender_color = board_after.turn
                attacker_color = not defender_color
                king_sq = board_after.king(defender_color)
                checkers = board_after.attackers(attacker_color, king_sq)
                
                if move_obj.to_square not in checkers and len(checkers) > 0:
                    checker_sq = list(checkers)[0]
                    checker_piece = board_after.piece_at(checker_sq)
                    checker_name = ChessUtils.get_piece_name_fr(checker_piece)
                    tactics.append(f"Découverte d'une attaque menant à un échec par {checker_name} (démasqué par {moving_piece_name})")
                elif len(checkers) > 1:
                    tactics.append(f"Échec double impliquant {moving_piece_name} en {to_square_name}")
                else:
                    tactics.append(f"Échec direct par {moving_piece_name} en {to_square_name}")
                
            # CORRECTION 1.3 : Algorithme de fourchette corrigé (ciblage des pièces adverses != turn, restriction aux pièces majeures/mineures, max 3 cibles)
            attacks = board_after.attacks(move_obj.to_square)
            targets = []
            for sq in attacks:
                piece = board_after.piece_at(sq)
                if piece and piece.color != board_after.turn and piece.piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.KING]:
                    targets.append(f"{ChessUtils.get_piece_name_fr(piece)} en {chess.square_name(sq)}")
            
            if 2 <= len(targets) <= 3:
                targets_str = ", ".join(targets)
                tactics.append(f"{moving_piece_name} en {to_square_name} réalise une fourchette attaquant simultanément : {targets_str}")

            defender_color = board_after.turn
            pinned_pieces = []
            for sq in chess.SQUARES:
                piece = board_after.piece_at(sq)
                if piece and piece.color == defender_color:
                    if board_after.is_pinned(defender_color, sq):
                        if not board_before.is_pinned(defender_color, sq):
                            pinned_pieces.append(f"{ChessUtils.get_piece_name_fr(piece)} en {chess.square_name(sq)}")
                            
            if pinned_pieces:
                tactics.append(f"Le coup crée un clouage immobilisant : {', '.join(pinned_pieces)}")

            if eval_after:
                if hasattr(eval_after, 'value'):
                    val = eval_after.value if eval_after.value is not None else 0
                    t = getattr(eval_after, 'type', 'cp')
                else:
                    val = eval_after.get('value', 0) if isinstance(eval_after, dict) else 0
                    t = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else 'cp'

                player_multiplier = 1 if board_before.turn == chess.WHITE else -1

                if t == 'mate':
                    sf = StockfishAnalyzer().get_engine()
                    if sf:
                        sf.set_fen_position(board_after.fen())
                        sim_board = board_after.copy()
                        seq_fr = []
                        seq_eng = []
                        for _ in range(abs(val)): 
                            best_uci = sf.get_best_move()
                            if not best_uci: break
                            move_obj_sim = sim_board.parse_uci(best_uci)
                            san_fr = ChessUtils.convert_english_to_french_notation(sim_board.san(move_obj_sim))
                            seq_fr.append(san_fr)
                            san_eng = sim_board.san(move_obj_sim)
                            seq_eng.append(san_eng)
                            sim_board.push(move_obj_sim)
                            sf.set_fen_position(sim_board.fen())

                        is_in_trap = False
                        if future_moves:
                            match_len = min(len(future_moves), len(seq_eng))
                            if match_len > 0 and all(future_moves[i] == seq_eng[i] for i in range(match_len)):
                                is_in_trap = True
                                
                        if is_in_trap:
                            tactics.append(f"Mat inévitable (suite illustrée)")
                        else:
                            tactics.append(f"Mat inévitable via : {' '.join(seq_fr)}")
                    
                elif t == 'cp':
                    cp_val = val * player_multiplier
                    if cp_val >= 300 and not any("Capture" in t for t in tactics):
                        tactics.append("Prépare un gain matériel décisif imminent")
                    elif cp_val <= -300:
                        piece_lost = None
                        lost_square = None
                        seq_eng = []
                        seq_fr = []
                        
                        sim_board = board_after.copy()
                        analyzer = StockfishAnalyzer()
                        sf = analyzer.get_engine()
                        original_color = board_after.turn 
                        
                        if sf:
                            for _ in range(6):
                                if sim_board.is_game_over(): break
                                sf.set_fen_position(sim_board.fen())
                                best_uci = sf.get_best_move()
                                if not best_uci: break
                                
                                move_obj_sim = sim_board.parse_uci(best_uci)
                                target_piece = sim_board.piece_at(move_obj_sim.to_square)
                                
                                if target_piece and target_piece.color != original_color:
                                    pt = target_piece.piece_type
                                    is_new_loss = False
                                    if pt == chess.QUEEN:
                                        piece_lost = "Dame"
                                        is_new_loss = True
                                    elif pt == chess.ROOK and piece_lost != "Dame":
                                        piece_lost = "Tour"
                                        is_new_loss = True
                                    elif pt == chess.BISHOP and piece_lost not in ["Dame", "Tour"]:
                                        piece_lost = "Fou"
                                        is_new_loss = True
                                    elif pt == chess.KNIGHT and piece_lost not in ["Dame", "Tour", "Fou"]:
                                        piece_lost = "Cavalier"
                                        is_new_loss = True
                                        
                                    if is_new_loss:
                                        lost_square = chess.square_name(move_obj_sim.to_square)
                                        
                                san_eng = sim_board.san(move_obj_sim)
                                seq_eng.append(san_eng)
                                seq_fr.append(ChessUtils.convert_english_to_french_notation(san_eng))
                                sim_board.push(move_obj_sim)
                                
                                if piece_lost == "Dame": break
                                
                        if piece_lost:
                            is_in_trap = False
                            if future_moves:
                                match_len = min(len(future_moves), len(seq_eng))
                                if match_len > 0 and all(future_moves[i] == seq_eng[i] for i in range(match_len)):
                                    is_in_trap = True
                                    
                            loss_desc = f"{piece_lost} en {lost_square} est exposée à une perte matérielle en quelques coups"
                            if is_in_trap:
                                tactics.append(f"{loss_desc} (suite illustrée)")
                            else:
                                tactics.append(f"{loss_desc} via : {' '.join(seq_fr)}")
                        else:
                            tactics.append("Expose le joueur à une lourde perte matérielle")
                        
        tactics_comment = " ; ".join(tactics) if tactics else "Déplacement standard"
        Logger.debug_log(f"Événement détecté pour le coup : {tactics_comment}", "INFO")
        return tactics_comment

    @staticmethod
    def generate_move_comment(move_raw, move_san, board_state, is_trap=False, played_continuation=None, best_alternative=None):
        raw = ChessUtils.remove_special_chars(move_raw.strip())
        board = chess.Board(board_state.fen())
        turn_color = "Blancs" if board.turn == chess.WHITE else "Noirs"
        
        analyzer = StockfishAnalyzer()
        engine = analyzer.get_engine()
        
        if engine:
            try:
                Logger.debug_log(f"Stockfish : Analyse du coup {raw}", "INFO")
                eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
                Logger.debug_log(f"Stockfish : Évaluation du meilleur coup alternatif pour {raw}", "INFO")
                best_move_fr, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
                
                if eval_before and eval_after and move_obj:
                    board_after = board.copy()
                    board_after.push(move_obj)
                    board_best = board.copy()
                    if best_uci: board_best.push(chess.Move.from_uci(best_uci))
                    
                    val_before = ChessUtils.get_eval_value(eval_before, board)
                    val_after = ChessUtils.get_eval_value(eval_after, board_after)
                    val_best = ChessUtils.get_eval_value(best_eval, board_best)
                    
                    player_multiplier = 1 if board.turn == chess.WHITE else -1
                    eval_player_before = val_before * player_multiplier
                    eval_player_after = val_after * player_multiplier
                    eval_player_best = val_best * player_multiplier
                    
                    delta = eval_player_after - eval_player_best
                    swing = eval_player_after - eval_player_before
                    if move_obj and best_uci and move_obj.uci() == best_uci: delta = 0

                    san_eng = board.san(move_obj) 
                    san_fr = ChessUtils.convert_english_to_french_notation(san_eng)

                    if board_after.is_checkmate():
                        return "Échec et mat.", f"{san_fr}#"

                    is_sacrifice = False
                    piece_moved = board.piece_at(move_obj.from_square)
                    piece_name = ChessUtils.get_piece_name_fr(piece_moved) if piece_moved else "Pièce"
                    
                    if piece_moved and piece_moved.piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                        if board.is_attacked_by(not board.turn, move_obj.to_square):
                            is_sacrifice = True

                    t_after = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else getattr(eval_after, 'type', 'cp')
                    val_after_raw = eval_after.get('value', 0) if isinstance(eval_after, dict) else (eval_after.value if hasattr(eval_after, 'value') and eval_after.value is not None else 0)
                    mate_in = (val_after_raw * player_multiplier) if t_after == 'mate' else 0

                    # Calcul mathématique strict de la qualification du coup
                    eval_symbol = ""
                    qualif_math = "Coup solide"
                    
                    if is_sacrifice and t_after == 'mate' and 0 < mate_in <= 3: 
                        eval_symbol = "!!"
                        qualif_math = "Coup brillant"
                    elif delta <= -300: 
                        eval_symbol = "??"
                        qualif_math = "Gaffe majeure"
                    elif delta <= -150: 
                        eval_symbol = "?"
                        qualif_math = "Erreur sérieuse"
                    elif delta <= -80: 
                        eval_symbol = "?!"
                        qualif_math = "Imprécision"
                    elif delta <= -30: 
                        eval_symbol = "!?"
                        qualif_math = "Coup douteux"
                    elif delta == 0 and swing >= 300: 
                        eval_symbol = "!"
                        qualif_math = "Excellent coup"
                    elif delta > -10: 
                        qualif_math = "Meilleur coup"
                    
                    target_square = chess.square_name(move_obj.to_square)
                    detailed_move_str = f"{piece_name} des {turn_color} vers la case {target_square} ({san_fr}{eval_symbol})"
                    pdf_move_str = f"{san_fr}{eval_symbol}"
                    
                    Logger.debug_log(f"Analyse tactique automatique pour {raw}", "DEBUG")
                    tactics = AIAnalyzer.detect_tactics(board, move_obj, eval_after, played_continuation)
                    
                    # CORRECTION 1.1 : Résolution de la contradiction logique (si Stockfish indique un meilleur/excellent coup, interdiction d'associer des termes de gaffe/perte)
                    if qualif_math in ["Meilleur coup", "Excellent coup", "Coup brillant", "Coup solide"]:
                        if any(term in tactics.lower() for term in ["perte", "gaffe", "erreur", "expose"]):
                            tactics = "Déplacement standard"
                    
                    if "via :" in tactics:
                        tactics = tactics.split("via :")[0].strip()
                    elif "suite illustrée" in tactics:
                        tactics = tactics.replace("(suite illustrée)", "").strip()
                        
                    eval_exacte = qualif_math
                    if tactics != "Déplacement standard":
                        eval_exacte += f" - Tactique : {tactics}"
                        
                    # CORRECTION 1.2 : Terminologie corrigée ("Coups alternatifs recommandés" au lieu de "Alternative forcée")
                    alt_recom_value = "Aucune variante recommandée retenue"
                    directive_text = ""

                    if delta < -30 and best_uci:
                        try:
                            sim_board = board.copy()
                            engine.set_fen_position(sim_board.fen())
                            pv_list = []
                            for _ in range(4):
                                m_best = engine.get_best_move()
                                if not m_best: break
                                m_sim = sim_board.parse_uci(m_best)
                                pv_list.append(sim_board.san(m_sim))
                                sim_board.push(m_sim)
                                engine.set_fen_position(sim_board.fen())
                            
                            best_pv_san = ChessUtils.parse_stockfish_pv(" ".join(pv_list))
                            if best_pv_san:
                                alt_recom_value = best_pv_san
                                directive_text = f"\n- Une alternative supérieure existait : [{best_pv_san}]. Intègre cette variante factuelle si nécessaire."
                            engine.set_fen_position(board.fen())
                        except Exception:
                            pass

                    system_prompt = f"""Tu es un Analyste Technique d'échecs retranscrivant des données machine en un rapport factuel. Ton rôle est de formuler l'analyse brute de l'ordinateur de manière strictement exacte, sans aucune invention, extrapolation ou tentative de style littéraire.

Lexique strict (Notation Française SAN) :
- F = Fou (ne désigne jamais une Dame)
- C = Cavalier
- T = Tour
- D = Dame
- R = Roi

RÈGLES ABSOLUES :
- DÉCRIS UNIQUEMENT CE QUI EST FOURNI DANS LES VARIABLES.
- Utilise EXCLUSIVEMENT la qualification exacte fournie dans "Évaluation exacte".{directive_text}
- Tu dois générer une analyse structurée dénuée de phrases superflues, respectant EXACTEMENT et UNIQUEMENT le format Markdown suivant :

Coup joué : [Description littérale vérifiée du coup SAN]
Évaluation Stockfish : [Intégrer dynamiquement la valeur d'évaluation fournie]
Coups alternatifs recommandés : [Alternative fournie ou "Aucune variante recommandée retenue"]
"""

                    user_content = f"""Données à formater rigoureusement :
- Coup SAN : {detailed_move_str}
- Évaluation exacte : {eval_exacte}
- Alternative : {alt_recom_value}
"""
                    
                    messages = [
                        {"role": "system", "content": system_prompt.strip()},
                        {"role": "user", "content": user_content.strip()}
                    ]
                    
                    options = {'temperature': 0.0, 'top_p': 0.1, 'num_predict': 150, 'repeat_penalty': 1.0}
                    
                    fallback_comment = f"Coup joué : {detailed_move_str}\nÉvaluation Stockfish : {eval_exacte}\nCoups alternatifs recommandés : {alt_recom_value}"
                    
                    cache_k = None
                    if is_trap:
                        import hashlib
                        trap_id = hashlib.md5(f"trap_{board_state.fen()}_{san_fr}".encode()).hexdigest()
                        cache_k = f"trap_{trap_id}"

                    comment_llm = AIAnalyzer.query_llm(messages, options, context_log=f"Commentaire de {san_fr}", fallback=fallback_comment, cache_key=cache_k)
                    
                    return comment_llm.strip(), pdf_move_str

            except Exception as e:
                Logger.debug_log(f"Analyse Stockfish échouée : {str(e)}. Fallback.", "ERROR")
                return "Analyse impossible : erreur de calcul.", ChessUtils.convert_english_to_french_notation(move_san)
        
        san_fr_fb = ChessUtils.convert_english_to_french_notation(move_san)
        if "x" in raw: return "Coup de prise : attention à la position des pièces.", san_fr_fb
        elif "#" in raw: return "Échec et mat. La partie est terminée.", san_fr_fb
        elif "+" in raw: return "Coup d'échec : menace immédiate.", san_fr_fb
        else: return "Coup neutre : pas de menace immédiate.", san_fr_fb
