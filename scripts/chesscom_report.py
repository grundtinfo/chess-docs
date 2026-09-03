import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path
from collections import defaultdict

import chess
import chess.pgn
import requests

from functools import partial
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

# Ajoute le répertoire parent au chemin de recherche des modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer
from classes.ai_analyzer import AIAnalyzer
from classes.pdf_components import ChessboardFlowable, EloProgressionChart, PDFUtils, WinDrawLossBar, ChapterMarker
from classes.json_cache import CacheManager

def is_bot_game(game, player_name=None):
    opponent_type = str(game.get("opponent_type", "")).lower()
    if opponent_type in {"robot", "bot", "computer", "engine", "ai"}:
        return True

    players = [
        str(game.get("white", {}).get("username", "")),
        str(game.get("black", {}).get("username", ""))
    ]
    if player_name:
        player_lower = player_name.lower()
        players = [name for name in players if name.lower() != player_lower]

    bot_pattern = re.compile(r"(?:bot|engine|stockfish|computer|chess\.com|^ai(?:$|[-_\d]))", re.I)
    return any(bot_pattern.search(name) for name in players)

def opponent_name(game, player_name):
    player_lower = player_name.lower()
    white_name = str(game.get("white", {}).get("username", ""))
    return game.get("black", {}).get("username", "") if white_name.lower() == player_lower else white_name

def game_date(game):
    timestamp = game.get("end_time") or game.get("start_time")
    if not timestamp:
        return "Date inconnue"
    return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y")

def game_category(game, player_name):
    if is_bot_game(game, player_name):
        return "Parties contre les bots"
    time_class = str(game.get("time_class", "")).lower()
    return {
        "daily": "Parties différées",
        "rapid": "Parties rapides",
        "blitz": "Parties Blitz",
        "bullet": "Parties Blitz"
    }.get(time_class, "Autres parties")

def adjusted_estimated_elo(base_elo, precision, move_count):
    """Calibre l'estimation existante avec précision et taille de l'échantillon."""
    if precision is None:
        return base_elo

    precision_elo = 400 + 2800 / (1 + math.exp(-(precision - 70) / 10))
    sample_weight = min(0.5, max(0.15, (move_count - 10) / 100))
    return round((base_elo * (1 - sample_weight)) + (precision_elo * sample_weight))

def update_estimates(game):
    analysis = game.setdefault("analysis", {})
    details = analysis.get("details", [])
    if not details:
        return

    precisions = ChessUtils.calculate_precision_from_details(details)
    base_white, base_black = ChessUtils.calculate_elo_from_details(details)
    analysis["precision_white"] = precisions["white"]
    analysis["precision_black"] = precisions["black"]
    analysis["est_elo_white"] = adjusted_estimated_elo(base_white, precisions["white"], len(details))
    analysis["est_elo_black"] = adjusted_estimated_elo(base_black, precisions["black"], len(details))

def refresh_opening_blunder_data(game):
    for blunder in game.get("analysis", {}).get("opening_blunders", []):
        stockfish_pv = str(blunder.get("stockfish_pv", "")).strip().lower()
        if stockfish_pv not in {"", "aucune", "none"} or not blunder.get("fen"):
            continue

        try:
            board = chess.Board(blunder["fen"])
            pv_line, arrows = AIAnalyzer.force_stockfish_line(
                board, blunder.get("played_uci", "")
            )
            blunder["stockfish_pv"] = pv_line
            blunder["fleches_pv"] = arrows
        except (ValueError, KeyError):
            continue

        if not blunder.get("best_move_san") and blunder.get("best_uci"):
            try:
                blunder["best_move_san"] = ChessUtils.convert_english_to_french_notation(
                    board.san(chess.Move.from_uci(blunder["best_uci"]))
                )
            except (ValueError, chess.IllegalMoveError):
                pass

