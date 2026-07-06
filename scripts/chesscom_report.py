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

# Importations depuis la librairie partagée
from chess_lib import (
    COLOR_BG_LIGHT, COLOR_BORDER, COLOR_PRIMARY, COLOR_TEXT, COLOR_SECONDARY, COLOR_MINT,
    StockfishAnalyzer, debug_log, get_eval_value,
    resolve_stockfish_depth, set_debug_enabled, OllamaManager, ChessboardFlowable,
    get_stockfish_theory_summary, generate_move_comment, convert_english_to_french_notation
)

# =====================================================================
# COMPOSANTS GRAPHIQUES
# =====================================================================

class SimpleLineChart(Flowable):
    def __init__(self, values, labels=None, width=420, height=180):
        super().__init__()
        self.values = values or []
        self.labels = labels or []
        self.width = width
        self.height = height

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        if not self.values or len(self.values) < 2: return
        x0, y0, x1, y1 = 40, 25, self.width - 20, self.height - 15
        self.canv.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.canv.setLineWidth(0.6)
        self.canv.rect(x0, y0, x1 - x0, y1 - y0)
        min_value, max_value = min(self.values), max(self.values)
        span = max_value - min_value or 1

        self.canv.setFont("Helvetica", 8)
        self.canv.setFillColor(COLOR_TEXT)
        num_steps = 4
        for i in range(num_steps + 1):
            y_pos = y0 + (i / num_steps) * (y1 - y0)
            val = min_value + (i / num_steps) * span
            self.canv.drawRightString(x0 - 5, y_pos - 3, str(int(val)))
            if 0 < i < num_steps:
                self.canv.setStrokeColor(colors.HexColor("#e2e8f0"))
                self.canv.setDash(2, 2)
                self.canv.line(x0, y_pos, x1, y_pos)
                self.canv.setDash()

        points = []
        for idx, value in enumerate(self.values):
            x = x0 + (idx / max(len(self.values) - 1, 1)) * (x1 - x0)
            y = y0 + ((value - min_value) / span) * (y1 - y0) 
            points.append((x, y))

        segments = [(points[i][0], points[i][1], points[i+1][0], points[i+1][1]) for i in range(len(points) - 1)]
        self.canv.setStrokeColor(COLOR_SECONDARY)
        self.canv.setLineWidth(1.2)
        self.canv.lines(segments)
        
        self.canv.setFillColor(COLOR_PRIMARY)
        for x, y in points: self.canv.circle(x, y, 2.6, stroke=0, fill=1)

        if self.labels:
            self.canv.setFont("Helvetica", 8)
            self.canv.setFillColor(COLOR_TEXT)
            step = max(1, len(self.labels) // 4)
            for idx, label in enumerate(self.labels):
                if idx % step != 0 and idx != len(self.labels) - 1: continue
                x = x0 + (idx / max(len(self.values) - 1, 1)) * (x1 - x0)
                self.canv.drawString(x - 15, y0 - 12, str(label)[:10])

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

# =====================================================================
# FETCH ET PARSING DES PARTIES
# =====================================================================

def fetch_player_games(username, months=6):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChessDocs/1.0"}
    debug_log(f"Récupération des archives Chess.com pour {username} (mois={months})", "INFO")

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
        debug_log(f"Erreur API archives: {e}", "ERROR")
        return []

    recent_archives = archives[-months:] if months and months > 0 else archives
    games = []
    for archive_url in recent_archives:
        try:
            games.extend(request_with_retry(archive_url).json().get("games", []))
        except Exception: pass
    return games

def parse_game_record(game, username, deep_analysis=False):
    game_url = game.get("url")
    pgn_text = game.get("pgn") or ""
    if not pgn_text: return None

    try: game_obj = chess.pgn.read_game(StringIO(pgn_text))
    except Exception: return None
    if not game_obj: return None

    white_name = game.get("white", {}).get("username", "")
    black_name = game.get("black", {}).get("username", "")
    
    result = game.get("result") or "*"
    if result == "win" and white_name == username: result_text = "1-0"
    elif result == "win" and black_name == username: result_text = "0-1"
    else: result_text = "1/2-1/2" if result == "draw" else "*"

    board_before = game_obj.board()

    moves = []
    san_moves = []

    for move in game_obj.mainline_moves():
        san_moves.append(board_before.san(move))
        moves.append(move)
        board_before.push(move)

    # Revenir à la position initiale
    board_before = game_obj.board()
    
    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine(depth=resolve_stockfish_depth(14))

    details = []
    blunders, good_moves = 0, 0
    opening_phase, middlegame_phase, endgame_phase = [], [], []
    opening_blunders_data = []
    
    max_deep_moves = 16 if deep_analysis else 0

    for idx, move in enumerate(moves, start=1):
        move_raw_en = san_moves[idx - 1]
        delta = 0
        pv_san = ""
        
        # Conserver le calcul delta pour les statistiques globales du JSON
        if engine:
            try:
                info = engine.analyse(board_before, chess.engine.Limit(depth=resolve_stockfish_depth(14)))
                if "pv" in info and len(info["pv"]) > 0:
                    b_temp = board_before.copy()
                    pv_list = []
                    for m in info["pv"][:4]:
                        pv_list.append(b_temp.san(m))
                        b_temp.push(m)
                    pv_san = " ".join(pv_list)

                eval_before, eval_after, move_obj = analyzer.analyze_move(board_before, move_raw_en)
                board_after = board_before.copy()
                board_after.push(move_obj)
                pm = 1 if board_before.turn == chess.WHITE else -1
                val_before = get_eval_value(eval_before, board_before) * pm
                val_after = get_eval_value(eval_after, board_after) * pm
                delta = val_after - val_before
            except Exception: pass

        # Centralisation via chess_lib comme pour traps et openings
        future_moves = san_moves[idx:]
        llm_comment = ""
        
        if idx <= max_deep_moves:
            llm_comment, move_label = generate_move_comment(
                move_raw_en, move_raw_en, board_before, is_trap=False, future_moves=future_moves
            )
        else:
            board_test_check = board_before.copy()
            board_test_check.push(move)
            suffix = infer_move_suffix(
                is_check=board_test_check.is_check(), 
                is_checkmate=board_test_check.is_checkmate(), 
                delta=delta
            )
            san_fr = convert_english_to_french_notation(move_raw_en)
            move_label = f"{san_fr}{suffix}" if suffix else san_fr

        if idx <= 12 and delta <= -250 and pv_san:
            opening_blunders_data.append({
                "played_move": move_raw_en,
                "stockfish_pv": pv_san,
                "fen": board_before.fen()
            })

        if delta <= -300: blunders += 1
        elif delta >= 180: good_moves += 1

        phase = "opening" if idx <= 12 else "middlegame" if idx <= 30 else "endgame"
        phase_bucket = {"opening": opening_phase, "middlegame": middlegame_phase, "endgame": endgame_phase}[phase]
        phase_bucket.append({"move": move_label, "delta": delta})

        board_before.push(move)
        
        details.append({
            "ply": idx,
            "move_number": (idx + 1) // 2,
            "color": "white" if idx % 2 != 0 else "black",
            "move": move_label,
            "raw_san": move_raw_en,
            "comment": llm_comment,
            "fen": board_before.fen(),
            "delta": round(delta, 2),
            "phase": phase,
        })

    summary = {
        "opening": {"good_moves": sum(1 for i in opening_phase if i.get("delta", 0) >= 180), "blunders": sum(1 for i in opening_phase if i.get("delta", 0) <= -300)},
        "middlegame": {"good_moves": sum(1 for i in middlegame_phase if i.get("delta", 0) >= 180), "blunders": sum(1 for i in middlegame_phase if i.get("delta", 0) <= -300)},
        "endgame": {"good_moves": sum(1 for i in endgame_phase if i.get("delta", 0) >= 180), "blunders": sum(1 for i in endgame_phase if i.get("delta", 0) <= -300)}
    }

    return {
        "id": game_url,
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
            "summary": summary, 
            "details": details, 
            "blunders": blunders, 
            "good_moves": good_moves,
            "opening_blunders": opening_blunders_data
        }
    }

