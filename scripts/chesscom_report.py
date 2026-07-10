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
import chess.engine
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
from classes.pdf_components import ChessboardFlowable

# =====================================================================
# COMPOSANTS GRAPHIQUES : GRAPHIQUE ELO
# =====================================================================

class EloProgressionChart(Flowable):
    def __init__(self, values_player, values_opponent, labels=None, width=460, height=200):
        super().__init__()
        self.vp = values_player or []
        self.vo = values_opponent or []
        self.labels = labels or []
        self.width = width
        self.height = height

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        if not self.vp or len(self.vp) < 2: return
        x0, y0, x1, y1 = 40, 25, self.width - 20, self.height - 15
        
        # Fond du graphique
        self.canv.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.canv.setLineWidth(0.6)
        self.canv.rect(x0, y0, x1 - x0, y1 - y0)
        
        all_vals = self.vp + self.vo
        min_value, max_value = min(all_vals), max(all_vals)
        
        # Padding vertical
        min_value = max(0, min_value - 150)
        max_value = max_value + 150
        span = max_value - min_value or 1

        self.canv.setFont("Helvetica", 8)
        self.canv.setFillColor(Config.COLOR_TEXT)
        num_steps = 5
        
        # Lignes horizontales (Repères ELO)
        for i in range(num_steps + 1):
            y_pos = y0 + (i / num_steps) * (y1 - y0)
            val = min_value + (i / num_steps) * span
            self.canv.drawRightString(x0 - 5, y_pos - 3, str(int(val)))
            if 0 < i < num_steps:
                self.canv.setStrokeColor(colors.HexColor("#e2e8f0"))
                self.canv.setDash(2, 2)
                self.canv.line(x0, y_pos, x1, y_pos)
                self.canv.setDash()

        # Fonction de tracé d'une ligne de données
        def draw_line(values, color_hex):
            points = []
            for idx, value in enumerate(values):
                x = x0 + (idx / max(len(values) - 1, 1)) * (x1 - x0)
                y = y0 + ((value - min_value) / span) * (y1 - y0) 
                points.append((x, y))

            segments = [(points[i][0], points[i][1], points[i+1][0], points[i+1][1]) for i in range(len(points) - 1)]
            self.canv.setStrokeColor(colors.HexColor(color_hex))
            self.canv.setLineWidth(1.8)
            self.canv.lines(segments)
            
            self.canv.setFillColor(colors.HexColor(color_hex))
            for x, y in points: self.canv.circle(x, y, 2.5, stroke=0, fill=1)

        # Tracé : Orange (Adversaire) en premier, puis Bleu (Joueur)
        draw_line(self.vo, "#f97316") # Orange
        draw_line(self.vp, "#0284c7") # Bleu

        # Labels (Noms/Numéros de parties en abscisse)
        if self.labels:
            self.canv.setFont("Helvetica", 8)
            self.canv.setFillColor(Config.COLOR_TEXT)
            step = max(1, len(self.labels) // 6)
            for idx, label in enumerate(self.labels):
                if idx % step != 0 and idx != len(self.labels) - 1: continue
                x = x0 + (idx / max(len(self.vp) - 1, 1)) * (x1 - x0)
                self.canv.drawString(x - 10, y0 - 12, str(label)[:10])

# =====================================================================
# UTILITAIRES ET DATA MANAGEMENT
# =====================================================================

def classify_opponent_type(username):
    if not username: return "humain"
    lowered = username.lower()
    if any(token in lowered for token in ["bot", "engine", "stockfish", "computer", "ai", "chess.com"]):
        return "robot"
    return "humain"

def infer_move_suffix(is_check=False, is_checkmate=False, delta=None):
    if is_checkmate: return "#"
    if is_check: return "+"
    if delta is None: return ""
    if delta <= -400: return "??"
    if delta <= -120: return "?"
    if delta >= 400: return "!!"
    if delta >= 160: return "!"
    return ""

def build_player_state_path(base_dir, player_name):
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", player_name).strip("_") or "player"
    return os.path.join(base_dir, "json", f"player_{safe_name}.json")

def resolve_project_base_dir():
    return Path(__file__).resolve().parent.parent

def load_state(path):
    if not path or not os.path.exists(path): return {"player": None, "games": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data.get("games"), list):
                data["games"] = {g["id"]: g for g in data["games"] if "id" in g}
            elif not isinstance(data.get("games"), dict):
                data["games"] = {}
            return data
    except Exception: return {"player": None, "games": {}}

def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, separators=(",", ":"), indent=2)