def parse_game_record(game, username, deep_analysis=False, progress_callback=None, existing_game=None):
    Logger.debug_log(f"Étape Parsing : Début du traitement de la partie (ID/URL: {game.get('url', 'Inconnu')})", "DEBUG")
    
    pgn_text = game.get("pgn")
    if not pgn_text: 
        Logger.debug_log("Étape Parsing : PGN introuvable. Abandon de l'analyse pour cette partie.", "DEBUG")
        return None

    try: 
        game_obj = chess.pgn.read_game(StringIO(pgn_text))
        Logger.debug_log("Étape Parsing : PGN lu avec succès par chess.pgn.", "DEBUG")
    except Exception as e: 
        Logger.debug_log(f"Erreur de lecture du PGN : {e}", "ERROR")
        return None
        
    if not game_obj: return None

    white_name, black_name = game.get("white", {}).get("username", ""), game.get("black", {}).get("username", "")
    result_text = game_obj.headers.get("Result", "*")
    
    w_res = game.get("white", {}).get("result", "")
    b_res = game.get("black", {}).get("result", "")

    if result_text == "*":
        if w_res == "win": result_text = "1-0"
        elif b_res == "win": result_text = "0-1"
        elif w_res in ["agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"]: result_text = "1/2-1/2"

    term_str = "Partie terminée."
    if w_res == "win": term_str = f"Victoire des Blancs (Noirs : {b_res})"
    elif b_res == "win": term_str = f"Victoire des Noirs (Blancs : {w_res})"
    elif w_res in ["agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"]: 
        term_str = f"Nulle ({w_res})"
    elif w_res in ["timeout", "abandoned", "resigned"] or b_res in ["timeout", "abandoned", "resigned"]:
        term_str = "Victoire par abandon ou temps."
        if w_res in ["timeout", "abandoned", "resigned"]: term_str = f"Victoire des Noirs (Blancs : {w_res})"
        else: term_str = f"Victoire des Blancs (Noirs : {b_res})"

    board_before = game_obj.board()
    moves, san_moves = [], []
    for move in game_obj.mainline_moves():
        san_moves.append(board_before.san(move))
        moves.append(move)
        board_before.push(move)

    details, opening_blunders_data = [], []
    est_elo_white, est_elo_black = None, None

    if existing_game and "analysis" in existing_game:
        old_analysis = existing_game["analysis"]
        details = old_analysis.get("details", [])
        opening_blunders_data = old_analysis.get("opening_blunders", [])
        est_elo_white = old_analysis.get("est_elo_white")
        est_elo_black = old_analysis.get("est_elo_black")

    # 1) PRÉ-REMPLISSAGE (Téléchargement de la structure totale)
    if len(details) < len(moves):
        temp_board = game_obj.board()
        for idx, move in enumerate(moves, start=1):
            san_eng = san_moves[idx - 1]
            is_capture = temp_board.is_capture(move) # <-- À vérifier AVANT de pousser le coup
            temp_board.push(move) # <-- MODIFICATION : Pousse le coup AVANT de générer le FEN
            
            if idx > len(details):
                san_fr = ChessUtils.convert_english_to_french_notation(san_eng)
                phase = "opening" if idx <= 12 else "middlegame" if idx <= 30 else "endgame"
                
                details.append({
                    "ply": idx, "move_number": (idx + 1) // 2, "color": "white" if idx % 2 != 0 else "black",
                    "move": san_fr, "raw_san": san_eng, "comment": "", "fen": temp_board.fen(), # FEN maintenant 100% correct
                    "delta": 0, "precision": -9999, "phase": phase,
                    "uci": move.uci(), "is_capture": is_capture, "tactics": ""
                })

    cached_opening = existing_game.get("opening", "Ouverture Inconnue") if existing_game else "Ouverture Inconnue"
    needs_recalc = ChessUtils.is_raw_opening(cached_opening)
    best_opening_name = cached_opening
    
    if needs_recalc:
        board_for_opening = game_obj.board()
        found_name = "Ouverture Inconnue"
        moves_to_check = moves[:20]
        
        # 1. On pousse d'abord tous les coups ciblés
        for m in moves_to_check:
            board_for_opening.push(m)
            
        # 2. Recherche inversée : la première trouvée est la plus spécifique
        for _ in range(len(moves_to_check)):
            op_name = ChessUtils.get_opening_name(board_for_opening)
            
            if op_name != "Ouverture Inconnue" and not ChessUtils.is_raw_opening(op_name):
                found_name = op_name
                break # Interruption immédiate de la boucle
                
            try:
                board_for_opening.pop()
            except IndexError:
                break
                
        best_opening_name = found_name if found_name != "Ouverture Inconnue" else cached_opening

    result_data = {
        "id": game.get("url"),
        "is_complete": existing_game.get("is_complete", False) if existing_game else False,
        "date": datetime.fromtimestamp(game.get("end_time", 0)).strftime("%Y-%m-%d %H:%M") if game.get("end_time") else None,
        "end_time": game.get("end_time"),
        "termination": term_str,
        "result": result_text,
        "time_class": game.get("time_class", "inconnu"),
        "opponent_type": ChessUtils.classify_opponent_type(opponent_name(game, username)),
        "white": {"username": white_name, "elo": game.get("white", {}).get("rating")},
        "black": {"username": black_name, "elo": game.get("black", {}).get("rating")},
        "opening": best_opening_name,
        "deep_analysis": deep_analysis,
        "analysis": {
            "summary": {"opening": {}, "middlegame": {}, "endgame": {}}, 
            "details": details, "blunders": 0, "good_moves": 0,
            "opening_blunders": opening_blunders_data,
            "est_elo_white": est_elo_white,
            "est_elo_black": est_elo_black
        }
    }

    def summarize_details(nodes):
        summary = {
            "opening": {"good_moves": 0, "blunders": 0, "mistakes": 0},
            "middlegame": {"good_moves": 0, "blunders": 0, "mistakes": 0},
            "endgame": {"good_moves": 0, "blunders": 0, "mistakes": 0}
        }
        def parcours_recursif(noeud_list):
            for node in noeud_list:
                phase = node.get("phase", "opening")
                swing = node.get("delta", node.get("swing", 0))
                precision = node.get("precision", -9999)
                
                if swing <= -300: summary[phase]["blunders"] += 1
                elif swing <= -150: summary[phase]["mistakes"] += 1
                elif precision >= -30 and swing > -100: summary[phase]["good_moves"] += 1
                
                if "variations" in node: parcours_recursif(node["variations"])
        parcours_recursif(nodes)
        return summary

    result_data["analysis"]["summary"] = summarize_details(details)
    
    # 2) Sauvegarde immédiate totale avant l'enrichissement
    if progress_callback: progress_callback(result_data)

    if not deep_analysis:
        return result_data

    # --- 3) ENRICHISSEMENT & REPRISE (Coup par Coup) ---
    Logger.debug_log("Étape Analyse Profonde : Démarrage de l'évaluation coup par coup...", "INFO")

    analyzer = StockfishAnalyzer()
    board_before = game_obj.board()
    
    for idx, move in enumerate(moves, start=1):
        detail_node = details[idx - 1]
        
        # Si le coup est déjà analysé (reprise sur crash ou interruption)
        if detail_node.get("precision", -9999) != -9999:
            board_before.push(move)
            continue

        san_eng = san_moves[idx - 1]
        move_raw_en = ChessUtils.remove_special_chars(san_eng)
        
        # 1. Analyse pré-calculée via Stockfish pour mutualiser les appels
        eval_before, eval_after, move_obj = analyzer.analyze_move(board_before, san_eng)
        _, best_eval, best_uci = analyzer.get_best_move_with_eval(board_before.copy())
        
        precomputed = {
            'eval_before': eval_before,
            'eval_after': eval_after,
            'move_obj': move_obj,
            'best_eval': best_eval,
            'best_uci': best_uci
        }
        
        # 2. Génération du commentaire avec IA
        comment, pdf_move_str, tactics, alt_recom = AIAnalyzer.generate_move_comment(
            move_raw_en, san_eng, board_before, is_trap=False, precomputed_data=precomputed
        )
        
        # 3. Calculs des métriques (delta/swing)
        val_before = ChessUtils.get_eval_value(eval_before, board_before)
        
        temp_board_after = board_before.copy()
        temp_board_after.push(move)
        val_after = ChessUtils.get_eval_value(eval_after, temp_board_after)
        
        board_best = board_before.copy()
        if best_uci:
            try:
                board_best.push(chess.Move.from_uci(best_uci))
            except ValueError:
                pass
        val_best = ChessUtils.get_eval_value(best_eval, board_best) if best_eval else val_before

        multiplier = 1 if board_before.turn == chess.WHITE else -1
        delta = (val_after * multiplier) - (val_best * multiplier)
        swing = (val_after * multiplier) - (val_before * multiplier)
        
        if temp_board_after.is_checkmate() or (best_uci and move.uci() == best_uci):
            delta = 0
        
        # 4. Identification des erreurs critiques d'ouverture (Pour le Chapitre 2)
        if idx <= 24 and swing <= -300 and best_uci:
            pv_line = alt_recom
            fleches_pv = []
            
            if not pv_line or pv_line == "Aucune":
                pv_line, fleches_pv = AIAnalyzer.force_stockfish_line(board_before, move.uci())
            else:
                _, fleches_pv = AIAnalyzer.force_stockfish_line(board_before, move.uci())
                
            opening_blunders_data.append({
                "move_number": (idx + 1) // 2,
                "color": "white" if board_before.turn == chess.WHITE else "black",
                "played_move": ChessUtils.convert_english_to_french_notation(san_eng),
                "played_uci": move.uci(),
                "best_uci": best_uci,
                "best_move_san": ChessUtils.convert_english_to_french_notation(
                    board_before.san(chess.Move.from_uci(best_uci))
                ) if best_uci else "N/A",
                "tactics": tactics,
                "stockfish_pv": pv_line,
                "fleches_pv": fleches_pv,
                "fen": board_before.fen()
            })

        # 5. Enrichissement des détails (Pour le Chapitre 3)
        detail_node["comment"] = comment
        detail_node["move"] = pdf_move_str
        detail_node["tactics"] = tactics
        detail_node["delta"] = swing 
        detail_node["precision"] = delta 
        
        board_before.push(move)
        
        # Sauvegarde progressive
        if progress_callback and idx % 5 == 0:
            result_data["analysis"]["summary"] = summarize_details(details)
            progress_callback(result_data)

    # 6. Clôture de l'analyse (Calcul ELO et Résumé final)
    update_estimates(result_data)
    result_data["analysis"]["summary"] = summarize_details(details)
    result_data["is_complete"] = True

    if progress_callback:
        progress_callback(result_data)

    return result_data

