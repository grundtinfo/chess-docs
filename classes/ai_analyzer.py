import json
import chess
import requests
import re
import ollama
from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer

class AIAnalyzer:
    FEW_SHOT_BANK = {
        "bon_coup": [
            {"role": "user", "content": "Coup : Tour (Tf8). Évaluation : C'est un bon coup, le plus précis actuellement. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "La Tour se place sur la colonne f pour soutenir efficacement la défense."}
        ],
        "imprecision": [
            {"role": "user", "content": "Coup : Pion (h3?!). Évaluation : C'est une imprécision qui dégrade légèrement la position. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "Une petite imprécision avec cette poussée de pion qui fait perdre un tempo précieux."}
        ],
        "suite_stockfish": [
            {"role": "user", "content": "Coup : Roi (Rxd3??). Évaluation : C'est une gaffe majeure entraînant un mat inévitable contre le joueur. Tactique détectée : Mat inévitable via : Df3+ Rg2 Df2#."},
            {"role": "assistant", "content": "Une gaffe fatale du Roi qui s'expose à une attaque directe menant au mat."}
        ],
        "gaffe_tactique_alternative": [
            {"role": "user", "content": "Coup : Cavalier (Cxd4??). Évaluation : C'est une gaffe majeure entraînant une perte catastrophique. Tactique détectée : Déplacement standard. Une meilleure alternative aurait été de jouer Fou (Fc4)."},
            {"role": "assistant", "content": "Erreur du Cavalier qui s'aventure trop loin ; il était préférable de développer le Fou en c4."}
        ],
        "erreur_avec_alternative": [
            {"role": "user", "content": "Coup : Fou (Fd3?). Évaluation : C'est une erreur sérieuse qui fait perdre un avantage significatif. Tactique détectée : Déplacement standard. Une meilleure alternative aurait été de roquer."},
            {"role": "assistant", "content": "Placement douteux du Fou sur d3, le roque était une option bien plus sécurisante ici."}
        ],
        "perte_materielle": [
            {"role": "user", "content": "Coup : Dame (Db5??). Évaluation : C'est une erreur sérieuse causant une perte matérielle forcée. Tactique détectée : Expose cette pièce Dame à une perte matérielle forcée en quelques coups."},
            {"role": "assistant", "content": "Une décision désastreuse qui expose directement la Dame à une capture inévitable."}
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
        
        try:
            result = ollama.chat(
                model=Config.OLLAMA_MODEL,
                messages=messages,
                options=options or {'temperature': 0.0}
            )
            if result and 'message' in result and 'content' in result['message']:
                content = result['message']['content']
                
                # 1. Suppression des balises de bavardage (ex: "Note : ...")
                content = re.sub(r'\(?Note\s*:.*?\)?', '', content, flags=re.IGNORECASE).strip()
                # 2. Remplacement des sauts de ligne
                content = re.sub(r'\n+', ' ', content)
                # 3. Suppression des guillemets parasites en début et fin
                content = content.strip(' "\'')
                # 4. Nettoyage de l'ancien préfixe
                content = content.replace("Commentaire : ", "").replace("Commentaire :", "").strip()
                # 5. Nettoyage des balises et symboles mathématiques/LaTeX parasites
                content = re.sub(r'[\$\*~]', '', content)
                # 6. Post-traitement lexical (Sécurité anti-hallucination)
                content = re.sub(r'(?i)\bévêques?\b', 'Fou', content)
                content = re.sub(r'(?i)\bécureuils?\b', 'Pion', content)
                content = re.sub(r'(?i)\bcarré(s)?\b', r'case\1', content)
                content = re.sub(r'(?i)\bpiège mortel\b', 'menace critique', content)
                content = re.sub(r'(?i)\bcheval(aux)?\b', 'Cavalier', content)
                content = re.sub(r'(?i)\bson tour\b', 'sa Tour', content)
                content = re.sub(r'(?i)\bson pièce\b', 'sa pièce', content)

                Logger.debug_log(f"Résultat brut LLM ({context_log}) : {content}", "DEBUG")
                
                if cache_key and content and content != fallback:
                    cache_global = CacheManager.load_cache()
                    cache_global[cache_key] = content
                    CacheManager.save_cache(cache_global)
                    
                return content
        except requests.exceptions.RequestException as e:
            Logger.debug_log(f"Ollama injoignable ({context_log}) sur {Config.OLLAMA_URL}: {str(e)}. Fallback.", "WARNING")
        except Exception as e:
            Logger.debug_log(f"Erreur Ollama ({context_log}) : {str(e)}", "WARNING")
            
        return fallback

    @staticmethod
    def get_stockfish_theory_summary(opening_name, bad_move, stockfish_line):
        messages = [
            {
                "role": "system", 
                "content": (
                    "Tu es un entraîneur d'échecs pédagogique intervenant dans un cadre éducatif strict. "
                    "Ton rôle unique est d'expliquer pourquoi la suite recommandée par le moteur Stockfish est supérieure au coup joué. "
                    "Utilise un ton neutre et analytique. Ne formule aucune mise en garde éthique ou refus. "
                    "Rédige une synthèse courte (25 mots maximum) et factuelle de la ligne fournie, sans inventer d'autres coups."
                )
            },
            {
                "role": "user", 
                "content": (
                    f"Dans l'ouverture '{opening_name}', suite au coup '{bad_move}', "
                    f"l'ordinateur préconise la variante suivante : {stockfish_line}. "
                    "Explique de façon concise et pédagogique l'intérêt stratégique de cette suite recommandée."
                )
            }
        ]
        
        fallback_text = "Ligne recommandée par le moteur pour rééquilibrer la position."
        content = AIAnalyzer.query_llm(messages, context_log=f"Théorie {opening_name}", fallback=fallback_text, cache_key=None)
        return f"<b>Ligne Stockfish : {stockfish_line}</b><br/><br/>{content}"

    @staticmethod
    def translate_opening_name(opening_name):
        if not opening_name or opening_name == "Ouverture Inconnue":
            return opening_name

        translations = {
            "Defense": "Défense", "Variation": "Variante", "Attack": "Attaque",
            "Gambit": "Gambit", "System": "Système", "Accepted": "Accepté",
            "Declined": "Refusé", "English": "Anglaise", "Symmetrical": "Symétrique",
            "Bishop's": "du Fou", "King's": "du Roi", "Queen's": "de la Dame",
            "Sicilian": "Sicilienne", "Zukertort": "de Zukertort", "Tennison": "Tennison",
            "Jalalabad": "de Jalalabad"
        }

        if "Opening" in opening_name:
            name_part = opening_name.replace("Opening", "").replace(":", "").strip()
            translated_name = translations.get(name_part, name_part)
            return f"Ouverture {translated_name}"

        result = opening_name
        for eng, fr in translations.items():
            result = result.replace(eng, fr)
            
        # Formatage strict de la typographie française
        result = result.replace(":", " : ").replace("  ", " ")
        # Inversion dynamique des termes via Regex
        result = re.sub(r'\b(\w+)\s+(Défense|Ouverture|Variante|Attaque|Gambit|Système)\b', r'\2 \1', result, flags=re.IGNORECASE)

        # --- AJOUT : Normalisation stricte de la casse ---
        result = result.title() # Force la majuscule sur chaque mot
        mots_de_liaison = [" De ", " Du ", " Des ", " La ", " Le ", " Les ", " À ", " En ", " Et ", " D'"]
        for mot in mots_de_liaison:
            result = result.replace(mot, mot.lower())
        # Correction des espacements autour des deux points
        result = re.sub(r'\s+', ' ', result)
        result = result.replace(" :", " :").replace(":", " : ")
        result = re.sub(r'\s+', ' ', result).strip()

        if result == opening_name:
            result = AIAnalyzer._translate_with_llm_fallback(opening_name)
            
        return result

    @staticmethod
    def _translate_with_llm_fallback(opening_name):
        messages = [
            {"role": "system", "content": "Tu es un outil de conversion d'ouvertures. Traduis vers le français en respectant la syntaxe (ex: 'Scandinavian Defense: Valencian Variation' -> 'Défense Scandinave : Variante Valencienne'). Conserve les noms propres. NE FAIS AUCUN COMMENTAIRE, retourne UNIQUEMENT la traduction."},
            {"role": "user", "content": opening_name}
        ]
        return AIAnalyzer.query_llm(messages, options={'temperature': 0.0, 'num_predict': 25}, context_log="Fallback Traduction")

    @staticmethod
    def detect_tactics(board_before, move_obj, eval_after=None, future_moves=None):
        # (La logique reste identique à celle de l'original)
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
        elif board_after.is_check():
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
            
        if not board_after.is_checkmate():
            attacks = board_after.attacks(move_obj.to_square)
            targets = []
            for sq in attacks:
                piece = board_after.piece_at(sq)
                if piece and piece.color == board_after.turn and piece.piece_type != chess.PAWN:
                    targets.append(f"{ChessUtils.get_piece_name_fr(piece)} en {chess.square_name(sq)}")
            
            if len(targets) > 1:
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

        if eval_after and not board_after.is_checkmate():
            if hasattr(eval_after, 'value'):
                val = eval_after.value if eval_after.value is not None else 0
                t = getattr(eval_after, 'type', 'cp')
            else:
                val = eval_after.get('value', 0) if isinstance(eval_after, dict) else 0
                t = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else 'cp'

            player_multiplier = 1 if board_before.turn == chess.WHITE else -1

            if t == 'mate':
                sf = StockfishAnalyzer().get_engine()
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
                if cp_val >= 300 and "Capture" not in " ".join(tactics):
                    tactics.append("Prépare un gain matériel décisif imminent")
                elif cp_val <= -300:
                    piece_lost = None
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
                                if pt == chess.QUEEN:
                                    piece_lost = "Dame"
                                elif pt == chess.ROOK and piece_lost != "Dame":
                                    piece_lost = "Tour"
                                elif pt == chess.BISHOP and piece_lost not in ["Dame", "Tour"]:
                                    piece_lost = "Fou"
                                elif pt == chess.KNIGHT and piece_lost not in ["Dame", "Tour", "Fou"]:
                                    piece_lost = "Cavalier"
                                    
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
                                
                        if is_in_trap:
                            tactics.append(f"Expose cette pièce {piece_lost} à une perte matérielle forcée en quelques coups (suite illustrée)")
                        else:
                            tactics.append(f"Expose cette pièce {piece_lost} à une perte matérielle forcée en quelques coups via : {' '.join(seq_fr)}")
                    else:
                        tactics.append("Expose le joueur à une lourde perte matérielle (gaffe stratégique)")
                        
        tactics_comment = " ; ".join(tactics) if tactics else "Continuité"
        Logger.debug_log(f"Événement détecté pour le coup : {tactics_comment}", "INFO")
        return tactics_comment

    @staticmethod
    def generate_move_comment(move_raw, move_san, board_state, is_trap=False, future_moves=None):
        raw = ChessUtils.remove_special_chars(move_raw.strip())
        board = chess.Board(board_state.fen())
        turn_color = "Blancs" if board.turn == chess.WHITE else "Noirs"
        
        analyzer = StockfishAnalyzer()
        engine = analyzer.get_engine()
        
        if engine:
            try:
                Logger.debug_log(f"Stockfish : Analyse du coup {raw} (Évaluation position)", "INFO")
                eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
                Logger.debug_log(f"Stockfish : Évaluation du meilleur coup alternatif pour {raw}", "INFO")
                best_move_fr, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
                
                if eval_before and eval_after and best_move_fr:
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
                    # --- NOUVEAU : Extraction explicite du nom de la pièce ---
                    piece_name = ChessUtils.get_piece_name_fr(piece_moved) if piece_moved else "Pièce"
                    
                    if piece_moved and piece_moved.piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                        if board.is_attacked_by(not board.turn, move_obj.to_square):
                            is_sacrifice = True

                    t_after = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else getattr(eval_after, 'type', 'cp')
                    val_after_raw = eval_after.get('value', 0) if isinstance(eval_after, dict) else (eval_after.value if hasattr(eval_after, 'value') and eval_after.value is not None else 0)
                    mate_in = (val_after_raw * player_multiplier) if t_after == 'mate' else 0

                    eval_symbol = ""
                    if is_sacrifice and t_after == 'mate' and 0 < mate_in <= 3: eval_symbol = "!!"
                    elif delta <= -300: eval_symbol = "??"
                    elif delta <= -150: eval_symbol = "?"
                    elif delta <= -80: eval_symbol = "?!"
                    elif delta <= -30: eval_symbol = "!?"
                    elif delta == 0 and swing >= 300: eval_symbol = "!"
                    
                    # --- NOUVEAU : Formatage du coup avec la pièce ---
                    final_move_str = f"{piece_name} des {turn_color} ({san_fr}{eval_symbol})"
                    
                    Logger.debug_log(f"Analyse tactique automatique pour {raw}", "DEBUG")
                    tactics = AIAnalyzer.detect_tactics(board, move_obj, eval_after, future_moves)
                    
                    # --- NOUVEAU : Interception Python de la séquence Stockfish ---
                    stockfish_seq = "Aucune"
                    if "via :" in tactics:
                        parts = tactics.split("via :")
                        stockfish_seq = parts[1].strip()
                        # Nettoie les FAITS pour ne pas embrouiller le LLM avec des coups bruts
                        tactics = parts[0].strip()
                    elif "suite illustrée" in tactics:
                        stockfish_seq = "Illustrée dans le rapport"
                        tactics = tactics.replace("(suite illustrée)", "").strip()
                    # ---------------------------------------------------------------
                    
                    if tactics != "Continuité":
                        if "mat inévitable" in tactics.lower() or "mat par" in tactics.lower():
                            if val_after_raw < 0:
                                status = "Ce coup est excellent, le joueur force le mat. Décris comment il gagne."
                            else:
                                status = "C'est une gaffe majeure qui entraîne un mat inévitable contre le joueur."
                        elif "perte matérielle" in tactics.lower():
                            status = "C'est une erreur sérieuse causant une perte matérielle forcée."
                        else:
                            status = f"C'est un coup tactique significatif."
                    else:
                        if delta > -10: status = "C'est un bon coup, le plus précis actuellement."
                        elif delta <= -300: status = "C'est une gaffe majeure entraînant une perte catastrophique."
                        elif delta <= -150: status = "C'est une erreur sérieuse qui fait perdre un avantage significatif."
                        elif delta <= -80: status = "C'est une imprécision qui dégrade légèrement la position."
                        elif delta <= -30: status = "C'est un coup jouable, mais il existe une alternative légèrement plus précise."
                        else: status = "C'est un coup solide et tout à fait correct."
                    
                    if raw != best_move_fr and delta < -20:
                        if "O-O" in best_move_fr:
                            alt_context = "Une meilleure alternative aurait été de roquer."
                        else:
                            # --- NOUVEAU : Pré-formatage du meilleur coup alternatif ---
                            if best_uci:
                                best_move_obj = chess.Move.from_uci(best_uci)
                                best_piece = board.piece_at(best_move_obj.from_square)
                                best_piece_name = ChessUtils.get_piece_name_fr(best_piece)
                                alt_context = f"Une meilleure alternative aurait été de jouer {best_piece_name} ({best_move_fr})."
                            else:
                                alt_context = f"Une meilleure alternative aurait été de jouer le coup {best_move_fr}."
                    else:
                        alt_context = ""
                    
                    if tactics != "Continuité":
                        events_text = f"Tactique détectée : {tactics}"
                    else:
                        events_text = "Tactique détectée : Déplacement standard."
                    
                    system_prompt = """Tu es un Analyste Technique d'échecs retranscrivant des données machine en un rapport factuel. Ton rôle est de formuler l'analyse brute de l'ordinateur de manière strictement exacte, sans aucune invention ou tentative de style littéraire.

Directives de rédaction à suivre impérativement :
1. Adopte un ton clinique, purement descriptif et factuel. L'exactitude prime sur le naturel. La répétition de structures de phrases est encouragée si elle garantit la précision.
2. Utilise EXCLUSIVEMENT la terminologie française officielle : Pion, Cavalier, Fou, Tour (féminine), Dame (féminine), Roi.
3. Décris l'action EXACTE fournie dans la variable "Tactique détectée". Ne nomme que les pièces explicitement mentionnées dans l'évaluation brute (par exemple, si l'évaluation mentionne un Fou, ne parle pas d'un Cavalier).
4. La première phrase décrit le coup joué et la raison technique stricte (issue de l'évaluation). 
5. La seconde phrase propose l'alternative UNIQUEMENT si le prompt indique explicitement "Une meilleure alternative aurait été de...". N'invente jamais de coup alternatif de ton propre chef.

RÈGLES ABSOLUES :
- Livre UNIQUEMENT le commentaire final, sans note, justification ni réflexion.
- N'utilise pas de guillemets pour encapsuler ta phrase.
- N'écris jamais l'évaluation brute entre parenthèses à la fin de ta phrase.
- Ne mentionne jamais de mise en échec, de clouage ou de gain matériel s'ils ne sont pas explicitement écrits dans l'invite.
- Rédige impérativement 1 à 2 phrases courtes (MAXIMUM 30 MOTS AU TOTAL).
"""

                    messages = [{"role": "system", "content": system_prompt}]
                    
                    if "bon coup" in status.lower() or "solide" in status.lower():
                        messages.extend(AIAnalyzer.FEW_SHOT_BANK["bon_coup"])
                    elif "imprécision" in status.lower():
                        messages.extend(AIAnalyzer.FEW_SHOT_BANK["imprecision"])
                    elif "erreur" in status.lower() or "gaffe" in status.lower():
                        if "via :" in tactics:
                            messages.extend(AIAnalyzer.FEW_SHOT_BANK["suite_stockfish"])
                        elif alt_context:
                            if "gaffe" in status.lower():
                                messages.extend(AIAnalyzer.FEW_SHOT_BANK["gaffe_tactique_alternative"])
                            else:
                                messages.extend(AIAnalyzer.FEW_SHOT_BANK["erreur_avec_alternative"])
                        elif tactics != "Continuité" and "perte matérielle" in tactics.lower():
                            messages.extend(AIAnalyzer.FEW_SHOT_BANK["perte_materielle"])

                    # Nettoyage de alt_context pour éviter les sauts de ligne inutiles
                    alt_str = alt_context.strip() if alt_context else ""
                    
                    messages.append({
                        "role": "user", 
                        "content": f"Coup : {final_move_str}. Évaluation : {status}. {events_text} {alt_str}"
                    })
                    
                    options = {'temperature': 0.0, 'top_p': 0.1, 'num_predict': 150, 'repeat_penalty': 1.0}
                    
                    fallback_comment = "Analyse LLM échouée."
                    if delta < -50: fallback_comment = "Coup très mauvais : menace grave non évitée."
                    elif delta == 0 or delta > -10: fallback_comment = "Coup bon : maintient la pression."
                    else: fallback_comment = "Coup neutre : pas de menace immédiate."
                    
                    cache_k = None
                    if is_trap:
                        import hashlib
                        trap_id = hashlib.md5(f"trap_{board_state.fen()}_{san_fr}".encode()).hexdigest()
                        cache_k = f"trap_{trap_id}"

                    comment_llm = AIAnalyzer.query_llm(messages, options, context_log=f"Commentaire de {san_fr}", fallback=fallback_comment, cache_key=cache_k)
                    
                    return comment_llm, final_move_str

            except Exception as e:
                Logger.debug_log(f"Analyse Stockfish échouée : {str(e)}. Fallback.", "ERROR")
                return "Analyse impossible : erreur de calcul.", move_raw
        
        if "x" in raw: return "Coup de prise : attention à la position des pièces.", move_raw
        elif "#" in raw: return "Échec et mat. La partie est terminée.", move_raw
        elif "+" in raw: return "Coup d'échec : menace immédiate.", move_raw
        else: return "Coup neutre : pas de menace immédiate.", move_raw
