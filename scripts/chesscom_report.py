import argparse
import json
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

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

# Ajoute le répertoire parent au chemin de recherche des modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer, OllamaManager
from classes.ai_analyzer import AIAnalyzer
from classes.pdf_components import ChessboardFlowable, EloProgressionChart, PDFUtils
from classes.json_cache import CacheManager

def parse_game_record(game, username, deep_analysis=False, progress_callback=None, existing_game=None):
    pgn_text = game.get("pgn")
    if not pgn_text: return None

    try: game_obj = chess.pgn.read_game(StringIO(pgn_text))
    except Exception: return None
    if not game_obj: return None

    white_name, black_name = game.get("white", {}).get("username", ""), game.get("black", {}).get("username", "")
    result_text = game_obj.headers.get("Result", "*")
    
    if result_text == "*":
        w_res, b_res = game.get("white", {}).get("result", ""), game.get("black", {}).get("result", "")
        if w_res == "win": result_text = "1-0"
        elif b_res == "win": result_text = "0-1"
        elif w_res in ["agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"]: result_text = "1/2-1/2"

    board_before = game_obj.board()
    moves, san_moves = [], []
    for move in game_obj.mainline_moves():
        san_moves.append(board_before.san(move))
        moves.append(move)
        board_before.push(move)

    board_before = game_obj.board()
    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine(depth=Config.DEFAULT_STOCKFISH_DEPTH)

    details, opening_blunders_data = [], []
    blunders, good_moves = 0, 0
    opening_phase, middlegame_phase, endgame_phase = [], [], []
    
    est_elo_white = None
    est_elo_black = None

    if existing_game and "analysis" in existing_game:
        old_analysis = existing_game["analysis"]
        details = old_analysis.get("details", [])
        blunders = old_analysis.get("blunders", 0)
        good_moves = old_analysis.get("good_moves", 0)
        opening_blunders_data = old_analysis.get("opening_blunders", [])
        est_elo_white = old_analysis.get("est_elo_white")
        est_elo_black = old_analysis.get("est_elo_black")
        
        for ply_data in details:
            ph = ply_data.get("phase", "opening")
            prec = ply_data.get("precision", -9999)
            bucket = opening_phase if ph == "opening" else middlegame_phase if ph == "middlegame" else endgame_phase
            bucket.append({"move": ply_data.get("move"), "swing": ply_data.get("delta", 0), "precision": prec})

        Logger.debug_log(f"Reprise de l'analyse de {game.get('url')} au coup {len(details) + 1}", "INFO")

    cached_opening = existing_game.get("opening", "Ouverture Inconnue") if existing_game else "Ouverture Inconnue"
    
    # Utilisation de la nouvelle détection intelligente
    needs_recalc = ChessUtils.is_raw_opening(cached_opening)
    
    best_opening_name = cached_opening

    # Si le nom est "brut" ou "inconnu", on relance la détection
    if needs_recalc:
        board_for_opening = game_obj.board()
        found_name = "Ouverture Inconnue"
        
        for m in moves[:20]:
            try:
                board_for_opening.push(m)
                op_name = ChessUtils.get_opening_name(board_for_opening)
                if op_name != "Ouverture Inconnue" and not ChessUtils.is_raw_opening(op_name):
                    found_name = op_name
            except Exception:
                continue
        
        best_opening_name = found_name if found_name != "Ouverture Inconnue" else cached_opening

    max_deep_moves = len(moves) if deep_analysis else 0
    result_data = {
        "id": game.get("url"),
        "is_complete": False,
        "date": datetime.fromtimestamp(game.get("end_time", 0)).strftime("%Y-%m-%d %H:%M") if game.get("end_time") else None,
        "end_time": game.get("end_time"),
        "result": result_text,
        "time_class": game.get("time_class", "inconnu"),
        "opponent_type": ChessUtils.classify_opponent_type(black_name if white_name == username else white_name),
        "white": {"username": white_name, "elo": game.get("white", {}).get("rating")},
        "black": {"username": black_name, "elo": game.get("black", {}).get("rating")},
        "opening": best_opening_name,
        "deep_analysis": deep_analysis,
        "analysis": {
            "summary": {"opening": {}, "middlegame": {}, "endgame": {}}, 
            "details": details, "blunders": blunders, "good_moves": good_moves,
            "opening_blunders": opening_blunders_data,
            "est_elo_white": est_elo_white,
            "est_elo_black": est_elo_black
        }
    }

    for idx, move in enumerate(moves, start=1):
        move_raw_en = san_moves[idx - 1]
        if idx <= len(details):
            board_before.push(move)
            continue

        swing, precision, pv_san = 0, -9999, ""
        
        if engine:
            try:
                eval_before, eval_after, move_obj = analyzer.analyze_move(board_before, move_raw_en)
                _, best_eval, best_uci = analyzer.get_best_move_with_eval(board_before.copy())
                
                if eval_before and eval_after and move_obj:
                    board_after = board_before.copy()
                    board_after.push(move_obj)
                    
                    pm = 1 if board_before.turn == chess.WHITE else -1
                    val_before = ChessUtils.get_eval_value(eval_before, board_before)
                    val_after = ChessUtils.get_eval_value(eval_after, board_after)
                    val_best = ChessUtils.get_eval_value(best_eval, board_before) if best_eval else val_before
                    
                    swing = (val_after - val_before) * pm
                    precision = min((val_after - val_best) * pm, swing)
                    if best_uci and move_obj.uci() == best_uci and swing > -50: 
                        precision = 0
                    
                    if idx <= 12 and swing <= -250:
                        sim_board = board_before.copy()
                        pv_list = []
                        engine.set_fen_position(sim_board.fen())
                        for _ in range(4):
                            m_best = engine.get_best_move()
                            if not m_best: break
                            m_sim = sim_board.parse_uci(m_best)
                            pv_list.append(sim_board.san(m_sim))
                            sim_board.push(m_sim)
                            engine.set_fen_position(sim_board.fen())
                        pv_san = " ".join(pv_list)
                        engine.set_fen_position(board_before.fen()) 
                        
            except Exception as e: 
                Logger.debug_log(f"Erreur d'analyse (ply {idx}) pour le coup {move_raw_en} : {str(e)}", "ERROR")

        if idx <= max_deep_moves:
            # Le cache StockfishAnalyzer optimise les doubles appels générés ici
            llm_comment, move_label = AIAnalyzer.generate_move_comment(
                move_raw_en, move_raw_en, board_before, is_trap=False, future_moves=san_moves[idx:]
            )
        else:
            board_test = board_before.copy()
            board_test.push(move)
            suffix = ChessUtils.infer_move_suffix(is_check=board_test.is_check(), is_checkmate=board_test.is_checkmate(), delta=swing)
            san_fr = ChessUtils.convert_english_to_french_notation(move_raw_en)
            move_label = f"{san_fr}{suffix}" if suffix else san_fr
            llm_comment = ""

        # On capture les informations de la gaffe pour le rapport détaillé
        if idx <= 12 and swing <= -250 and pv_san:
            opening_blunders_data.append({
                "move_number": (idx + 1) // 2,
                "color": "white" if idx % 2 != 0 else "black",
                "played_move": move_raw_en,
                "played_uci": move.uci(),
                "best_uci": best_uci,
                "stockfish_pv": pv_san,
                "fen": board_before.fen()
            })

        if swing <= -300: blunders += 1
        elif precision >= -30 and swing > -100: good_moves += 1

        phase = "opening" if idx <= 12 else "middlegame" if idx <= 30 else "endgame"
        {"opening": opening_phase, "middlegame": middlegame_phase, "endgame": endgame_phase}[phase].append({
            "move": move_label, "swing": swing, "precision": precision
        })

        # On vérifie la capture AVANT de pousser le coup
        is_capture = board_before.is_capture(move)
        board_before.push(move)
        
        details.append({
            "ply": idx, "move_number": (idx + 1) // 2, "color": "white" if idx % 2 != 0 else "black",
            "move": move_label, "raw_san": move_raw_en, "comment": llm_comment, "fen": board_before.fen(),
            "delta": round(swing, 2), "precision": round(precision, 2), "phase": phase,
            "uci": move.uci(),
            "is_capture": is_capture
        })

        result_data["analysis"]["summary"] = {
            ph: {"good_moves": sum(1 for i in lst if i.get("precision", -9999) >= -30 and i.get("swing", -9999) > -100), 
                 "blunders": sum(1 for i in lst if i.get("swing", 0) <= -300)}
            for ph, lst in [("opening", opening_phase), ("middlegame", middlegame_phase), ("endgame", endgame_phase)]
        }
        
        result_data["analysis"]["blunders"] = blunders
        result_data["analysis"]["good_moves"] = good_moves
        result_data["analysis"]["est_elo_white"], result_data["analysis"]["est_elo_black"] = ChessUtils.calculate_elo_from_details(details)
        
        if progress_callback: progress_callback(result_data)

    result_data["is_complete"] = True
    if progress_callback: progress_callback(result_data)

    return result_data