# =====================================================================
# RENDU PDF
# =====================================================================

def render_game_analysis_table(game, normal_style, bold_style):
    elements = []
    
    table_data = [[
        Paragraph("<b>Diag</b>", normal_style), Paragraph("<b>N°</b>", normal_style),
        Paragraph("<b>Blanc</b>", normal_style), Paragraph("<b>Noir</b>", normal_style),
        Paragraph("<b>Analyse (Stockfish)</b>", normal_style)
    ]]
    
    rows, current_row = [], None
    for ply in game.get("analysis", {}).get("details", []):
        move_num = ply["move_number"]
        if ply["color"] == "white":
            current_row = {
                "move_number": move_num, 
                "white": ply["move"], "white_comment": ply["comment"], "white_fen": ply["fen"], 
                "white_uci": ply.get("uci"), "white_is_capture": ply.get("is_capture", False),
                "black": "", "black_comment": "", "black_fen": None, 
                "black_uci": None, "black_is_capture": False
            }
            rows.append(current_row)
        else:
            if not current_row or current_row["move_number"] != move_num:
                current_row = {
                    "move_number": move_num, 
                    "white": "", "white_comment": "", "white_fen": None, "white_uci": None, "white_is_capture": False,
                    "black": ply["move"], "black_comment": ply["comment"], "black_fen": ply["fen"],
                    "black_uci": ply.get("uci"), "black_is_capture": ply.get("is_capture", False)
                }
                rows.append(current_row)
            else:
                current_row.update({
                    "black": ply["move"], "black_comment": ply["comment"], "black_fen": ply["fen"],
                    "black_uci": ply.get("uci"), "black_is_capture": ply.get("is_capture", False)
                })

    orientation = chess.WHITE if game["white"]["username"].lower() == game.get("player_focus", "").lower() else chess.BLACK

    for row in rows:
        fen = row.get("black_fen") or row.get("white_fen")
        
        fleches_blanches, fleches_noires, fleches_bordeaux = [], [], []
        
        # Attribution des flèches selon la couleur et si c'est une prise
        if row.get("white_uci"):
            if row.get("white_is_capture"): fleches_bordeaux.append(row["white_uci"])
            else: fleches_blanches.append(row["white_uci"])
                
        if row.get("black_uci"):
            if row.get("black_is_capture"): fleches_bordeaux.append(row["black_uci"])
            else: fleches_noires.append(row["black_uci"])

        diag = ChessboardFlowable(
            fen, size=110, 
            fleches_blanches=fleches_blanches, 
            fleches_noires=fleches_noires, 
            fleches_bordeaux=fleches_bordeaux, 
            orientation=orientation
        ) if fen else ""
        
        parts = []
        if row.get("white_comment"): parts.append(f"<b>Blancs :</b> {row['white_comment']}")
        if row.get("black_comment"): parts.append(f"<b>Noirs :</b> {row['black_comment']}")
        
        table_data.append([
            diag, Paragraph(str(row["move_number"]), bold_style), Paragraph(row.get("white", ""), bold_style),
            Paragraph(row.get("black", ""), bold_style), Paragraph("<br/>".join(parts) if parts else "<i>Développement validé.</i>", normal_style)
        ])
        
    termination_reason = game.get("termination", "Fin de la partie.")
    table_data.append([
        "", Paragraph("<b>Fin</b>", normal_style), 
        Paragraph(f"<i>{termination_reason}</i>", normal_style), "", ""
    ])

    t = Table(table_data, colWidths=[110, 35, 55, 55, 255], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), Config.COLOR_PRIMARY), 
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),                    # Diag centré
        ('ALIGN', (1, 0), (3, -1), 'CENTER'),                    # N°, Blanc, Noir centrés
        ('ALIGN', (4, 0), (4, -1), 'LEFT'),                      # Analyse justifiée
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),                  # Centrage vertical
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, Config.COLOR_BG_LIGHT]),
        ('INNERGRID', (0, 0), (-1, -2), 0.5, Config.COLOR_BORDER), # Sépare les colonnes
        ('BOX', (0, 0), (-1, -2), 0.5, Config.COLOR_BORDER),       # Encadrement
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, Config.COLOR_BORDER),# Ligne finale (Fin)
        ('PADDING', (0, 0), (-1, -1), 6),
        ('SPAN', (2, -1), (4, -1))
    ]))
    elements.append(t)
    return elements

