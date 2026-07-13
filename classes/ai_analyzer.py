import json
import chess
import requests
import ollama
from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer

class AIAnalyzer:
    FEW_SHOT_BANK = {
        "bon_coup": [
            {"role": "user", "content": "FAITS :\nJoueur : Blancs\nCoup : e4\nQualité : C'est un bon coup, le plus précis.\n\nCOMMENTAIRE :"},
            {"role": "assistant", "content": "Un bon coup qui est le plus précis dans cette position."}
        ],
        "erreur_avec_alternative": [
            {"role": "user", "content": "FAITS :\nJoueur : Noirs\nCoup : Cxd4\nQualité : C'est une erreur sérieuse qui fait perdre un avantage significatif.\nMeilleure alternative : Cf6\n\nCOMMENTAIRE :"},
            {"role": "assistant", "content": "Ce coup est une erreur sérieuse qui fait perdre un avantage significatif, la meilleure alternative étant Cf6."}
        ],
        "perte_materielle": [
            {"role": "user", "content": "FAITS :\nJoueur : Blancs\nCoup : Cg5\nQualité : C'est une erreur sérieuse causant une perte matérielle forcée.\nÉvénement : Expose cette pièce Cavalier à une perte matérielle forcée en quelques coups via : Tf7 Cxf7 Rxf7 Dxh7+ Re8 dxe5\n\nCOMMENTAIRE :"},
            {"role": "assistant", "content": "Ce coup expose le Cavalier à une perte matérielle forcée selon la suite : Tf7 Cxf7 Rxf7 Dxh7+ Re8 dxe5."}
        ],
        "gaffe_tactique_alternative": [
            {"role": "user", "content": "FAITS :\nJoueur : Noirs\nCoup : Fg4\nQualité : C'est une gaffe majeure entraînant une perte catastrophique.\nÉvénement : Tactique Fourchette par Cavalier en e5 sur : Roi en e8, Tour en h8\nMeilleure alternative : 0-0\n\nCOMMENTAIRE :"},
            {"role": "assistant", "content": "C'est une gaffe majeure entraînant une perte catastrophique en permettant une fourchette du Cavalier en e5 sur le Roi et la Tour, alors que le meilleur coup était le petit roque (0-0)."}
        ],
        "imprecision": [
            {"role": "user", "content": "FAITS :\nJoueur : Noirs\nCoup : Df6\nQualité : C'est une imprécision qui dégrade légèrement la position.\nMeilleure alternative : Cf6\n\nCOMMENTAIRE :"},
            {"role": "assistant", "content": "Ce coup est une imprécision qui dégrade légèrement la position, la meilleure alternative étant Cf6."}
        ]
    }

    @staticmethod
    def query_llm(messages, options=None, context_log="LLM", fallback=""):
        Logger.debug_log(f"Appel d'Ollama ({Config.OLLAMA_MODEL}) pour : {context_log}...", "INFO")
        Logger.debug_log(f"Prompt envoyé au LLM : {json.dumps(messages, ensure_ascii=False)}", "DEBUG")
        
        try:
            result = ollama.chat(
                model=Config.OLLAMA_MODEL,
                messages=messages,
                options=options or {'temperature': 0.0}
            )
            if result and 'message' in result and 'content' in result['message']:
                content = result['message']['content'].strip().replace("\n", " ")
                Logger.debug_log(f"Résultat brut LLM ({context_log}) : {content}", "DEBUG")
                return content
        except requests.exceptions.RequestException as e:
            Logger.debug_log(f"Ollama injoignable ({context_log}) sur {Config.OLLAMA_URL}: {str(e)}. Fallback.", "WARNING")
        except Exception as e:
            Logger.debug_log(f"Erreur Ollama ({context_log}) : {str(e)}", "WARNING")
            
        return fallback

    @staticmethod
    def get_stockfish_theory_summary(opening_name, bad_move, stockfish_line):
        messages = [
            {"role": "system", "content": "Tu es un commentateur d'échecs factuel. Ton SEUL but est d'expliquer la ligne calculée par Stockfish fournie par l'utilisateur. TU NE DOIS SOUS AUCUN PRÉTEXTE inventer ou proposer d'autres coups. Contente-toi de reprendre la ligne exacte et de la justifier brièvement."},
            {"role": "user", "content": f"Dans l'ouverture '{opening_name}', le joueur a joué la gaffe '{bad_move}'. La correction exacte de l'ordinateur est la ligne suivante : {stockfish_line}. Explique de façon concise pourquoi cette ligne de l'ordinateur est forte, sans inventer de nouveaux coups."}
        ]
        
        fallback_text = "Erreur de génération LLM."
        content = AIAnalyzer.query_llm(messages, context_log=f"Théorie {opening_name}", fallback=fallback_text)
        return f"<b>Ligne Stockfish : {stockfish_line}</b><br/><br/>{content}"

    @staticmethod
    def translate_opening_name(opening_name):
        if not opening_name or opening_name == "Ouverture Inconnue":
            return opening_name
            
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu es un traducteur robotique et strict d'ouvertures d'échecs. Ton SEUL rôle est de traduire de l'anglais vers le français.\n"
                    "RÈGLES ABSOLUES :\n"
                    "1. 'Opening' se traduit EXCLUSIVEMENT par 'Ouverture' (JAMAIS par Ouvrière).\n"
                    "2. 'Bishop' = 'Fou', 'Knight' = 'Cavalier', 'Queen' = 'Dame', 'Draw' = 'Nulle'.\n"
                    "3. Renvoie UNIQUEMENT la traduction. Aucun préfixe 'Nom:', aucun commentaire, aucune note entre parenthèses."
                )
            },
            {
                "role": "user",
                "content": f"{opening_name}"
            }
        ]
        
        traduction = AIAnalyzer.query_llm(messages, options={'temperature': 0.0}, context_log=f"Traduction de {opening_name}", fallback=opening_name)
        
        # Nettoyage programmatique post-LLM pour forcer le format
        traduction = traduction.replace("Nom :", "").replace("Nom:", "").strip()
        traduction = traduction.split("(")[0].strip() # Enlève tout blabla entre parenthèses
        
        return traduction

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
        elif board_after.is_check():
            defender_color = board_after.turn
            attacker_color = not defender_color
            king_sq = board_after.king(defender_color)
            checkers = board_after.attackers(attacker_color, king_sq)
            
            if move_obj.to_square not in checkers and len(checkers) > 0:
                checker_sq = list(checkers)[0]
                checker_piece = board_after.piece_at(checker_sq)
                checker_name = ChessUtils.get_piece_name_fr(checker_piece)
                tactics.append(f"Tactique Échec à la découverte par {checker_name} (démasqué par {moving_piece_name})")
            elif len(checkers) > 1:
                tactics.append(f"Tactique Échec double impliquant {moving_piece_name} en {to_square_name}")
            else:
                tactics.append(f"Échec par {moving_piece_name} en {to_square_name}")
            
        if not board_after.is_checkmate():
            attacks = board_after.attacks(move_obj.to_square)
            targets = []
            for sq in attacks:
                piece = board_after.piece_at(sq)
                if piece and piece.color == board_after.turn and piece.piece_type != chess.PAWN:
                    targets.append(f"{ChessUtils.get_piece_name_fr(piece)} en {chess.square_name(sq)}")
            
            if len(targets) > 1:
                targets_str = ", ".join(targets)
                tactics.append(f"Tactique Fourchette par {moving_piece_name} en {to_square_name} sur : {targets_str}")

        defender_color = board_after.turn
        pinned_pieces = []
        for sq in chess.SQUARES:
            piece = board_after.piece_at(sq)
            if piece and piece.color == defender_color:
                if board_after.is_pinned(defender_color, sq):
                    if not board_before.is_pinned(defender_color, sq):
                        pinned_pieces.append(f"{ChessUtils.get_piece_name_fr(piece)} en {chess.square_name(sq)}")
                        
        if pinned_pieces:
            tactics.append(f"Tactique Clouage imposé sur : {', '.join(pinned_pieces)}")

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
                    
                    final_move_str = f"{san_fr}{eval_symbol}"
                    
                    Logger.debug_log(f"Analyse tactique automatique pour {raw}", "DEBUG")
                    tactics = AIAnalyzer.detect_tactics(board, move_obj, eval_after, future_moves)
                    
                    if tactics != "Continuité":
                        # CORRECTION : On vérifie "mat inévitable" ou "mat par" pour éviter le faux positif sur "matérielle"
                        if "mat inévitable" in tactics.lower() or "mat par" in tactics.lower():
                            status = "C'est une gaffe majeure entraînant un mat inévitable."
                        elif "perte matérielle" in tactics.lower():
                            status = "C'est une erreur sérieuse causant une perte matérielle forcée."
                        else:
                            status = f"C'est un coup tactique significatif."
                    else:
                        # TA LOGIQUE SUR LES DELTAS EST BIEN CONSERVÉE ICI
                        if delta > -10: status = "C'est un bon coup, le plus précis actuellement."
                        elif delta <= -300: status = "C'est une gaffe majeure entraînant une perte catastrophique."
                        elif delta <= -150: status = "C'est une erreur sérieuse qui fait perdre un avantage significatif."
                        elif delta <= -80: status = "C'est une imprécision qui dégrade légèrement la position."
                        elif delta <= -30: status = "C'est un coup jouable, mais il existe une alternative légèrement plus précise."
                        else: status = "C'est un coup solide et tout à fait correct."
                    
                    if raw != best_move_fr and delta < -20:
                        alt_context = f"Meilleure alternative : {best_move_fr}\n  "
                        alt_rule = "\n7. Mentionne le meilleur coup alternatif"
                    else:
                        alt_context = ""
                        alt_rule = ""
                    
                    events_text = f"Événement : {tactics}" if tactics != "Continuité" else ""
                    
                    system_prompt = f"""Tu es un parseur de données strict. Ton unique objectif est de transformer les variables brutes fournies dans la section "FAITS" en une seule phrase naturelle en français.
RÈGLES :
1. Utilise EXCLUSIVEMENT le vocabulaire, les pièces et les événements fournis dans les "FAITS".
2. Si un attribut est vide ou absent, n'en parle pas.
3. Si la mention "via :" apparaît dans les faits, tu dois obligatoirement la mentionner telle quelle avec la pièce concernée.
4. Génère uniquement la phrase finale, sans aucune introduction, conclusion ou justification.
5. RÈGLE ABSOLUE : utilise l'expression "mettre en échec" ou le mot "échec" uniquement pour le Roi. Cet échec peut être direct ou indirect mais ne doit jamais être utilisé pour d'autres pièces.
6. RÈGLE ABSOLUE : Si l'événement est une simple capture de pion sans tactique associée, ce n'est pas un coup tactique significatif.
7. RÈGLE ABSOLUE : Tu as l'INTERDICTION d'inventer des menaces, des échecs ou des conséquences tactiques qui ne sont pas explicitement écrites dans les FAITS.{alt_rule}"""

                    messages = [{"role": "system", "content": system_prompt}]
                    
                    if "bon coup" in status.lower() or "solide" in status.lower():
                        messages.extend(AIAnalyzer.FEW_SHOT_BANK["bon_coup"])
                    elif "imprécision" in status.lower():
                        messages.extend(AIAnalyzer.FEW_SHOT_BANK["imprecision"])
                    elif "erreur" in status.lower() or "gaffe" in status.lower():
                        # Utilisation dynamique de la bonne clé selon la gravité
                        if alt_context:
                            if "gaffe" in status.lower():
                                messages.extend(AIAnalyzer.FEW_SHOT_BANK["gaffe_tactique_alternative"])
                            else:
                                messages.extend(AIAnalyzer.FEW_SHOT_BANK["erreur_avec_alternative"])
                        # Injection croisée si l'erreur implique une perte matérielle tactique
                        if tactics != "Continuité" and "perte matérielle" in tactics.lower():
                            messages.extend(AIAnalyzer.FEW_SHOT_BANK["perte_materielle"])

                    # 3. Ajout de la requête finale (le vrai coup à analyser)
                    messages.append({
                        "role": "user", 
                        "content": f"FAITS :\nJoueur : {turn_color}\nCoup : {san_fr}\nQualité : {status}\n{events_text}\n{alt_context}\n\nCOMMENTAIRE :"
                    })
                    
                    options = {'temperature': 0.0, 'top_p': 0.1, 'num_predict': 70, 'repeat_penalty': 1.0}
                    
                    fallback_comment = "Analyse LLM échouée."
                    if delta < -50: fallback_comment = "Coup très mauvais : menace grave non évitée."
                    elif delta == 0 or delta > -10: fallback_comment = "Coup bon : maintient la pression."
                    else: fallback_comment = "Coup neutre : pas de menace immédiate."
                    
                    comment = AIAnalyzer.query_llm(messages, options, context_log=f"Commentaire de {san_fr}", fallback=fallback_comment)
                    return comment, final_move_str

            except Exception as e:
                Logger.debug_log(f"Analyse Stockfish échouée : {str(e)}. Fallback.", "ERROR")
                return "Analyse impossible : erreur de calcul.", move_raw
        
        if "x" in raw: return "Coup de prise : attention à la position des pièces.", move_raw
        elif "#" in raw: return "Échec et mat. La partie est terminée.", move_raw
        elif "+" in raw: return "Coup d'échec : menace immédiate.", move_raw
        else: return "Coup neutre : pas de menace immédiate.", move_raw