# =====================================================================
# RENDU PDF
# =====================================================================

def render_game_analysis_table(game, normal_style, bold_style):
    elements = []
    w_est, b_est = game["analysis"].get("est_elo_white", "N/A"), game["analysis"].get("est_elo_black", "N/A")
    elements.extend([Paragraph(f"<i>Performance estimée : Blanc {w_est} | Noir {b_est}</i>", normal_style), Spacer(1, 5)])
    
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
        
        fleches_blanches, fleches_noires, fleches_rouges = [], [], []
        
        # Attribution des flèches selon la couleur et si c'est une prise
        if row.get("white_uci"):
            if row.get("white_is_capture"): fleches_rouges.append(row["white_uci"])
            else: fleches_blanches.append(row["white_uci"])
                
        if row.get("black_uci"):
            if row.get("black_is_capture"): fleches_rouges.append(row["black_uci"])
            else: fleches_noires.append(row["black_uci"])

        diag = ChessboardFlowable(
            fen, size=110, 
            fleches_blanches=fleches_blanches, 
            fleches_noires=fleches_noires, 
            fleches_rouges=fleches_rouges, 
            orientation=orientation
        ) if fen else ""
        
        parts = []
        if row.get("white_comment"): parts.append(f"<b>Blancs :</b> {row['white_comment']}")
        if row.get("black_comment"): parts.append(f"<b>Noirs :</b> {row['black_comment']}")
        
        table_data.append([
            diag, Paragraph(str(row["move_number"]), bold_style), Paragraph(row.get("white", ""), bold_style),
            Paragraph(row.get("black", ""), bold_style), Paragraph("<br/>".join(parts) if parts else "<i>Développement validé.</i>", normal_style)
        ])
        
    t = Table(table_data, colWidths=[120, 30, 50, 50, 260], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), Config.COLOR_PRIMARY), ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('VALIGN', (0,0), (-1,-1), 'TOP'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, Config.COLOR_BG_LIGHT]),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, Config.COLOR_BORDER), ('PADDING', (0,0), (-1,-1), 6)
    ]))
    elements.append(t)
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

    games = list(state.get("games", {}).values())
    if opponent_name:
        op_lower = opponent_name.lower()
        games = [g for g in games if op_lower in (g["white"]["username"].lower(), g["black"]["username"].lower())]

    games = sorted([g for g in games if g.get("is_complete", True)], key=lambda x: x.get("end_time", 0))

    if not games:
        elements.append(Paragraph("Aucune partie complétée trouvée pour ces critères.", normal_style))
        doc.build(elements)
        return

    player_lower = player_name.lower()
    wins = sum(1 for g in games if (g["result"] == "1-0" and g["white"]["username"].lower() == player_lower) or (g["result"] == "0-1" and g["black"]["username"].lower() == player_lower))
    losses = sum(1 for g in games if (g["result"] == "0-1" and g["white"]["username"].lower() == player_lower) or (g["result"] == "1-0" and g["black"]["username"].lower() == player_lower))
    
    elements.extend([
        Paragraph("1. Vue d'ensemble", section_style),
        Paragraph(f"Analyse basée sur <b>{len(games)} parties</b>. Bilan pour {player_name} : <font color='green'>{wins} V</font> / <font color='gray'>{len(games) - wins - losses} N</font> / <font color='red'>{losses} D</font>.", normal_style),
        Spacer(1, 15)
    ])

    player_elos, opponent_elos = [], []
    for g in games:
        is_white = g["white"]["username"].lower() == player_lower
        player_elos.append(g["analysis"].get("est_elo_white" if is_white else "est_elo_black", 1200))
        opponent_elos.append(g["analysis"].get("est_elo_black" if is_white else "est_elo_white", 1200))
        
    if len(player_elos) > 1:
        elements.extend([
            Paragraph("Progression des Performances Estimées", subsection_style),
            EloProgressionChart(player_elos, opponent_elos, labels=[f"P {i+1}" for i in range(len(games))]),
            Spacer(1, 5),
            Paragraph("<i><font color='#0284c7'>Bleu : Niveau de performance (Joueur)</font> | <font color='#f97316'>Orange : Niveau de performance (Adversaire)</font></i>", normal_style),
            Spacer(1, 15)
        ])

    elements.append(Paragraph("2. Forces et Faiblesses (Ouvertures)", section_style))
    categorized_games = defaultdict(list)
    for g in games: categorized_games[f"{g['time_class'].capitalize()} ({g['opponent_type'].capitalize()})"].append(g)

    for cat in sorted(categorized_games.keys(), key=lambda x: (1 if "Robot" in x else 0, x)):
        cat_games = categorized_games[cat]
        good = sum(g["analysis"]["summary"]["opening"].get("good_moves", 0) for g in cat_games)
        blunders = sum(g["analysis"]["summary"]["opening"].get("blunders", 0) for g in cat_games)
        elements.extend([
            Paragraph(f"Format : {cat} ({len(cat_games)} parties)", subsection_style),
            Paragraph(f"Bons coups théoriques : <b>{good}</b> | Gaffes d'ouverture : <b>{blunders}</b>", normal_style),
            Spacer(1, 10)
        ])

    elements.extend([PageBreak(), Paragraph("3. Focus Théorique des Ouvertures (via Stockfish)", section_style)])
    
    openings_blunders = defaultdict(list)
    for g in games:
        for blunder in g.get("analysis", {}).get("opening_blunders", []):
            openings_blunders[g.get("opening", "Inconnue")].append(blunder)

    top_weak = sorted(openings_blunders.items(), key=lambda x: len(x[1]), reverse=True)[:3]
    
    if not top_weak:
        elements.append(Paragraph("Aucune erreur critique d'ouverture n'a été détectée dans cet échantillon.", normal_style))
    else:
        for op_name, blunders_list in [item for item in top_weak if item[0] != "Inconnue"]:
            elements.append(Paragraph(f"Ouverture : {op_name} ({len(blunders_list)} erreurs récentes)", subsection_style))
            
            blunder_data = [[
                Paragraph("<b>Diag</b>", normal_style), 
                Paragraph("<b>N°</b>", normal_style),
                Paragraph("<b>Gaffe (Orange)</b>", normal_style),
                Paragraph("<b>Meilleure (Bleue)</b>", normal_style),
                Paragraph("<b>Analyse de l'IA</b>", normal_style)
            ]]
            
            # On génère une ligne de tableau pour chaque gaffe liée à cette ouverture
            for sample in blunders_list:
                fen = sample.get("fen")
                played_uci = sample.get("played_uci")
                best_uci = sample.get("best_uci")
                
                # Formatage du numéro de coup (ex: 4B ou 4N)
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
                
                summary = AIAnalyzer.get_stockfish_theory_summary(op_name, sample['played_move'], sample['stockfish_pv'])
                best_reply_san = sample['stockfish_pv'].split()[0] if sample.get('stockfish_pv') else "N/A"
                
                blunder_data.append([
                    diag,
                    Paragraph(move_num, normal_style),
                    Paragraph(sample.get('played_move', ''), normal_style),
                    Paragraph(best_reply_san, normal_style),
                    Paragraph(summary, normal_style)
                ])
                
            t_blunder = Table(blunder_data, colWidths=[120, 30, 60, 60, 230], repeatRows=1)
            t_blunder.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), Config.COLOR_PRIMARY), ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('VALIGN', (0,0), (-1,-1), 'TOP'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, Config.COLOR_BG_LIGHT]),
                ('LINEBELOW', (0,0), (-1,-1), 0.5, Config.COLOR_BORDER), ('PADDING', (0,0), (-1,-1), 6)
            ]))
            
            elements.extend([t_blunder, Spacer(1, 15)])

    for idx, g in enumerate([g for g in games if g.get("deep_analysis")]):
        if idx > 0: elements.append(Spacer(1, 20))
        g["player_focus"] = player_name
        title = f"Partie {idx+1} : {g['white']['username']} ({g['analysis'].get('est_elo_white', 'N/A')} ELO) vs {g['black']['username']} ({g['analysis'].get('est_elo_black', 'N/A')} ELO)"
        
        elements.append(KeepTogether([
            Paragraph(title, subsection_style),
            Paragraph(f"Ouverture : {g.get('opening')} | Résultat : {g['result']} ({g['date']})", normal_style),
            Spacer(1, 10)
        ] + render_game_analysis_table(g, normal_style, bold_style)))

    footer = lambda c, d: PDFUtils.ajouter_pied_page(c, d, "Rapport Analytique Complet - Chess Docs")
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
    parser.add_argument("--game-id", type=str, default=None, help="ID ou URL spécifique de la partie à forcer dans l'analyse")
    # --------------------------------------
    
    args = parser.parse_args()

    Logger.set_debug_enabled(bool(args.verbose), level=max(int(args.verbose or 0), 1))
    
    ollama_mgr = OllamaManager()
    ollama_mgr.start()
    
    try:
        base_dir = Path(__file__).resolve().parent.parent
        state_path = ChessUtils.build_player_state_path(str(base_dir), args.player)
        
        out_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', f"{args.player}_vs_{args.opponent}" if args.opponent else args.player).strip('_')
        output_path = base_dir / f"{out_name}_report_avance.pdf"
        
        state = CacheManager.load_state(str(state_path))
        if (state.get("player") or "").lower() != args.player.lower():
            state = {"player": args.player, "games": {}}
        
        for game in state.get("games", {}).values():
            if "analysis" in game and "details" in game["analysis"]:
                game["analysis"]["est_elo_white"], game["analysis"]["est_elo_black"] = ChessUtils.calculate_elo_from_details(game["analysis"]["details"])

        existing_games = state.get("games", {})
        
        # --- NOUVELLE LOGIQUE DE FILTRAGE ET DE LIMITE ---
        games_to_process = []
        for g in ChessUtils.fetch_player_games(args.player, months=args.months):
            game_id = g.get("url")
            if not game_id: continue
            
            # Filtre 1 : ID de la partie si fourni (vérifie si l'ID passé est dans l'URL)
            if args.game_id and args.game_id not in game_id:
                continue
            
            # Filtre 2 : Adversaire
            if args.opponent and args.opponent.lower() not in (g.get("white", {}).get("username", "").lower(), g.get("black", {}).get("username", "").lower()):
                continue
                
            existing_g = existing_games.get(game_id)
            needs_full_analysis = ChessUtils.is_game_incomplete(existing_g, require_deep=True)
            needs_opening_fix = existing_g and ChessUtils.is_raw_opening(existing_g.get("opening", ""))
            
            # On stocke uniquement les parties qui requièrent un traitement
            if needs_full_analysis or needs_opening_fix:
                games_to_process.append((g, game_id, existing_g, needs_full_analysis))
        
        # Application de la limite du nombre de parties (uniquement si > 0)
        if args.max_games > 0:
            games_to_process = games_to_process[:args.max_games]
            
        # Lancement de l'analyse sur la liste restreinte
        for g, game_id, existing_g, needs_full_analysis in games_to_process:
            def save_progress(partial_parsed):
                existing_games[game_id] = partial_parsed
                state["games"] = existing_games
                CacheManager.save_state(str(state_path), state)
            
            parse_game_record(g, args.player, deep_analysis=needs_full_analysis, progress_callback=save_progress, existing_game=existing_g)
        # -------------------------------------------------
        
        state.update({"player": args.player, "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        CacheManager.save_state(str(state_path), state)
        build_pdf(str(output_path), state, args.player, args.opponent)

    finally:
        ollama_mgr.stop()
        StockfishAnalyzer().clear_cache()

if __name__ == "__main__":
    main()