def render_opening_focus(game, normal_style, bold_style, section_style):
    """Génère les diagrammes PDF pour les erreurs critiques en ouverture."""
    elements = []
    blunders_data = game.get("analysis", {}).get("opening_blunders", [])
    
    if not blunders_data:
        return elements
        
    elements.append(Paragraph("Focus sur l'Ouverture (Erreurs Critiques)", section_style))
    elements.append(Spacer(1, 10))
    
    # Définit l'orientation de l'échiquier selon la couleur du joueur focus
    orientation = chess.WHITE if game["white"]["username"].lower() == game.get("player_focus", "").lower() else chess.BLACK
    
    for blunder in blunders_data:
        fen = blunder.get("fen")
        played_uci = blunder.get("played_uci")
        best_uci = blunder.get("best_uci")
        fleches_pv = blunder.get("fleches_pv", [])
        
        # Flèche rouge pour l'erreur jouée, flèches bleues pour la séquence de correction Stockfish
        fleches_rouges = [played_uci] if played_uci else []
        fleches_bleues = fleches_pv if fleches_pv else ([best_uci] if best_uci else [])
        
        diag = ChessboardFlowable(
            fen, size=180, 
            fleches_rouges=fleches_rouges, 
            fleches_bleues=fleches_bleues,
            orientation=orientation
        )
        
        move_num = blunder.get("move_number")
        color = "Blancs" if blunder.get("color") == "white" else "Noirs"
        
        desc = f"<b>Coup {move_num} ({color}) :</b> {blunder.get('played_move')}<br/><br/>"
        desc += f"<b>Problème détecté :</b> {blunder.get('tactics', 'Erreur stratégique')}<br/><br/>"
        desc += f"<b>Ligne Stockfish :</b> {blunder.get('stockfish_pv')}"
        
        # Utilisation de KeepTogether pour éviter de couper le diagramme de son explication
        t = Table([[diag, Paragraph(desc, normal_style)]], colWidths=[200, 320])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 20)
        ]))
        elements.append(KeepTogether(t))
        
    return elements