def is_game_incomplete(game, require_deep):
    if not game: return True
    if not game.get("is_complete", False): return True
    if not game.get("result") or game.get("result") == "*": return True
    if not game.get("date") or not game.get("end_time"): return True
    if not game.get("analysis") or not game.get("analysis").get("summary"): return True
    
    if require_deep:
        if not game.get("deep_analysis"): return True
        analysis = game.get("analysis", {})
        if not analysis.get("details") or len(analysis.get("details")) == 0: return True
        
    return False

# =====================================================================
# FETCH ET PARSING DES PARTIES
# =====================================================================

def fetch_player_games(username, months=6):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChessDocs/1.0"}
    Logger.debug_log(f"Récupération des archives Chess.com pour {username} (mois={months})", "INFO")

    def request_with_retry(url, retries=3):
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=25, headers=headers)
                if response.status_code in {403, 429} and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                if attempt < retries - 1: time.sleep(2 ** attempt)
                else: raise exc

    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    try:
        response = request_with_retry(archives_url)
        archives = response.json().get("archives", [])
    except Exception as e:
        Logger.debug_log(f"Erreur API archives: {e}", "ERROR")
        return []

    recent_archives = archives[-months:] if months and months > 0 else archives
    games = []
    for archive_url in recent_archives:
        try:
            games.extend(request_with_retry(archive_url).json().get("games", []))
        except Exception: pass
    return games

