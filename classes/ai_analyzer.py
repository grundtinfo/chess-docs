import json
import chess
import re
import time
from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer

# Pré-compilation au niveau du module pour éliminer le coût à chaque appel
_OPENING_TRANSLATIONS = [
    (re.compile(r"\bDefense\b", re.I), "Défense"), (re.compile(r"\bVariation\b", re.I), "Variante"),
    (re.compile(r"\bAttack\b", re.I), "Attaque"), (re.compile(r"\bGambit\b", re.I), "Gambit"),
    (re.compile(r"\bSystem\b", re.I), "Système"), (re.compile(r"\bAccepted\b", re.I), "Accepté"),
    (re.compile(r"\bDeclined\b", re.I), "Refusé"), (re.compile(r"\bEnglish\b", re.I), "Anglaise"),
    (re.compile(r"\bOpening\b", re.I), "Ouverture"), (re.compile(r"\bSymmetrical\b", re.I), "Symétrique"),
    (re.compile(r"\bBishop's\b", re.I), "du Fou"), (re.compile(r"\bKing's\b", re.I), "du Roi"),
    (re.compile(r"\bQueen's\b", re.I), "de la Dame"), (re.compile(r"\bSicilian\b", re.I), "Sicilienne"),
    (re.compile(r"\bZukertort\b", re.I), "Zukertort"), (re.compile(r"\bScandinavian\b", re.I), "Scandinave"),
    (re.compile(r"\bFrench\b", re.I), "Française"), (re.compile(r"\bCaro-Kann\b", re.I), "Caro-Kann"),
    (re.compile(r"\bItalian\b", re.I), "Italienne"), (re.compile(r"\bSpanish\b", re.I), "Espagnole"),
    (re.compile(r"\bRuy Lopez\b", re.I), "Ruy Lopez"), (re.compile(r"\bSlav\b", re.I), "Slave"),
    (re.compile(r"\bNimzo-Indian\b", re.I), "Nimzo-Indienne"), (re.compile(r"\bDutch\b", re.I), "Hollandaise"),
    (re.compile(r"\bRussian\b", re.I), "Russe"), (re.compile(r"\bPetrov\b", re.I), "Petrov"),
    (re.compile(r"\bPhilidor\b", re.I), "Philidor"), (re.compile(r"\bAlekhine\b", re.I), "Alekhine"),
    (re.compile(r"\bPirc\b", re.I), "Pirc"), (re.compile(r"\bModern\b", re.I), "Moderne"),
    (re.compile(r"\bReti\b", re.I), "Réti"), (re.compile(r"\bBird\b", re.I), "Bird"),
    (re.compile(r"\bIndian\b", re.I), "Indienne"), (re.compile(r"\bTwo Knights\b", re.I), "des Deux Cavaliers"),
    (re.compile(r"\bFour Knights\b", re.I), "des Quatre Cavaliers"), (re.compile(r"\bGiuoco Piano\b", re.I), "Giuoco Piano"),
    (re.compile(r"\bEvans\b", re.I), "Evans"), (re.compile(r"\bExchange\b", re.I), "d'Échange"),
    (re.compile(r"\bAdvance\b", re.I), "d'Avance"), (re.compile(r"\bClassical\b", re.I), "Classique"),
    (re.compile(r"\bTarrasch\b", re.I), "Tarrasch"), (re.compile(r"\bNajdorf\b", re.I), "Najdorf"),
    (re.compile(r"\bDragon\b", re.I), "Dragon"), (re.compile(r"\bScheveningen\b", re.I), "Scheveningen"),
    (re.compile(r"\bClosed\b", re.I), "Fermée"), (re.compile(r"\bOpen\b", re.I), "Ouverte"),
    (re.compile(r"\bMain Line\b", re.I), "Ligne Principale"), (re.compile(r"\bGame\b", re.I), "Partie"),
    (re.compile(r"\bScotch\b", re.I), "Écossaise"), (re.compile(r"\bVienna\b", re.I), "Viennoise"),
    (re.compile(r"\bPawn\b", re.I), "Pion"), (re.compile(r"\bKnights\b", re.I), "Cavaliers"),
    (re.compile(r"\bBishops\b", re.I), "Fous"), (re.compile(r"\bKing's Indian\b", re.I), "Est-Indienne"),
    (re.compile(r"\bQueen's Indian\b", re.I), "Ouest-Indienne"), (re.compile(r"\bCatalan\b", re.I), "Catalane"),
    (re.compile(r"\bBenoni\b", re.I), "Benoni"), (re.compile(r"\bLondon\b", re.I), "de Londres"),
    (re.compile(r"\bGrob\b", re.I), "Grob"), (re.compile(r"\bBorg\b", re.I), "Borg")
]

