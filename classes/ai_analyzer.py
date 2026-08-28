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
        tactics_clean = tactics.replace("- Meilleure ligne calculée :", "").strip() if tactics else ""
        
        # Adaptation dynamique selon le contexte tactique
        if "mat" in tactics_clean.lower():
            objectif = "concrétiser une opportunité de mat ou éviter une défaite rapide"
        elif any(kw in tactics_clean.lower() for kw in ["perte", "expose", "prise"]):
            objectif = "préserver le matériel et maintenir la stabilité de la position"
        elif any(kw in tactics_clean.lower() for kw in ["avantage", "gain"]):
            objectif = "accentuer l'avantage tactique et concrétiser la domination"
        else:
            objectif = "obtenir la meilleure continuité positionnelle selon le moteur"

        summary = f"Ligne Stockfish : {stockfish_line}\n\nDans l'ouverture {opening_name}, suite au coup {bad_move}, c'est la ligne recommandée par le moteur pour {objectif}."
        
        if tactics_clean:
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
    def detect_tactics(board_before, move_obj, eval_after=None, future_moves=None, delta=None, best_eval=None, best_pv_san=None):
        Logger.debug_log(f"Détection des tactiques pour le coup {move_obj.uci()}...", "INFO")
        tactics = []
        moving_piece = board_before.piece_at(move_obj.from_square)
        moving_piece_name = ChessUtils.get_piece_name_fr(moving_piece)
        to_square_name = chess.square_name(move_obj.to_square)
        
        board_after = board_before.copy()
        board_after.push(move_obj)

        # Détection d'un mat manqué si le meilleur coup alternatif offrait un mat forcé
        if best_eval and not board_after.is_checkmate():
            t_best = getattr(best_eval, 'type', 'cp') if hasattr(best_eval, 'type') else (best_eval.get('type', 'cp') if isinstance(best_eval, dict) else 'cp')
            val_best_raw = getattr(best_eval, 'value', 0) if hasattr(best_eval, 'value') else (best_eval.get('value', 0) if isinstance(best_eval, dict) else 0)
            
            # Dans board_best, val_best_raw < 0 indique que l'adversaire subit un mat (mat forcé pour le joueur)
            if t_best == 'mate' and val_best_raw is not None and val_best_raw < 0:
                mate_in_best = abs(val_best_raw)
                alt_str = f" (meilleur coup : {best_pv_san})" if best_pv_san else ""
                tactics.append(f"Manque un échec et mat forcé en {mate_in_best} coup(s){alt_str}")

        if board_before.is_capture(move_obj):
            captured_piece = board_before.piece_at(move_obj.to_square)
            if captured_piece:
                captured_name = ChessUtils.get_piece_name_fr(captured_piece)
                tactics.append(f"{moving_piece_name} prend {captured_name} en {to_square_name}")
            else:
                tactics.append(f"{moving_piece_name} prend en passant en {to_square_name}")
        
        if board_after.is_checkmate():
            tactics.append(f"Mat par {moving_piece_name} en {to_square_name}")
        else:
            if board_after.is_check():
                defender_color = board_after.turn
                attacker_color = not defender_color
                king_sq = board_after.king(defender_color)
                if king_sq is not None:
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
            for sq in chess.SquareSet(board_after.occupied_co[defender_color]):
                if board_after.is_pinned(defender_color, sq):
                    if not board_before.is_pinned(defender_color, sq):
                        piece = board_after.piece_at(sq)
                        if piece:
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
                    analyzer = StockfishAnalyzer()
                    sf = analyzer.get_engine()
                    if sf:
                        try:
                            seq_eng = analyzer.get_fast_pv_sequence(board_after, max_moves=abs(val) * 2)

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
                    val_white_centric = ChessUtils.get_eval_value(eval_after, board_after)
                    player_color = board_before.turn
                    multiplier = 1 if player_color == chess.WHITE else -1
                    cp_val = val_white_centric * multiplier
                    
                    if cp_val >= 300 and delta is not None and delta >= 150 and not any("prend" in tact for tact in tactics):
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
                            seq_eng = analyzer.get_fast_pv_sequence(board_after, max_moves=6)
                            
                            # MODIFICATION : Traçage des pièces d'origine pour éviter les hallucinations
                            orig_pieces = {sq: p for sq, p in board_after.piece_map().items() if p.color == original_color}
                            current_positions = {sq: sq for sq in orig_pieces.keys()}
                            lost_pieces = []
                            
                            for san_move in seq_eng:
                                try:
                                    move_obj_sim = sim_board.parse_san(san_move)
                                    from_sq = move_obj_sim.from_square
                                    to_sq = move_obj_sim.to_square
                                    
                                    # 1. Détection de capture
                                    captured_sq = to_sq
                                    if sim_board.is_en_passant(move_obj_sim):
                                        captured_sq = to_sq - 8 if sim_board.turn == chess.WHITE else to_sq + 8
                                        
                                    captured_piece = sim_board.piece_at(captured_sq)
                                    if captured_piece and captured_piece.color == original_color:
                                        orig_sq = None
                                        for start_sq, curr_sq in current_positions.items():
                                            if curr_sq == captured_sq:
                                                orig_sq = start_sq
                                                break
                                        if orig_sq is not None:
                                            lost_pieces.append((orig_pieces[orig_sq].piece_type, orig_sq))
                                            del current_positions[orig_sq] # La pièce n'est plus sur l'échiquier
                                            
                                    # 2. Mise à jour de la position de la pièce si elle a bougé
                                    if sim_board.turn == original_color:
                                        orig_sq = None
                                        for start_sq, curr_sq in current_positions.items():
                                            if curr_sq == from_sq:
                                                orig_sq = start_sq
                                                break
                                        if orig_sq is not None:
                                            current_positions[orig_sq] = to_sq
                                            
                                    sim_board.push(move_obj_sim)
                                except Exception:
                                    break
                                
                            if lost_pieces:
                                piece_values = {chess.QUEEN: 9, chess.ROOK: 5, chess.BISHOP: 3, chess.KNIGHT: 3, chess.PAWN: 1}
                                lost_pieces.sort(key=lambda x: piece_values.get(x[0], 0), reverse=True)
                                best_lost_pt, best_orig_sq = lost_pieces[0]
                                
                                if best_lost_pt == chess.QUEEN: piece_lost = "Dame"
                                elif best_lost_pt == chess.ROOK: piece_lost = "Tour"
                                elif best_lost_pt == chess.BISHOP: piece_lost = "Fou"
                                elif best_lost_pt == chess.KNIGHT: piece_lost = "Cavalier"
                                
                                if piece_lost:
                                    lost_square = chess.square_name(best_orig_sq)
                                
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

        # Suppression des félicitations tactiques (fourchette, échec) si le coup est mathématiquement une gaffe absolue
        if delta is not None and delta <= -150:
            # MODIFICATION : Liste étendue et comparaison insensible à la casse
            bad_kws = ['fourchette', 'échec direct', 'découverte', 'attaque simultanément', 'clouage immobilisant']
            tactics = [t for t in tactics if not any(kw in t.lower() for kw in bad_kws)]
                
        tactics_comment = " ; ".join(tactics) if tactics else ""
        
        if tactics_comment:
            Logger.debug_log(f"[Génération Tactique] Événement détecté pour le coup {move_obj.uci()} : {tactics_comment}", "DEBUG")
        else:
            Logger.debug_log(f"Aucun événement tactique pour le coup : {move_obj.uci()}", "INFO")
            
        return tactics_comment

    @staticmethod
    def generate_move_comment(move_raw, move_san, board_state, is_trap=False, played_continuation=None, best_alternative=None, future_moves=None, precomputed_data=None):
        raw = ChessUtils.remove_special_chars(move_raw.strip())
        board = board_state.copy()
        
        cache_key = None
        trap_cache = {}
        if is_trap:
            from classes.json_cache import CacheManager
            trap_cache = CacheManager.load_cache(CacheManager.TRAP_CACHE_FILE)
            cache_key = f"{board_state.fen()}_{raw}"
            if cache_key in trap_cache:
                Logger.debug_log(f"[Cache Trap] Récupération de l'analyse pour le coup {raw}", "INFO")
                cached = trap_cache[cache_key]
                return cached.get("comment", ""), cached.get("move_str", ""), cached.get("tactics", ""), cached.get("alt_recom", "Aucune")

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
                    
                    san_eng = board.san(move_obj).strip() 
                    san_fr = ChessUtils.convert_english_to_french_notation(san_eng)

                    # OPTIMISATION : Calculer le delta AVANT d'invoquer get_fast_pv_sequence pour économiser les appels Stockfish
                    val_before = ChessUtils.get_eval_value(eval_before, board)
                    val_after = ChessUtils.get_eval_value(eval_after, board_after)
                    
                    board_best = board.copy()
                    if best_uci:
                        try:
                            board_best.push(chess.Move.from_uci(best_uci))
                        except Exception:
                            pass
                    val_best = ChessUtils.get_eval_value(best_eval, board_best) if best_eval else val_before

                    player_color = board.turn
                    multiplier = 1 if player_color == chess.WHITE else -1

                    eval_player_before = val_before * multiplier
                    eval_player_after = val_after * multiplier
                    eval_player_best = val_best * multiplier

                    delta = eval_player_after - eval_player_best
                    swing = eval_player_after - eval_player_before

                    if board_after.is_checkmate() or (best_uci and move_obj.uci() == best_uci):
                        delta = 0

                    # Extraction de la meilleure alternative uniquement si le coup est douteux ou pire (delta <= -30)
                    if best_uci and move_obj.uci() != best_uci and not board_after.is_checkmate() and delta <= -30:
                        try:
                            # Prise en charge d'un précalcul éventuel pour mutualiser les calculs
                            best_pv_san = precomputed_data.get('best_pv_san') if precomputed_data else None
                            if best_pv_san:
                                alt_recom_value = best_pv_san
                            else:
                                seq_eng = analyzer.get_fast_pv_sequence(board, max_moves=4)
                                if seq_eng:
                                    best_pv_san = ChessUtils.parse_stockfish_pv(" ".join(seq_eng), is_white_turn=(board.turn == chess.WHITE), start_move_number=board.fullmove_number)
                                    alt_recom_value = best_pv_san
                        except Exception as e:
                            Logger.debug_log(f"Erreur extraction PV alternative : {e}", "WARNING")

                    t_before = eval_before.get('type', 'cp') if isinstance(eval_before, dict) else getattr(eval_before, 'type', 'cp')
                    t_after = eval_after.get('type', 'cp') if isinstance(eval_after, dict) else getattr(eval_after, 'type', 'cp')
                    val_after_raw = eval_after.get('value', 0) if isinstance(eval_after, dict) else (eval_after.value if hasattr(eval_after, 'value') and eval_after.value is not None else 0)

                    mate_status = ""
                    is_blunder_into_mate = False
                    is_mate_for_player = False

                    if board_after.is_checkmate():
                        mate_status = "Échec et mat sur l'échiquier"
                        is_mate_for_player = True
                    elif t_after == 'mate' and val_after_raw != 0:
                        side_to_move_after = board_after.turn
                        is_mate_for_player = (val_after_raw < 0)
                        winning_side = "les Blancs" if (side_to_move_after == chess.WHITE and val_after_raw > 0) or (side_to_move_after == chess.BLACK and val_after_raw < 0) else "les Noirs"
                        mate_in = abs(val_after_raw)

                        if not is_mate_for_player:
                            if t_before != 'mate':
                                mate_status = f"Gaffe critique - Autorise un Mat forcé en {mate_in} coups par {winning_side}"
                            else:
                                mate_status = f"Mat forcé en {mate_in} coups par {winning_side}"
                            is_blunder_into_mate = True
                        else:
                            mate_status = f"Mat forcé en {mate_in} coups par {winning_side}"

                    is_sacrifice = False
                    piece_moved = board.piece_at(move_obj.from_square)
                    if piece_moved and piece_moved.piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]:
                        if board.is_attacked_by(not board.turn, move_obj.to_square):
                            is_sacrifice = True

                    eval_symbol = ""
                    qualif_math = "Coup solide"

                    if board_after.is_checkmate():
                        qualif_math = "Meilleur coup"
                        eval_symbol = ""
                        alt_recom_value = "Aucune"
                    elif is_blunder_into_mate:
                        eval_symbol = "??"
                        qualif_math = "Gaffe majeure"
                    elif is_sacrifice and is_mate_for_player and 0 < abs(val_after_raw) <= 3:
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

                    tactics = AIAnalyzer.detect_tactics(board, move_obj, eval_after, continuation, delta=delta, best_eval=best_eval, best_pv_san=best_pv_san)

                    if board_after.is_checkmate():
                        tactics = ""

                    if qualif_math in ["Meilleur coup", "Excellent coup", "Coup brillant", "Coup solide"] and tactics and "Manque" not in tactics:
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

                    if board_after.is_checkmate() or (best_uci and move_obj.uci() == best_uci):
                        alt_recom_value = "Aucune"

                    comment_final = f"{eval_exacte}."
                    if alt_recom_value != "Aucune" and (not best_uci or move_obj.uci() != best_uci) and not board_after.is_checkmate():
                        comment_final += f" L'alternative recommandée était : {alt_recom_value}."

                    Logger.debug_log(f"[Génération Commentaire] {pdf_move_str} -> {comment_final.strip()}", "DEBUG")

                    result_tuple = (comment_final.strip(), pdf_move_str, tactics, alt_recom_value)

                    if is_trap and cache_key:
                        trap_cache[cache_key] = {
                            "comment": result_tuple[0],
                            "move_str": result_tuple[1],
                            "tactics": result_tuple[2],
                            "alt_recom": result_tuple[3]
                        }
                        from classes.json_cache import CacheManager
                        CacheManager.save_cache(trap_cache, CacheManager.TRAP_CACHE_FILE)
                        Logger.debug_log(f"[Cache Trap] Nouvelle analyse sauvegardée pour {raw}", "DEBUG")

                    return result_tuple

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