def parse_game_record(game, username, deep_analysis=False, progress_callback=None, existing_game=None):
    game_url = game.get("url")
    pgn_text = game.get("pgn") or ""
    if not pgn_text: return None

    try: game_obj = chess.pgn.read_game(StringIO(pgn_text))
    except Exception: return None
    if not game_obj: return None

    white_name = game.get("white", {}).get("username", "")
    black_name = game.get("black", {}).get("username", "")
    
    result_text = game_obj.headers.get("Result", "*")
    if result_text == "*":
        w_res = game.get("white", {}).get("result", "")
        b_res = game.get("black", {}).get("result", "")
        if w_res == "win": result_text = "1-0"
        elif b_res == "win": result_text = "0-1"
        elif w_res in ["agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"]: 
            result_text = "1/2-1/2"

    board_before = game_obj.board()
    moves = []
    san_moves = []

    for move in game_obj.mainline_moves():
        san_moves.append(board_before.san(move))
        moves.append(move)
        board_before.push(move)

    board_before = game_obj.board()
    
    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine(depth=ChessUtils.resolve_stockfish_depth(18))

    details = []
    blunders, good_moves = 0, 0
    opening_phase, middlegame_phase, endgame_phase = [], [], []
    opening_blunders_data = []
    
    # Suivi des Centipawns (CPL) pour calcul d'ELO
    white_cpl, black_cpl = 0, 0
    white_m_count, black_m_count = 0, 0

    if existing_game and "analysis" in existing_game:
        old_analysis = existing_game["analysis"]
        details = old_analysis.get("details", [])
        blunders = old_analysis.get("blunders", 0)
        good_moves = old_analysis.get("good_moves", 0)
        opening_blunders_data = old_analysis.get("opening_blunders", [])
        
        for ply_data in details:
            ph = ply_data.get("phase", "opening")
            prec = ply_data.get("precision", -9999)
            bucket = opening_phase if ph == "opening" else middlegame_phase if ph == "middlegame" else endgame_phase
            bucket.append({"move": ply_data.get("move"), "swing": ply_data.get("delta", 0), "precision": prec})
            
            # Reconstruction du tracker CPL
            if prec != -9999:
                loss = min(1000, max(0, -prec))  # Borné à 10 pions
                if ply_data.get("color") == "white":
                    white_cpl += loss
                    white_m_count += 1
                else:
                    black_cpl += loss
                    black_m_count += 1

        Logger.debug_log(f"Reprise de l'analyse de {game_url} à partir du coup {len(details) + 1}", "INFO")

    max_deep_moves = len(moves) if deep_analysis else 0

    result_data = {
        "id": game_url,
        "is_complete": False,
        "date": datetime.fromtimestamp(game.get("end_time", 0)).strftime("%Y-%m-%d %H:%M") if game.get("end_time") else None,
        "end_time": game.get("end_time"),
        "result": result_text,
        "time_class": game.get("time_class", "inconnu"),
        "opponent_type": classify_opponent_type(black_name if white_name == username else white_name),
        "white": {"username": white_name, "elo": game.get("white", {}).get("rating")},
        "black": {"username": black_name, "elo": game.get("black", {}).get("rating")},
        "opening": game_obj.headers.get("Opening", game_obj.headers.get("ECO", "Inconnue")),
        "deep_analysis": deep_analysis,
        "analysis": {
            "summary": {"opening": {}, "middlegame": {}, "endgame": {}}, 
            "details": details, 
            "blunders": blunders, 
            "good_moves": good_moves,
            "opening_blunders": opening_blunders_data
        }
    }

    for idx, move in enumerate(moves, start=1):
        move_raw_en = san_moves[idx - 1]
        
        # SI DÉJÀ ANALYSÉ : avance le jeu et ignore l'évaluation
        if idx <= len(details):
            board_before.push(move)
            continue

        swing = 0
        precision = -9999
        pv_san = ""
        
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
                    val_best = ChessUtils.get_eval_value(best_eval, board_after) if best_eval else val_before
                    
                    eval_player_before = val_before * pm
                    eval_player_after = val_after * pm
                    eval_player_best = val_best * pm
                    
                    swing = eval_player_after - eval_player_before
                    precision = eval_player_after - eval_player_best
                    if best_uci and move_obj.uci() == best_uci: 
                        precision = 0

                    # Ajout dynamique au track CPL pour calcul de l'ELO estimé
                    loss = min(1000, max(0, -precision))
                    if idx % 2 != 0:
                        white_cpl += loss; white_m_count += 1
                    else:
                        black_cpl += loss; black_m_count += 1
                    
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

        future_moves = san_moves[idx:]
        llm_comment = ""
        
        if idx <= max_deep_moves:
            llm_comment, move_label = AIAnalyzer.generate_move_comment(
                move_raw_en, move_raw_en, board_before, is_trap=False, future_moves=future_moves
            )
        else:
            board_test_check = board_before.copy()
            board_test_check.push(move)
            suffix = infer_move_suffix(is_check=board_test_check.is_check(), is_checkmate=board_test_check.is_checkmate(), delta=swing)
            san_fr = ChessUtils.convert_english_to_french_notation(move_raw_en)
            move_label = f"{san_fr}{suffix}" if suffix else san_fr

        if idx <= 12 and swing <= -250 and pv_san:
            opening_blunders_data.append({
                "played_move": move_raw_en,
                "stockfish_pv": pv_san,
                "fen": board_before.fen()
            })

        if swing <= -300: blunders += 1
        elif precision >= -30 and swing > -100: good_moves += 1

        phase = "opening" if idx <= 12 else "middlegame" if idx <= 30 else "endgame"
        phase_bucket = {"opening": opening_phase, "middlegame": middlegame_phase, "endgame": endgame_phase}[phase]
        phase_bucket.append({"move": move_label, "swing": swing, "precision": precision})

        board_before.push(move)
        
        details.append({
            "ply": idx, "move_number": (idx + 1) // 2, "color": "white" if idx % 2 != 0 else "black",
            "move": move_label, "raw_san": move_raw_en, "comment": llm_comment, "fen": board_before.fen(),
            "delta": round(swing, 2), "precision": round(precision, 2), "phase": phase,
        })

        summary = {
            "opening": {
                "good_moves": sum(1 for i in opening_phase if i.get("precision", -9999) >= -30 and i.get("swing", -9999) > -100), 
                "blunders": sum(1 for i in opening_phase if i.get("swing", 0) <= -300)
            },
            "middlegame": {
                "good_moves": sum(1 for i in middlegame_phase if i.get("precision", -9999) >= -30 and i.get("swing", -9999) > -100), 
                "blunders": sum(1 for i in middlegame_phase if i.get("swing", 0) <= -300)
            },
            "endgame": {
                "good_moves": sum(1 for i in endgame_phase if i.get("precision", -9999) >= -30 and i.get("swing", -9999) > -100), 
                "blunders": sum(1 for i in endgame_phase if i.get("swing", 0) <= -300)
            }
        }
        
        # Calcul de l'ELO estimé en temps réel
        acpl_w = (white_cpl / white_m_count) if white_m_count > 0 else 0
        acpl_b = (black_cpl / black_m_count) if black_m_count > 0 else 0
        
        # Nouvelle formule : 3000 - (ACPL * 20) avec un facteur de lissage
        est_elo_w = max(100, min(3200, int(3000 - (acpl_w * 20))))
        est_elo_b = max(100, min(3200, int(3000 - (acpl_b * 20))))
        
        result_data["analysis"]["summary"] = summary
        result_data["analysis"]["est_elo_white"] = est_elo_w
        result_data["analysis"]["est_elo_black"] = est_elo_b
        
        result_data["analysis"]["summary"] = summary
        result_data["analysis"]["blunders"] = blunders
        result_data["analysis"]["good_moves"] = good_moves
        result_data["analysis"]["est_elo_white"] = est_elo_w
        result_data["analysis"]["est_elo_black"] = est_elo_b
        
        if progress_callback:
            progress_callback(result_data)

    result_data["is_complete"] = True
    if progress_callback:
        progress_callback(result_data)

    return result_data