class AIAnalyzer:

    @staticmethod
    def get_stockfish_theory_summary(opening_name, bad_move, stockfish_line, tactics=""):
        summary = f"Ligne Stockfish : {stockfish_line}\n\nDans l'ouverture {opening_name}, suite au coup {bad_move}, c'est la ligne recommandée par le moteur pour rééquilibrer la position."
        
        if tactics:
            tactics_clean = tactics.replace("- Meilleure ligne calculée :", "").strip()
            summary += f"\n\nExplication de l'erreur : {tactics_clean}"
            
        Logger.debug_log(f"[Génération Théorie] {opening_name} | Coup {bad_move} -> {summary}", "DEBUG")
        
        return summary

    @staticmethod
    def translate_opening_name(opening_name):
        if not opening_name or opening_name == "Ouverture Inconnue":
            return opening_name

        result = opening_name.strip()
        for compiled_pattern, fr_str in _OPENING_TRANSLATIONS:
            result = compiled_pattern.sub(fr_str, result)
            
        result = re.sub(r'\b([a-zA-ZÀ-ÿ]+)\s+(Défense|Ouverture|Variante|Attaque|Gambit|Système)\b', r'\2 \1', result, flags=re.IGNORECASE)

        def titlecase_custom(match):
            return match.group(0).capitalize()
        
        result = re.sub(r'\b[a-zA-ZÀ-ÿ]+\b', titlecase_custom, result)
        
        mots_de_liaison = ["De", "Du", "Des", "La", "Le", "Les", "À", "En", "Et", "D'"]
        for mot in mots_de_liaison:
            result = re.sub(rf'\b{mot}\b', mot.lower(), result, flags=re.IGNORECASE)
            
        result = result.replace("D' ", "d'").replace("d' ", "d'")

        return result.strip()

    @staticmethod
    def detect_tactics(board_before, move_obj, eval_after=None, future_moves=None, delta=None):
        Logger.debug_log(f"Détection des tactiques pour le coup {move_obj.uci()}...", "INFO")
        tactics = []
        moving_piece = board_before.piece_at(move_obj.from_square)
        moving_piece_name = ChessUtils.get_piece_name_fr(moving_piece)
        to_square_name = chess.square_name(move_obj.to_square)
        
        if board_before.is_capture(move_obj):
            captured_piece = board_before.piece_at(move_obj.to_square)
            if captured_piece:
                captured_name = ChessUtils.get_piece_name_fr(captured_piece)
                tactics.append(f"{moving_piece_name} prend {captured_name} en {to_square_name}")
            else:
                tactics.append(f"{moving_piece_name} prend en passant en {to_square_name}")
        
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
                if piece and piece.color == board_after.turn and piece.piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.KING]:
                    targets.append(f"{ChessUtils.get_piece_name_fr(piece)} en {chess.square_name(sq)}")
            
            if len(targets) >= 2:
                targets_str = ", ".join(targets)
                tactics.append(f"{moving_piece_name} en {to_square_name} réalise une fourchette attaquant simultanément : {targets_str}")

            defender_color = board_after.turn
            pinned_pieces = []
            # Optimization: vérifie uniquement les cases occupées par le défenseur (~10-16 cases au lieu de 64)
            # Correction : Utilisation de chess.SquareSet car occupied_co retourne un entier non itérable
            for sq in chess.SquareSet(board_after.occupied_co[defender_color]):
                if board_after.is_pinned(defender_color, sq):
                    if not board_before.is_pinned(defender_color, sq):
                        piece = board_after.piece_at(sq)
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

                # NOUVEAU BLOC
                # NOUVEAU BLOC (SÉCURISÉ)
                if t == 'mate':
                    analyzer = StockfishAnalyzer()
                    sf = analyzer.get_engine()
                    if sf:
                        try:
                            sim_board = board_after.copy()
                            seq_eng = []
                            for _ in range(abs(val) * 2): 
                                if sim_board.is_game_over(): break
                                best_uci = analyzer._get_cached_best_move(sim_board.fen())
                                if not best_uci: break
                                move_obj_sim = sim_board.parse_uci(best_uci)
                                san_eng = sim_board.san(move_obj_sim)
                                seq_eng.append(san_eng)
                                sim_board.push(move_obj_sim)

                            is_in_trap = False
                            if future_moves:
                                match_len = min(len(future_moves), len(seq_eng))
                                if match_len > 0 and all(future_moves[i] == seq_eng[i] for i in range(match_len)):
                                    is_in_trap = True
                                    
                            formatted_seq = ChessUtils.parse_stockfish_pv(" ".join(seq_eng), is_white_turn=(board_after.turn == chess.WHITE), start_move_number=board_after.fullmove_number) if seq_eng else ""
                            
                            if is_in_trap:
                                tactics.append("Mat inévitable (suite illustrée)")
                            else:
                                tactics.append(f"Mat inévitable via : {formatted_seq}")
                        except Exception as e:
                            Logger.debug_log(f"Erreur simulation mat : {e}", "WARNING")
                    
                elif t == 'cp':
                    cp_val = val * player_multiplier
                    if cp_val >= 300 and delta is not None and delta >= 150 and not any("Capture" in t for t in tactics):
                        tactics.append("Prépare un gain matériel décisif imminent")
                    elif delta is not None and delta <= -30:
                        piece_lost = None
                        lost_square = None
                        seq_eng = []
                        
                        sim_board = board_after.copy()
                        analyzer = StockfishAnalyzer()
                        sf = analyzer.get_engine()
                        original_color = board_after.turn 
                        
                        def get_material_score(b, c):
                            return len(b.pieces(chess.PAWN, c)) + 3 * len(b.pieces(chess.KNIGHT, c)) + 3 * len(b.pieces(chess.BISHOP, c)) + 5 * len(b.pieces(chess.ROOK, c)) + 9 * len(b.pieces(chess.QUEEN, c))
                        
                        mat_before = get_material_score(sim_board, original_color)
                        mat_opp_before = get_material_score(sim_board, not original_color)
                        
                        if sf:
                            for _ in range(6):
                                if sim_board.is_game_over(): break
                                best_uci = analyzer._get_cached_best_move(sim_board.fen())
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
                                sim_board.push(move_obj_sim)
                                
                        mat_after = get_material_score(sim_board, original_color)
                        mat_opp_after = get_material_score(sim_board, not original_color)
                        
                        blunderer_loss = mat_opp_before - mat_opp_after
                        opponent_loss = mat_before - mat_after
                        net_loss_for_blunderer = blunderer_loss - opponent_loss

                        formatted_seq = ChessUtils.parse_stockfish_pv(" ".join(seq_eng), is_white_turn=(board_after.turn == chess.WHITE), start_move_number=board_after.fullmove_number) if seq_eng else ""
                        formatted_seq_3 = ChessUtils.parse_stockfish_pv(" ".join(seq_eng[:3]), is_white_turn=(board_after.turn == chess.WHITE), start_move_number=board_after.fullmove_number) if seq_eng else ""

                        if net_loss_for_blunderer > 0:
                            if piece_lost:
                                is_in_trap = False
                                if future_moves:
                                    match_len = min(len(future_moves), len(seq_eng))
                                    if match_len > 0 and all(future_moves[i] == seq_eng[i] for i in range(match_len)):
                                        is_in_trap = True

                                is_fem = piece_lost in ["Dame", "Tour"]
                                adj_mise = "mise" if is_fem else "mis"
                                adj_exp = "exposée" if is_fem else "exposé"

                                if len(seq_eng) == 1:
                                    loss_desc = f"{piece_lost} en {lost_square} est {adj_mise} en prise directe"
                                else:
                                    loss_desc = f"{piece_lost} en {lost_square} est {adj_exp} à une perte matérielle en quelques coups"
                                
                                if is_in_trap:
                                    tactics.append(f"{loss_desc} (suite illustrée)")
                                else:
                                    tactics.append(f"{loss_desc} via : {formatted_seq}")
                            else:
                                seq_str = f" via : {formatted_seq_3}" if formatted_seq_3 else ""
                                if delta <= -150:
                                    tactics.append(f"Expose le joueur à une lourde perte matérielle (pion clé ou qualité){seq_str}")
                                else:
                                    tactics.append(f"Entraîne une perte matérielle ou concède un avantage tactique décisif{seq_str}")
                        else:
                            seq_str = f" via : {formatted_seq_3}" if formatted_seq_3 else ""
                            if delta <= -150:
                                tactics.append(f"Erreur stratégique majeure causant une détérioration critique de la position{seq_str}")
                            elif delta <= -80:
                                tactics.append(f"Concession positionnelle permettant à l'adversaire de prendre l'initiative{seq_str}")
                            else:
                                tactics.append(f"Coup douteux qui déséquilibre ou affaiblit la position{seq_str}")
                        
        tactics_comment = " ; ".join(tactics) if tactics else ""
        
        if tactics_comment:
            Logger.debug_log(f"[Génération Tactique] Événement détecté pour le coup {move_obj.uci()} : {tactics_comment}", "DEBUG")
        else:
            Logger.debug_log(f"Aucun événement tactique pour le coup : {move_obj.uci()}", "INFO")
            
        return tactics_comment

    @staticmethod
    def generate_move_comment(move_raw, move_san, board_state, is_trap=False, played_continuation=None, best_alternative=None, future_moves=None, precomputed_data=None):
        raw = ChessUtils.remove_special_chars(move_raw.strip())
        board = chess.Board(board_state.fen())
        turn_color = "Blancs" if board.turn == chess.WHITE else "Noirs"
        
        continuation = played_continuation if played_continuation is not None else future_moves
        
        analyzer = StockfishAnalyzer()
        engine = analyzer.get_engine()
        
        tactics = "" 
        best_pv_san = None 
        alt_recom_value = "Aucune"
        
        if engine:
            try:
                if precomputed_data:
                    eval_before = precomputed_data.get('eval_before')
                    eval_after = precomputed_data.get('eval_after')
                    move_obj = precomputed_data.get('move_obj')
                    best_eval = precomputed_data.get('best_eval')
                    best_uci = precomputed_data.get('best_uci')
                else:
                    Logger.debug_log(f"Stockfish : Analyse du coup {raw}", "INFO")
                    eval_before, eval_after, move_obj = analyzer.analyze_move(board, move_san)
                    Logger.debug_log(f"Stockfish : Évaluation du meilleur coup alternatif pour {raw}", "INFO")
                    _, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
                
                if eval_before and eval_after and move_obj:
                    board_after = board.copy()
                    board_after.push(move_obj)
                    board_best = board.copy()
                    if best_uci:
                        try:
                            board_best.push(chess.Move.from_uci(best_uci))
                        except Exception:
                            pass
                    
                    # CORRECTION : Définition de player_multiplier
                    player_multiplier = 1 if board.turn == chess.WHITE else -1
                    
                    val_before = ChessUtils.get_eval_value(eval_before, board)
                    val_after = ChessUtils.get_eval_value(eval_after, board_after)
                    val_best = ChessUtils.get_eval_value(best_eval, board_best)
                    
                    # Évaluations relatives au joueur qui vient de jouer
                    eval_player_before = val_before
                    eval_player_after = -val_after
                    eval_player_best = -val_best
                    
                    delta = eval_player_after - eval_player_best
                    swing = eval_player_after - eval_player_before
                    if move_obj and best_uci and move_obj.uci() == best_uci: delta = 0

                    san_eng = board.san(move_obj).strip() 
                    san_fr = ChessUtils.convert_english_to_french_notation(san_eng)

                    is_sacrifice = False
                    piece_moved = board.piece_at(move_obj.from_square)
                    piece_name = ChessUtils.get_piece_name_fr(piece_moved) if piece_moved else "Pièce"
                    
                    if piece_moved and piece_moved.piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                        if board.is_attacked_by(not board.turn, move_obj.to_square):
                            is_sacrifice = True

                    t_before = eval_before.get('type', 'cp') if isinstance(eval_before, dict) else getattr(eval_before, 'type', 'cp')
                    t_after = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else getattr(eval_after, 'type', 'cp')
                    val_after_raw = eval_after.get('value', 0) if isinstance(eval_after, dict) else (eval_after.value if hasattr(eval_after, 'value') and eval_after.value is not None else 0)
                    
                    mate_status = ""
                    is_blunder_into_mate = False

                    if board_after.is_checkmate():
                        mate_status = "Échec et mat sur l'échiquier"
                    elif t_after == 'mate' and val_after_raw != 0:
                        side_to_move_after = board_after.turn
                        val_after_absolute = val_after_raw if side_to_move_after == chess.WHITE else -val_after_raw
                        winning_side = "les Blancs" if val_after_absolute > 0 else "les Noirs"
                        
                        is_mate_for_player = (val_after_absolute > 0 and board.turn == chess.WHITE) or (val_after_absolute < 0 and board.turn == chess.BLACK)
                        
                        mate_in = abs(val_after_raw)
                        
                        is_mate_missed = False
                        if is_mate_for_player and continuation:
                            if len(continuation) >= mate_in * 2:
                                is_mate_missed = True

                        if not best_pv_san:
                            try:
                                sim_board = board.copy()
                                pv_list = []
                                for _ in range(abs(val_after_raw) * 2): 
                                    m_best = analyzer._get_cached_best_move(sim_board.fen())
                                    if not m_best: break
                                    m_sim = sim_board.parse_uci(m_best)
                                    pv_list.append(sim_board.san(m_sim))
                                    sim_board.push(m_sim)
                                
                                if pv_list:
                                    best_pv_san = ChessUtils.parse_stockfish_pv(" ".join(pv_list), is_white_turn=(board.turn == chess.WHITE), start_move_number=board.fullmove_number)
                                    alt_recom_value = best_pv_san
                            except Exception:
                                pass

                        if not is_mate_for_player:
                            if t_before != 'mate':
                                mate_status = f"Gaffe critique - Autorise un Mat forcé en {mate_in} coups par {winning_side}"
                            else:
                                mate_status = f"Mat forcé en {mate_in} coups par {winning_side}"
                            is_blunder_into_mate = True
                        elif is_mate_for_player and not is_mate_missed:
                            mate_status = f"Mat forcé en {mate_in} coups par {winning_side}"

                    eval_symbol = ""
                    qualif_math = "Coup solide"
                    
                    mate_in_val = (val_after_raw * player_multiplier) if t_after == 'mate' else 0
                    if is_sacrifice and t_after == 'mate' and 0 < mate_in_val <= 3: 
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
                    
                    pdf_move_str = f"{san_fr}{eval_symbol}"
                    
                    tactics = AIAnalyzer.detect_tactics(board, move_obj, eval_after, continuation, delta=delta)
                    
                    if board_after.is_checkmate():
                        tactics = ""
                    
                    if qualif_math in ["Meilleur coup", "Excellent coup", "Coup brillant", "Coup solide"] and tactics:
                        tact_list = tactics.split(" ; ")
                        tactics = " ; ".join([t for t in tact_list if not any(term in t.lower() for term in ["perte", "expose", "gaffe"])])
                    
                    if "via :" in tactics:
                        tactics = tactics.replace("via :", "- Meilleure ligne calculée :")
                    elif "(suite illustrée)" in tactics:
                        tactics = tactics.replace("(suite illustrée)", "- Meilleure ligne calculée : (illustrée dans la partie)")
                        
                    eval_exacte = mate_status if mate_status else qualif_math
                    if tactics:
                        eval_exacte += f" - Tactique : {tactics}"
                        
                    if "- Meilleure ligne calculée :" in eval_exacte:
                        parts = eval_exacte.split("- Meilleure ligne calculée :", 1)
                        eval_exacte = f'{parts[0]}- Meilleure ligne calculée : "{parts[1].strip()}"'
                    
                    if best_pv_san is None:
                        alt_recom_value = "Aucune"

                    if delta < -30 and best_uci and not board_after.is_checkmate() and best_pv_san is None:
                        try:
                            sim_board = board.copy()
                            pv_list = []
                            for _ in range(4):
                                m_best = analyzer._get_cached_best_move(sim_board.fen())
                                if not m_best: break
                                m_sim = sim_board.parse_uci(m_best)
                                pv_list.append(sim_board.san(m_sim))
                                sim_board.push(m_sim)
                            
                            best_pv_san = ChessUtils.parse_stockfish_pv(" ".join(pv_list), is_white_turn=(board.turn == chess.WHITE), start_move_number=board.fullmove_number)
                            if best_pv_san:
                                alt_recom_value = best_pv_san
                        except Exception:
                            pass

                    # Construction directe du commentaire déterministe
                    comment_final = f"{eval_exacte}."
                    if alt_recom_value != "Aucune" and (not best_uci or move_obj.uci() != best_uci):
                        comment_final += f" L'alternative recommandée était : {alt_recom_value}."

                    Logger.debug_log(f"[Génération Commentaire] {pdf_move_str} -> {comment_final.strip()}", "DEBUG")

                    return comment_final.strip(), pdf_move_str, tactics, alt_recom_value

            except Exception as e:
                Logger.debug_log(f"Analyse Stockfish échouée : {str(e)}. Fallback.", "ERROR")
                return "Analyse impossible : erreur de calcul.", ChessUtils.convert_english_to_french_notation(move_san), tactics, "Aucune"
        
        san_fr_fb = ChessUtils.convert_english_to_french_notation(move_san)
        
        if "x" in raw: 
            fallback_comment = "Coup de prise : attention à la position des pièces."
        elif "#" in raw: 
            fallback_comment = "Échec et mat. La partie est terminée."
        elif "+" in raw: 
            fallback_comment = "Coup d'échec : menace immédiate."
        else: 
            fallback_comment = "Coup neutre : pas de menace immédiate."
            
        Logger.debug_log(f"[Génération Fallback] {san_fr_fb} -> {fallback_comment}", "DEBUG")
        
        return fallback_comment, san_fr_fb, tactics, "Aucune"