# =====================================================================
# RENDU PDF
# =====================================================================

def ajouter_pied_page_rapport(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(COLOR_TEXT)
    canvas.drawString(36, 20, "Rapport Analytique Complet - Chess Docs")
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()

def render_game_analysis_table(game, normal_style, bold_style):
    elements = []
    details = game.get("analysis", {}).get("details", [])
    
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
        if ply.get("phase") != "opening": continue
        
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
        ('BACKGROUND', (0,0), (-1,0), COLOR_PRIMARY), ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('VALIGN', (0,0), (-1,-1), 'TOP'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, COLOR_BG_LIGHT]),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, COLOR_BORDER), ('PADDING', (0,0), (-1,-1), 6)
    ]))
    elements.append(t)
    return elements

def build_pdf(output_path, state, player_name, opponent_name=None):
    debug_log(f"Génération du PDF : {output_path}", "INFO")
    doc = SimpleDocTemplate(output_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=22, leading=26, textColor=COLOR_PRIMARY, spaceAfter=5)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11, leading=14, textColor=COLOR_TEXT, spaceAfter=20)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=16, leading=20, textColor=COLOR_SECONDARY, spaceAfter=12)
    subsection_style = ParagraphStyle("SubSection", parent=styles["Heading3"], fontSize=14, leading=18, textColor=COLOR_MINT, spaceAfter=8)
    normal_style = ParagraphStyle("NormalCustom", parent=styles["Normal"], fontSize=10, leading=14, textColor=COLOR_TEXT)
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

    if not games:
        elements.append(Paragraph("Aucune partie trouvée pour ces critères.", normal_style))
        doc.build(elements)
        return

    wins = sum(1 for g in games if (g["result"] == "1-0" and g["white"]["username"].lower() == player_name.lower()) or (g["result"] == "0-1" and g["black"]["username"].lower() == player_name.lower()))
    losses = sum(1 for g in games if (g["result"] == "0-1" and g["white"]["username"].lower() == player_name.lower()) or (g["result"] == "1-0" and g["black"]["username"].lower() == player_name.lower()))
    draws = len(games) - wins - losses

    elements.append(Paragraph("1. Vue d'ensemble", section_style))
    summary_text = f"Analyse basée sur <b>{len(games)} parties</b>. Bilan pour {player_name} : <font color='green'>{wins} V</font> / <font color='gray'>{draws} N</font> / <font color='red'>{losses} D</font>."
    elements.extend([Paragraph(summary_text, normal_style), Spacer(1, 15)])

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
                
                # Utilisation de la fonction centralisée de chess_lib
                theory_text = get_stockfish_theory_summary(
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
    for idx, g in enumerate(deep_games[:5]):
        if idx > 0: elements.append(Spacer(1, 20))
        g["player_focus"] = player_name
        white, black = g["white"]["username"], g["black"]["username"]
        title = f"Partie {idx+1} : {white} vs {black} ({g['date']})"
        
        elements.append(KeepTogether([
            Paragraph(title, subsection_style),
            Paragraph(f"Ouverture : {g.get('opening')} | Résultat : {g['result']}", normal_style),
            Spacer(1, 10)
        ] + render_game_analysis_table(g, normal_style, bold_style)))

    doc.build(elements, onFirstPage=ajouter_pied_page_rapport, onLaterPages=ajouter_pied_page_rapport)
    debug_log(f"PDF généré avec succès : {output_path}", "ESSENTIAL")

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

    # Logique harmonisée pour la gestion du debug
    enabled, level = (True, max(int(args.verbose), 1)) if args.verbose else (False, 0)
    set_debug_enabled(enabled, level=level)
    
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
            
            is_h2h = False
            if args.opponent:
                op_l = args.opponent.lower()
                if w_name == op_l or b_name == op_l: is_h2h = True
            
            do_deep = is_h2h if args.opponent else True
            
            if game_id not in existing_games or (do_deep and not existing_games[game_id].get("deep_analysis")):
                parsed = parse_game_record(g, args.player, deep_analysis=do_deep)
                if parsed:
                    existing_games[game_id] = parsed
                    state["games"] = existing_games
                    save_state(str(state_path), state)
        
        state["player"] = args.player
        state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_state(str(state_path), state)
        
        build_pdf(str(output_path), state, args.player, args.opponent)

    finally:
        ollama_mgr.stop()

if __name__ == "__main__":
    main()