# =====================================================================
# RENDU PDF
# =====================================================================

def ajouter_pied_page_rapport(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(Config.COLOR_TEXT)
    canvas.drawString(36, 20, "Rapport Analytique Complet - Chess Docs")
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()

def render_game_analysis_table(game, normal_style, bold_style):
    elements = []
    details = game.get("analysis", {}).get("details", [])

    # Ajout d'une ligne d'en-tête de scores estimés avant la table
    w_est = game["analysis"].get("est_elo_white", "N/A")
    b_est = game["analysis"].get("est_elo_black", "N/A")
    elements.append(Paragraph(f"<i>Performance estimée : Blanc {w_est} | Noir {b_est}</i>", normal_style))
    elements.append(Spacer(1, 5))
    
    table_data = [[
        Paragraph("<b>Diag</b>", normal_style),
        Paragraph("<b>N°</b>", normal_style),
        Paragraph("<b>Blanc</b>", normal_style),
        Paragraph("<b>Noir</b>", normal_style),
        Paragraph("<b>Analyse (Stockfish)</b>", normal_style)
    ]]
    
    rows = []
    current_row = None
    for ply in details:
        move_num = ply["move_number"]
        if ply["color"] == "white":
            current_row = {
                "move_number": move_num, "white": ply["move"], "white_comment": ply["comment"], "white_fen": ply["fen"],
                "black": "", "black_comment": "", "black_fen": None
            }
            rows.append(current_row)
        else:
            if not current_row or current_row["move_number"] != move_num:
                current_row = {"move_number": move_num, "white": "", "white_comment": "", "white_fen": None, "black": ply["move"], "black_comment": ply["comment"], "black_fen": ply["fen"]}
                rows.append(current_row)
            else:
                current_row.update({"black": ply["move"], "black_comment": ply["comment"], "black_fen": ply["fen"]})

    orientation = chess.WHITE if game["white"]["username"].lower() == game.get("player_focus", "").lower() else chess.BLACK

    for row in rows:
        fen = row.get("black_fen") or row.get("white_fen")
        diag = ChessboardFlowable(fen, size=110, orientation=orientation) if fen else ""
        
        parts = []
        if row.get("white_comment"): parts.append(f"<b>Blancs :</b> {row['white_comment']}")
        if row.get("black_comment"): parts.append(f"<b>Noirs :</b> {row['black_comment']}")
        comment_text = "<br/>".join(parts) if parts else "<i>Développement validé.</i>"

        table_data.append([
            diag,
            Paragraph(str(row["move_number"]), bold_style),
            Paragraph(row.get("white", ""), bold_style),
            Paragraph(row.get("black", ""), bold_style),
            Paragraph(comment_text, normal_style)
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

    elements = []
    title_text = f"Rapport Stratégique : {player_name}"
    if opponent_name:
        title_text += f" vs {opponent_name}"
        
    elements.extend([
        Paragraph(title_text, title_style),
        Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", subtitle_style),
    ])

    games = list(state.get("games", {}).values())
    if opponent_name:
        op_lower = opponent_name.lower()
        games = [g for g in games if g["white"]["username"].lower() == op_lower or g["black"]["username"].lower() == op_lower]

    # Trie chronologiquement
    games = sorted([g for g in games if g.get("is_complete", True)], key=lambda x: x.get("end_time", 0))

    if not games:
        elements.append(Paragraph("Aucune partie complétée trouvée pour ces critères.", normal_style))
        doc.build(elements)
        return

    wins = sum(1 for g in games if (g["result"] == "1-0" and g["white"]["username"].lower() == player_name.lower()) or (g["result"] == "0-1" and g["black"]["username"].lower() == player_name.lower()))
    losses = sum(1 for g in games if (g["result"] == "0-1" and g["white"]["username"].lower() == player_name.lower()) or (g["result"] == "1-0" and g["black"]["username"].lower() == player_name.lower()))
    draws = len(games) - wins - losses

    elements.append(Paragraph("1. Vue d'ensemble", section_style))
    summary_text = f"Analyse basée sur <b>{len(games)} parties</b>. Bilan pour {player_name} : <font color='green'>{wins} V</font> / <font color='gray'>{draws} N</font> / <font color='red'>{losses} D</font>."
    elements.extend([Paragraph(summary_text, normal_style), Spacer(1, 15)])

    # GRAPHIQUE ELO
    player_elos, opponent_elos, graph_labels = [], [], []
    for idx, g in enumerate(games):
        w_name = g["white"]["username"].lower()
        if w_name == player_name.lower():
            player_elos.append(g["analysis"].get("est_elo_white", 1200))
            opponent_elos.append(g["analysis"].get("est_elo_black", 1200))
        else:
            player_elos.append(g["analysis"].get("est_elo_black", 1200))
            opponent_elos.append(g["analysis"].get("est_elo_white", 1200))
        graph_labels.append(f"P {idx+1}")
        
    if len(player_elos) > 1:
        elements.append(Paragraph("Progression des Performances Estimées", subsection_style))
        elements.append(EloProgressionChart(player_elos, opponent_elos, labels=graph_labels))
        elements.append(Spacer(1, 5))
        elements.append(Paragraph("<i><font color='#0284c7'>Bleu : Niveau de performance (Joueur)</font> | <font color='#f97316'>Orange : Niveau de performance (Adversaire)</font></i>", normal_style))
        elements.append(Spacer(1, 15))

    elements.append(Paragraph("2. Forces et Faiblesses (Ouvertures)", section_style))
    categorized_games = {}
    for g in games:
        cat = f"{g['time_class'].capitalize()} ({g['opponent_type'].capitalize()})"
        categorized_games.setdefault(cat, []).append(g)

    sorted_categories = sorted(categorized_games.keys(), key=lambda x: (1 if "Robot" in x else 0, x))

    for cat in sorted_categories:
        cat_games = categorized_games[cat]
        good = sum(g["analysis"]["summary"]["opening"].get("good_moves", 0) for g in cat_games)
        blunders = sum(g["analysis"]["summary"]["opening"].get("blunders", 0) for g in cat_games)
        
        elements.append(Paragraph(f"Format : {cat} ({len(cat_games)} parties)", subsection_style))
        elements.append(Paragraph(f"Bons coups théoriques : <b>{good}</b> | Gaffes d'ouverture : <b>{blunders}</b>", normal_style))
        elements.append(Spacer(1, 10))

    elements.append(PageBreak())
    elements.append(Paragraph("3. Focus Théorique des Ouvertures (via Stockfish)", section_style))
    
    openings_blunders = defaultdict(list)
    for g in games:
        op = g.get("opening", "Inconnue")
        for blunder in g.get("analysis", {}).get("opening_blunders", []):
            openings_blunders[op].append(blunder)

    top_weak_openings = sorted(openings_blunders.items(), key=lambda x: len(x[1]), reverse=True)[:3]
    
    if not top_weak_openings:
        elements.append(Paragraph("Aucune erreur critique d'ouverture n'a été détectée dans cet échantillon.", normal_style))
    else:
        for op_name, blunders_list in top_weak_openings:
            if len(blunders_list) > 0 and op_name != "Inconnue":
                sample_blunder = blunders_list[0] 
                elements.append(Paragraph(f"Ouverture : {op_name} ({len(blunders_list)} erreurs récentes)", subsection_style))
                
                theory_text = AIAnalyzer.get_stockfish_theory_summary(
                    op_name, 
                    sample_blunder["played_move"], 
                    sample_blunder["stockfish_pv"]
                )
                elements.append(Paragraph(f"<i>Analyse de l'ordinateur :</i><br/>{theory_text}", normal_style))
                elements.append(Spacer(1, 15))

    elements.append(PageBreak())
    elements.append(Paragraph("4. Analyses Détaillées des Parties", section_style))
    elements.append(Spacer(1, 15))

    deep_games = [g for g in games if g.get("deep_analysis")]
    for idx, g in enumerate(deep_games):
        if idx > 0: elements.append(Spacer(1, 20))
        g["player_focus"] = player_name
        
        w_name, b_name = g["white"]["username"], g["black"]["username"]
        w_elo = g["analysis"].get("est_elo_white", "N/A")
        b_elo = g["analysis"].get("est_elo_black", "N/A")
        title = f"Partie {idx+1} : {w_name} ({w_elo} ELO) vs {b_name} ({b_elo} ELO)"
        
        elements.append(KeepTogether([
            Paragraph(title, subsection_style),
            Paragraph(f"Ouverture : {g.get('opening')} | Résultat : {g['result']} ({g['date']})", normal_style),
            Spacer(1, 10)
        ] + render_game_analysis_table(g, normal_style, bold_style)))

    doc.build(elements, onFirstPage=ajouter_pied_page_rapport, onLaterPages=ajouter_pied_page_rapport)
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
    args = parser.parse_args()

    enabled, level = (True, max(int(args.verbose), 1)) if args.verbose else (False, 0)
    Logger.set_debug_enabled(enabled, level=level)
    
    ollama_mgr = OllamaManager()
    ollama_mgr.start()
    
    try:
        base_dir = resolve_project_base_dir()
        state_path = build_player_state_path(str(base_dir), args.player)
        
        out_name = f"{args.player}_vs_{args.opponent}" if args.opponent else args.player
        out_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', out_name).strip('_')
        output_path = base_dir / f"{out_name}_report_avance.pdf"
        
        state = load_state(str(state_path))
        if state.get("player") and state.get("player").lower() != args.player.lower():
            state = {"player": args.player, "games": {}}

        existing_games = state.get("games", {})
        fetched_games = fetch_player_games(args.player, months=args.months)
        
        for g in fetched_games:
            game_id = g.get("url")
            if not game_id: continue
            
            w_name = g.get("white", {}).get("username", "").lower()
            b_name = g.get("black", {}).get("username", "").lower()
            
            if args.opponent:
                op_lower = args.opponent.lower()
                if w_name != op_lower and b_name != op_lower:
                    continue
            
            do_deep = True
            existing_game = existing_games.get(game_id)
            
            if is_game_incomplete(existing_game, require_deep=do_deep):
                
                def save_progress(partial_parsed):
                    existing_games[game_id] = partial_parsed
                    state["games"] = existing_games
                    save_state(str(state_path), state)
                
                parse_game_record(
                    g, args.player, 
                    deep_analysis=do_deep, 
                    progress_callback=save_progress, 
                    existing_game=existing_game
                )
        
        state["player"] = args.player
        state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_state(str(state_path), state)
        
        build_pdf(str(output_path), state, args.player, args.opponent)

    finally:
        ollama_mgr.stop()

if __name__ == "__main__":
    main()