def build_pdf(output_path, state, player_name, opponent_name=None):
    Logger.debug_log(f"Génération du PDF : {output_path}", "INFO")
    doc = SimpleDocTemplate(output_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=22, leading=26, textColor=Config.COLOR_PRIMARY, spaceAfter=5)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11, leading=14, textColor=Config.COLOR_TEXT, spaceAfter=20)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=16, leading=20, textColor=Config.COLOR_SECONDARY, spaceAfter=12)
    subsection_style = ParagraphStyle("SubSection", parent=styles["Heading3"], fontSize=14, leading=18, textColor=Config.COLOR_MINT, spaceAfter=8)
    normal_style = ParagraphStyle("NormalCustom", parent=styles["Normal"], fontSize=10, leading=14, textColor=Config.COLOR_TEXT)
    bold_style = ParagraphStyle("BoldCustom", parent=normal_style, fontName="Helvetica-Bold")

    elements = [
        Paragraph(f"Rapport Stratégique : {player_name}" + (f" vs {opponent_name}" if opponent_name else ""), title_style),
        Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", subtitle_style),
    ]
    chapter_entries = []

    games = list(state.get("games", {}).values())
    if opponent_name:
        op_lower = opponent_name.lower()
        games = [g for g in games if op_lower in (g["white"]["username"].lower(), g["black"]["username"].lower())]

    # Tri chronologique préservé et garanti pour la suite
    games = sorted([g for g in games if g.get("is_complete", True)], key=lambda x: x.get("end_time", 0))

    for game in games:
        update_estimates(game)

    if not games:
        elements.append(Paragraph("Aucune partie complétée trouvée pour ces critères.", normal_style))
        callback = lambda c, d: PDFUtils.header_footer_callback(c, d, "Rapport Analytique Complet - Chess Docs")
        doc.build(elements, onFirstPage=callback, onLaterPages=callback)
        return

    player_lower = player_name.lower()
    wins = sum(1 for g in games if (g["result"] == "1-0" and g["white"]["username"].lower() == player_lower) or (g["result"] == "0-1" and g["black"]["username"].lower() == player_lower))
    losses = sum(1 for g in games if (g["result"] == "0-1" and g["white"]["username"].lower() == player_lower) or (g["result"] == "1-0" and g["black"]["username"].lower() == player_lower))
    
    games_bots = [g for g in games if game_category(g, player_name) == "Parties contre les bots"]
    games_daily = [g for g in games if game_category(g, player_name) == "Parties différées"]
    games_rapid = [g for g in games if game_category(g, player_name) == "Parties rapides"]
    games_blitz = [g for g in games if game_category(g, player_name) == "Parties Blitz"]

    def get_wdl(cat_games):
        w = sum(1 for g in cat_games if (g["result"] == "1-0" and g["white"]["username"].lower() == player_lower) or (g["result"] == "0-1" and g["black"]["username"].lower() == player_lower))
        l = sum(1 for g in cat_games if (g["result"] == "0-1" and g["white"]["username"].lower() == player_lower) or (g["result"] == "1-0" and g["black"]["username"].lower() == player_lower))
        d = len(cat_games) - w - l
        return w, d, l

    categories = [
        ("Parties différées", games_daily),
        ("Parties rapides", games_rapid),
        ("Parties Blitz", games_blitz),
        ("Parties contre les bots", games_bots)
    ]

    elements.extend([
        ChapterMarker("1. Vue d'ensemble", 1),
        Paragraph("1. Vue d'ensemble", section_style),
        Paragraph(f"Analyse basée sur <b>{len(games)} parties</b>.", normal_style),
        Spacer(1, 10),
        Paragraph("<b>Bilan global :</b>", normal_style),
        WinDrawLossBar(wins, len(games) - wins - losses, losses, width=350, height=20),
        Spacer(1, 15),
        Paragraph("<b>Résumé par sous-catégories :</b>", normal_style),
        Spacer(1, 5)
    ])
    chapter_entries.append((1, "1. Vue d'ensemble"))

    cat_table_data = []
    for cat_name, cat_games in categories:
        if len(cat_games) > 0:
            w, d, l = get_wdl(cat_games)
            cat_table_data.append([
                Paragraph(f"- {cat_name} : {len(cat_games)}", normal_style),
                WinDrawLossBar(w, d, l, width=200, height=15)
            ])
            
    if cat_table_data:
        cat_table = Table(cat_table_data, colWidths=[150, 210])
        cat_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8)
        ]))
        elements.append(cat_table)

    elements.extend([
        ChapterMarker("2. Forces et Faiblesses & Progression ELO (Par type de jeu)", 1),
        Paragraph("2. Forces et Faiblesses & Progression ELO (Par type de jeu)", section_style),
        Paragraph("Progression estimée du niveau de performance par catégorie.", normal_style),
        Spacer(1, 10)
    ])
    chapter_entries.append((1, "2. Forces et Faiblesses & Progression ELO (Par type de jeu)"))
    for cat_name, cat_games in categories:
        if cat_games:
            elements.extend([
                Paragraph(cat_name, subsection_style),
                EloProgressionChart(cat_games, player_name),
                Spacer(1, 10)
            ])

    elements.extend([
        PageBreak(),
        ChapterMarker("3. Focus Théorique des Ouvertures", 1),
        Paragraph("3. Focus Théorique des Ouvertures (via Stockfish)", section_style),
        Spacer(1, 5)
    ])
    chapter_entries.append((1, "3. Focus Théorique des Ouvertures"))

    openings_blunders = defaultdict(list)
    for g in games:
        for blunder in g.get("analysis", {}).get("opening_blunders", []):
            openings_blunders[g.get("opening", "Inconnue")].append(blunder)

    # Nettoyage et tri direct des ouvertures (élimine la redondance et l'erreur de syntaxe)
    valid_top_weak = [item for item in sorted(openings_blunders.items(), key=lambda x: len(x[1]), reverse=True) if item[0] != "Inconnue"][:3]
    
    if not valid_top_weak:
        elements.append(Paragraph("Aucune erreur critique d'ouverture n'a été détectée dans cet échantillon.", normal_style))
    else:
        # --- Tableau de résumé des ouvertures ---
        summary_table_data = [[
            Paragraph("<b>Ouverture</b>", normal_style),
            Paragraph("<b>Nombre d'erreurs</b>", normal_style)
        ]]
        for op_name, blunders_list in valid_top_weak:
            summary_table_data.append([
                Paragraph(op_name, normal_style),
                Paragraph(str(len(blunders_list)), normal_style)
            ])
            
        t_summary = Table(summary_table_data, colWidths=[350, 150])
        t_summary.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), Config.COLOR_PRIMARY), 
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, Config.COLOR_BORDER), 
            ('BOX', (0, 0), (-1, -1), 0.5, Config.COLOR_BORDER),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, Config.COLOR_BG_LIGHT]),
        ]))
        elements.extend([t_summary, Spacer(1, 15)])

        for idx, (op_name, blunders_list) in enumerate(valid_top_weak, 1):
            
            opening_header_parts = [Paragraph(f"3.{idx}, {len(blunders_list)} erreurs récentes ({op_name})", subsection_style)]
            
            # CORRECTIF A : Le bloc `AIAnalyzer.translate_opening_name` a été supprimé ici
            elements.extend(opening_header_parts)
            
            blunder_data = [[
                Paragraph("<b>Diag</b>", normal_style),
                Paragraph("<b>N°</b>", normal_style),
                Paragraph("<b>Gaffe (Orange)</b>", normal_style),
                Paragraph("<b>Meilleure (Bleue)</b>", normal_style),
                Paragraph("<b>Analyse de Stockfish</b>", normal_style)
            ]]
            
            for sample in blunders_list:
                fen = sample.get("fen")
                played_uci = sample.get("played_uci")
                best_uci = sample.get("best_uci")
                
                color_letter = "B" if sample.get("color") == "white" else "N"
                move_num = f"{sample.get('move_number', '?')} {color_letter}"
                
                fleches_oranges = [played_uci] if played_uci else []
                fleches_bleues = [best_uci] if best_uci else []
                orient = chess.WHITE if sample.get("color") == "white" else chess.BLACK
                
                diag = ChessboardFlowable(
                    fen, size=110,
                    fleches_oranges=fleches_oranges, 
                    fleches_bleues=fleches_bleues, 
                    orientation=orient
                ) if fen else ""
                
                summary = AIAnalyzer.get_stockfish_theory_summary(op_name, sample.get('played_move', ''), sample.get('stockfish_pv', ''), sample.get('tactics', ''))
                best_reply_san = sample.get('best_move_san', 'N/A') # <-- MODIFICATION : Corrige l'en-tête du tableau
                
                summary_pdf = summary.replace('\n', '<br/>')
                summary_pdf = summary_pdf.replace("Explication de l'erreur :", "<b>Explication de l'erreur :</b>")
                
                blunder_data.append([
                    diag,
                    Paragraph(move_num, normal_style),
                    Paragraph(sample.get('played_move', ''), normal_style),
                    Paragraph(best_reply_san, normal_style),
                    Paragraph(summary_pdf, normal_style)
                ])
                
            t_blunder = Table(blunder_data, colWidths=[110, 35, 65, 65, 235], repeatRows=1)
            t_blunder.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), Config.COLOR_PRIMARY), 
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (1, 0), (3, -1), 'CENTER'),
                ('ALIGN', (4, 0), (4, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, Config.COLOR_BG_LIGHT]),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, Config.COLOR_BORDER), 
                ('BOX', (0, 0), (-1, -1), 0.5, Config.COLOR_BORDER),
                ('PADDING', (0, 0), (-1, -1), 6)
            ]))
            
            elements.extend([t_blunder, Spacer(1, 15)])

    elements.extend([
        PageBreak(),
        ChapterMarker("4. Analyses des parties", 1),
        Paragraph("4. Analyses des parties", section_style)
    ])
    chapter_entries.append((1, "4. Analyses des parties"))

    cat_mapping = [
        ("4.1 Parties différées", games_daily),
        ("4.2 Parties rapides", games_rapid),
        ("4.3 Parties Blitz", games_blitz),
        ("4.4 Parties contre les bots", games_bots)
    ]

    for cat_title, cat_games in cat_mapping:
        if not cat_games:
            continue

        elements.extend([
            ChapterMarker(cat_title, 2),
            Paragraph(cat_title, subsection_style),
            Spacer(1, 10)
        ])
        chapter_entries.append((2, cat_title))

        for game_index, g in enumerate(cat_games, 1):
            white_name = g.get("white", {}).get("username", "Blanc")
            black_name = g.get("black", {}).get("username", "Noir")
            game_title = (
                f"{cat_title.split(' ', 1)[0]}.{game_index} "
                f"{white_name} (Blancs) - {black_name} (Noirs) - {game_date(g)}"
            )
            g["player_focus"] = player_name
            elements.append(ChapterMarker(game_title, 3))
            elements.append(Paragraph(game_title, subsection_style))
            chapter_entries.append((3, game_title))
            elements.append(Paragraph(
                f"ELO estimé : {g.get('analysis', {}).get('est_elo_white', 'N/A')} "
                f"(Blancs) - {g.get('analysis', {}).get('est_elo_black', 'N/A')} (Noirs) | "
                f"Précision : {g.get('analysis', {}).get('precision_white', 'N/A')}% "
                f"(Blancs) - {g.get('analysis', {}).get('precision_black', 'N/A')}% (Noirs)",
                normal_style
            ))
            elements.append(Paragraph(f"Partie : {g.get('white', {}).get('username', 'Blanc')} vs {g.get('black', {}).get('username', 'Noir')} ({g.get('result')})", bold_style))
            elements.extend(render_game_analysis_table(g, normal_style, bold_style))
            elements.append(Spacer(1, 15))

    table_of_contents = [
        Spacer(1, 15),
        Paragraph("Sommaire", section_style)
    ]
    for level, title in chapter_entries:
        table_of_contents.append(Paragraph(f"{'&nbsp;' * (level - 1) * 4}{title}", normal_style))
    table_of_contents.append(PageBreak())
    elements[2:2] = table_of_contents

    footer = lambda c, d: PDFUtils.header_footer_callback(c, d, "Rapport Analytique Complet - Chess Docs")
    doc.build(elements, onFirstPage=footer, onLaterPages=footer)
    Logger.debug_log(f"PDF généré avec succès : {output_path}", "ESSENTIAL")

