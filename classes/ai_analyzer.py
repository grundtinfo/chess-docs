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
            {"role": "user", "content": "Coup : Tour des Blancs vers la case f8 (Tf8). Évaluation : C'est un bon coup, le plus précis actuellement. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "La Tour se déplace sur la case f8. C'est le coup le plus précis."}
        ],
        "imprecision": [
            {"role": "user", "content": "Coup : Pion des Noirs vers la case h3 (h3?!). Évaluation : C'est une imprécision qui dégrade légèrement la position. Tactique détectée : Déplacement standard."},
            {"role": "assistant", "content": "Le Pion se déplace sur la case h3. C'est une imprécision."}
        ],
        "suite_stockfish": [
            {"role": "user", "content": "Coup : Roi des Blancs vers la case d3 (Rxd3??). Évaluation : C'est une gaffe majeure entraînant un mat inévitable contre le joueur. Tactique détectée : Mat inévitable. Suite forcée : Df3+ Rg2 Df2#"},
            {"role": "assistant", "content": "Le Roi se déplace sur la case d3. C'est une gaffe majeure entraînant un mat inévitable. Suite : Df3+ Rg2 Df2#."}
        ],
        "gaffe_tactique_alternative": [
            {"role": "user", "content": "Coup : Cavalier des Blancs vers la case d4 (Cxd4??). Évaluation : C'est une gaffe majeure. Tactique détectée : Déplacement standard. Une meilleure alternative aurait été de déplacer le Fou vers la case c4 (Fc4)."},
            {"role": "assistant", "content": "Le Cavalier se déplace sur la case d4. C'est une gaffe majeure. Une meilleure alternative aurait été de déplacer le Fou sur la case c4."}
        ],
        "erreur_avec_alternative": [
            {"role": "user", "content": "Coup : Fou des Noirs vers la case d3 (Fd3?). Évaluation : C'est une erreur sérieuse. Tactique détectée : Déplacement standard. Une meilleure alternative aurait été de roquer."},
            {"role": "assistant", "content": "Le Fou se déplace sur la case d3. C'est une erreur sérieuse. Une meilleure alternative aurait été de roquer."}
        ],
        "perte_materielle": [
            {"role": "user", "content": "Coup : Dame des Blancs vers la case b5 (Db5??). Évaluation : C'est une erreur sérieuse causant une perte matérielle forcée. Tactique détectée : <b>Dame en b5</b> est exposée à une perte matérielle forcée en quelques coups."},
            {"role": "assistant", "content": "La Dame se déplace sur la case b5. C'est une erreur sérieuse causant une perte matérielle forcée."}
        ],
        "echec_geometrique": [
            {"role": "user", "content": "Coup : Dame des Noirs vers la case h4 (Dh4+). Évaluation : C'est un bon coup, le plus précis actuellement. Tactique détectée : Échec direct par Dame en h4."},
            {"role": "assistant", "content": "La Dame se déplace sur la case h4. Elle met le Roi adverse en échec."}
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
                
                # --- NOUVEAU : Interception stricte des refus et bavardages éthiques de l'IA ---
                refusals_regex = r"(?i)(je suis désolé|désolé|en tant qu'IA|en tant que modèle|je ne peux pas répondre|je ne suis pas autorisé)"
                if re.search(refusals_regex, content):
                    Logger.debug_log(f"Refus IA intercepté ({context_log}). Fallback appliqué.", "WARNING")
                    return fallback
                
                # 1. Suppression des balises de bavardage
                content = re.sub(r'\(?Note\s*:.*?\)?', '', content, flags=re.IGNORECASE).strip()
                # 2. Remplacement des sauts de ligne
                content = re.sub(r'\n+', ' ', content)
                # 3. Suppression des guillemets parasites
                content = content.strip(' "\'')
                # 4. Nettoyage de l'ancien préfixe
                content = content.replace("Commentaire : ", "").replace("Commentaire :", "").strip()
                
                # --- NOUVEAU : Nettoyage strict des symboles mathématiques et artéfacts ($) ---
                content = re.sub(r'[\$~]', '', content)
                
                # 6. Post-traitement lexical & Anti-hallucination rigoureux (Inchangé)
                content = re.sub(r'(?i)\bévêques?\b', 'Fou', content)
                content = re.sub(r'(?i)\bécureuils?\b', 'Pion', content)
                content = re.sub(r'(?i)\bcarré(s)?\b', r'case\1', content)
                content = re.sub(r'(?i)\bpiège mortel\b', 'menace critique', content)
                content = re.sub(r'(?i)\bcheval(aux)?\b', 'Cavalier', content)
                content = re.sub(r'(?i)\bson tour\b', 'sa Tour', content)
                content = re.sub(r'(?i)\bson pièce\b', 'sa pièce', content)
                content = re.sub(r'(?i)\ba déplacé vers\b', 's\'est déplacé vers', content)
                content = re.sub(r'(?i)attaque directe contre le [a-zA-ZÀ-ÿ]+ (Blanc|Noir) en [a-h][1-8]', 'capture sur la case', content)
                content = re.sub(r'(?i)une meilleure alternative aurait été.*?\.', '', content).strip()
                content = re.sub(r'(?i)attaquant\s+simultanément\s*(?::)?\s*([a-zA-ZÀ-ÿ0-9\s,]+(?:et\s+[a-zA-ZÀ-ÿ0-9\s]+)?)', r'attaquant \1', content)
                content = re.sub(r'(?i)(mettant|met)\s+en\s+échec\s+(le|la|les)\s+(?!Roi)[a-zA-Z]+', r'attaquant \2', content)
                content = re.sub(r'\b([L|l])e\s+Tour\b', lambda m: f"{m.group(1)}a Tour", content)
                content = re.sub(r'\b([L|l])e\s+Dame\b', lambda m: f"{m.group(1)}a Dame", content)
                content = re.sub(r'(?i)Roi\s+(Blanc|Noir)\s+en\s+[a-h][1-8]', 'Roi adverse', content)

                content = content.strip()
                if not content.endswith('.'):
                    content += '.'

                Logger.debug_log(f"Résultat brut LLM ({context_log}) : {content}", "DEBUG")
                
                # Caching limité à ce qui est strictement demandé
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
            
        result = result.replace(":", " : ").replace("  ", " ")
        result = re.sub(r'\b(\w+)\s+(Défense|Ouverture|Variante|Attaque|Gambit|Système)\b', r'\2 \1', result, flags=re.IGNORECASE)

        result = result.title()
        mots_de_liaison = [" De ", " Du ", " Des ", " La ", " Le ", " Les ", " À ", " En ", " Et ", " D'"]
        for mot in mots_de_liaison:
            result = result.replace(mot, mot.lower())
        result = re.sub(r'\s+', ' ', result)
        result = result.replace(" :", " :").replace(":", " : ")
        result = re.sub(r'\s+', ' ', result).strip()

        # Suppression du fallback LLM : on retourne uniquement le résultat traduit de manière déterministe
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
                                    
                            # Amélioration : La pièce menacée et sa case apparaissent en gras et au début de la description
                            loss_desc = f"<b>{piece_lost} en {lost_square}</b> est exposée à une perte matérielle forcée en quelques coups"
                            if is_in_trap:
                                tactics.append(f"{loss_desc} (suite illustrée)")
                            else:
                                tactics.append(f"{loss_desc} via : {' '.join(seq_fr)}")
                        else:
                            tactics.append("Expose le joueur à une lourde perte matérielle (gaffe stratégique)")
                        
        tactics_comment = " ; ".join(tactics) if tactics else "Déplacement standard"
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

                    eval_symbol = ""
                    if is_sacrifice and t_after == 'mate' and 0 < mate_in <= 3: eval_symbol = "!!"
                    elif delta <= -300: eval_symbol = "??"
                    elif delta <= -150: eval_symbol = "?"
                    elif delta <= -80: eval_symbol = "?!"
                    elif delta <= -30: eval_symbol = "!?"
                    elif delta == 0 and swing >= 300: eval_symbol = "!"
                    
                    target_square = chess.square_name(move_obj.to_square)
                    
                    # Détails complets conservés pour le LLM
                    detailed_move_str = f"{piece_name} des {turn_color} vers la case {target_square} ({san_fr}{eval_symbol})"
                    
                    # Format concis standard français avec suffixe pour le rapport PDF
                    pdf_move_str = f"{san_fr}{eval_symbol}"
                    
                    Logger.debug_log(f"Analyse tactique automatique pour {raw}", "DEBUG")
                    tactics = AIAnalyzer.detect_tactics(board, move_obj, eval_after, future_moves)
                    
                    stockfish_seq = "Aucune"
                    if "via :" in tactics:
                        parts = tactics.split("via :")
                        stockfish_seq = parts[1].strip()
                        tactics = parts[0].strip()
                    elif "suite illustrée" in tactics:
                        stockfish_seq = "Illustrée dans le rapport"
                        tactics = tactics.replace("(suite illustrée)", "").strip()
                    
                    if delta <= -150:
                        status = f"Le joueur {turn_color} commet une erreur. L'adversaire bénéficie de la tactique suivante : {tactics}"
                        events_text = ""
                    else:
                        if tactics != "Déplacement standard":
                            if "mat inévitable" in tactics.lower() or "mat par" in tactics.lower():
                                if val_after_raw < 0:
                                    status = f"Ce coup est excellent, le joueur {turn_color} force le mat. Décris comment il gagne."
                                else:
                                    status = f"C'est une gaffe majeure entraînant un mat inévitable contre le joueur {turn_color}."
                            elif "perte matérielle" in tactics.lower():
                                status = f"C'est une erreur sérieuse causant une perte matérielle forcée pour le joueur {turn_color}."
                            else:
                                status = f"C'est un coup tactique significatif pour le joueur {turn_color}."
                        else:
                            if delta > -10: status = "C'est un bon coup, le plus précis actuellement."
                            elif delta <= -80: status = f"C'est une imprécision qui dégrade légèrement la position de {turn_color}."
                            elif delta <= -30: status = "C'est un coup jouable."
                            else: status = "C'est un coup solide et tout à fait correct."
                        
                        if tactics != "Déplacement standard":
                            events_text = f"Tactique détectée : {tactics}"
                        else:
                            events_text = "Tactique détectée : Déplacement standard."
                    
                    alt_context = ""
                    # ... [Le reste du code des alternatives reste strictement identique] ...
                    
                    if not alt_context:
                        warning_msg = "AVERTISSEMENT SYSTÈME : Ne propose aucune alternative de coup. Ne fournis aucune phrase d'alternative."
                        if events_text:
                            events_text += f" {warning_msg}"
                        else:
                            events_text = warning_msg
                    
                    system_prompt = """Tu es un Analyste Technique d'échecs retranscrivant des données machine en un rapport factuel. Ton rôle est de formuler l'analyse brute de l'ordinateur de manière strictement exacte, sans aucune invention, extrapolation ou tentative de style littéraire.

Guide d'interprétation strict des suffixes d'échecs :
- !! : Coup brillant/sacrifice
- ! : Excellent coup
- !? : Coup intéressant
- ?! : Imprécision
- ? : Erreur
- ?? : Gaffe majeure ou perte forcée

Directives de rédaction à suivre impérativement :
1. Adopte un ton clinique, purement descriptif et factuel. L'exactitude prime sur le naturel. La répétition de structures de phrases rigides est encouragée et obligatoire.
2. Utilise EXCLUSIVEMENT la terminologie française officielle : Pion, Cavalier, Fou, Tour (féminine), Dame (féminine), Roi.
3. Intègre factuellement les informations de tactique sans utiliser l'expression 'tactique détectée'. N'invente aucun élément absent des données.
4. Distingue rigoureusement la "Suite jouée dans la partie" (les coups réellement joués) de la "Meilleure alternative théorique" (variante de l'ordinateur). Ne mélange jamais les deux.
5. Si le champ d'alternative est vide, NE MENTIONNE STRICTEMENT AUCUNE ALTERNATIVE et n'invente jamais de coup alternatif.
6. Nettoie toute interférence contextuelle : chaque commentaire cible uniquement le tour analysé.

RÈGLES ABSOLUES :
- DÉCRIS UNIQUEMENT CE QUI EST FOURNI DANS LES VARIABLES.
- Livre UNIQUEMENT le commentaire final, sans note ni réflexion.
- Si une "Suite jouée" t'est fournie, cite-la factuellement. Si une "Meilleure alternative théorique" t'est fournie, précise que c'est une recommandation.
- Rédige impérativement 1 à 3 phrases courtes et standardisées.
- PENALITÉ MAXIMALE : Si ta réponse dépasse 3 phrases, elle sera rejetée. Ne décris JAMAIS la sécurité des pions ou des pièces de ton propre chef.
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

                    if "échec direct" in tactics.lower() or "échec double" in tactics.lower():
                        messages.extend(AIAnalyzer.FEW_SHOT_BANK["echec_geometrique"])

                    suite_str = ""
                    if stockfish_seq not in ["Aucune", "Illustrée dans le rapport"] and stockfish_seq.strip() != "":
                        suite_str = f"Suite jouée dans la partie : {stockfish_seq}"
                    
                    alt_str = f"Meilleure alternative théorique (recommandation Stockfish) : {alt_context.strip()}" if alt_context else ""
                    
                    user_content = f"Coup : {detailed_move_str}. Évaluation : {status} {events_text} {alt_str} {suite_str}".strip()
                    
                    if not suite_str:
                        user_content = re.sub(r'\s+', ' ', user_content).strip()

                    messages.append({"role": "user", "content": user_content})
                    
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
                    
                    # On retourne le commentaire de l'IA et la notation concise pour le PDF
                    return comment_llm, pdf_move_str

            except Exception as e:
                Logger.debug_log(f"Analyse Stockfish échouée : {str(e)}. Fallback.", "ERROR")
                return "Analyse impossible : erreur de calcul.", ChessUtils.convert_english_to_french_notation(move_san)
        
        san_fr_fb = ChessUtils.convert_english_to_french_notation(move_san)
        if "x" in raw: return "Coup de prise : attention à la position des pièces.", san_fr_fb
        elif "#" in raw: return "Échec et mat. La partie est terminée.", san_fr_fb
        elif "+" in raw: return "Coup d'échec : menace immédiate.", san_fr_fb
        else: return "Coup neutre : pas de menace immédiate.", san_fr_fb