# =====================================================================
# MAIN EXECUTION
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Génère un rapport PDF avancé (Head-to-Head, IA, Ouvertures)")
    parser.add_argument("player", help="Nom d'utilisateur Chess.com (Toi)")
    parser.add_argument("--opponent", default=None, help="Adversaire spécifique pour un rapport Head-to-Head")
    parser.add_argument("--months", type=int, default=1, help="Nombre de mois d'historique à récupérer")
    parser.add_argument("--verbose", nargs="?", const=1, default=0, type=int, help="Active les logs")
    parser.add_argument("--max-games", type=int, default=5, help="Nombre max de parties à analyser (0 pour toutes, 5 par défaut)")
    parser.add_argument("--incomplete-only", action="store_true", help="Reprend uniquement l'analyse des parties déjà enregistrées mais incomplètes")
    parser.add_argument("--game-id", type=str, default=None, help="ID ou URL spécifique de la partie à forcer dans l'analyse")
    # --------------------------------------
    
    args = parser.parse_args()

    Logger.set_debug_enabled(bool(args.verbose), level=max(int(args.verbose or 0), 1))
    
    try:
        base_dir = Path(__file__).resolve().parent.parent
        state_path = ChessUtils.build_player_state_path(str(base_dir), args.player)
        
        out_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', f"{args.player}_vs_{args.opponent}" if args.opponent else args.player).strip('_')
        output_path = base_dir / f"{out_name}_report_avance.pdf"
        
        state = CacheManager.load_state(str(state_path))
        if (state.get("player") or "").lower() != args.player.lower():
            state = {"player": args.player, "games": {}}
        
        for game in state.get("games", {}).values():
            update_estimates(game)

        existing_games = state.get("games", {})
        for cached_game in existing_games.values():
            white_name = cached_game.get("white", {}).get("username", "")
            black_name = cached_game.get("black", {}).get("username", "")
            cached_game["opponent_type"] = ChessUtils.classify_opponent_type(
                opponent_name(cached_game, args.player)
            )
        
        # --- LOGIQUE DE FILTRAGE ET DE REPRISE ---
        games_to_process = []
        raw_games = ChessUtils.fetch_player_games(args.player, months=args.months)
        
        # PASSE 1 : TÉLÉCHARGEMENT ET PRÉ-REMPLISSAGE DE TOUTES LES PARTIES
        for g in raw_games:
            game_id = g.get("url")
            if not game_id: continue

            bot_game = is_bot_game(g, args.player)
            pgn_text = g.get("pgn", "")
            if not pgn_text:
                Logger.debug_log(f"Partie ignorée sans PGN: {game_id}", "WARNING")
                continue
            if pgn_text.strip().endswith("*") and not bot_game:
                continue

            if bot_game and not g.get("end_time"):
                g["end_time"] = g.get("start_time") or int(time.time())
            
            if args.game_id and args.game_id not in game_id: continue
            if args.opponent and args.opponent.lower() not in (g.get("white", {}).get("username", "").lower(), g.get("black", {}).get("username", "").lower()): continue
                
            existing_g = existing_games.get(game_id)
            
            if args.incomplete_only:
                if existing_g and ChessUtils.is_game_incomplete(existing_g, require_deep=True):
                    games_to_process.append((g, game_id, existing_g, True))
                continue

            needs_full_analysis = ChessUtils.is_game_incomplete(existing_g, require_deep=True)
            needs_opening_fix = existing_g and ChessUtils.is_raw_opening(existing_g.get("opening", ""))
            
            if needs_full_analysis or needs_opening_fix:
                # 3) Télécharger et sauvegarder la partie entière avant analyse profonde
                if not existing_g or len(existing_g.get("analysis", {}).get("details", [])) == 0:
                    Logger.debug_log(f"Téléchargement et préparation de la partie : {game_id}", "INFO")
                    def pre_save(partial):
                        existing_games[game_id] = partial
                        state["games"] = existing_games
                        CacheManager.save_game(str(state_path), game_id, partial)
                    # Sauvegarde intégrale sans moteur Stockfish (deep_analysis=False)
                    existing_g = parse_game_record(g, args.player, deep_analysis=False, progress_callback=pre_save, existing_game=existing_g)
                
                games_to_process.append((g, game_id, existing_g, needs_full_analysis))
        
        if args.max_games > 0:
            games_to_process = sorted(
                games_to_process,
                key=lambda item: not is_bot_game(item[0], args.player)
            )[:args.max_games]
            
        # PASSE 2 : ENRICHISSEMENT TACTIQUE (MODE REPRISE)
        for g, game_id, existing_g, needs_full_analysis in games_to_process:
            def save_progress_buffered(partial_parsed):
                existing_games[game_id] = partial_parsed
                state["games"] = existing_games
                # Sauvegarde immédiate du cache à chaque coup joué
                CacheManager.save_game(str(state_path), game_id, partial_parsed)
            
            Logger.debug_log(f"Enrichissement tactique de la partie : {game_id}", "INFO")
            parse_game_record(g, args.player, deep_analysis=needs_full_analysis, progress_callback=save_progress_buffered, existing_game=existing_g)

        for game_id, cached_game in existing_games.items():
            before = json.dumps(cached_game.get("analysis", {}).get("opening_blunders", []), sort_keys=True)
            refresh_opening_blunder_data(cached_game)
            after = json.dumps(cached_game.get("analysis", {}).get("opening_blunders", []), sort_keys=True)
            if before != after:
                CacheManager.save_game(str(state_path), game_id, cached_game)
        # -------------------------------------------------
        
        state.update({"player": args.player, "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        CacheManager.save_state(str(state_path), state)
        build_pdf(str(output_path), state, args.player, args.opponent)

    finally:
        StockfishAnalyzer().clear_cache()

if __name__ == "__main__":
    main()
