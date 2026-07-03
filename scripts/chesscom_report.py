import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from statistics import mean

import chess
import chess.pgn
import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Import from existing shared module
from chess_lib import (
    COLOR_BG_LIGHT,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_TEXT,
    StockfishAnalyzer,
    debug_log,
    get_eval_value,
    resolve_stockfish_depth,
    set_debug_enabled,
)


DEFAULT_STATE_FILENAME = "chesscom_report_state.json"
DEFAULT_PDF_FILENAME = "player_report.pdf"


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
        if not self.values or len(self.values) < 2:
            return
        x0 = 30
        y0 = 20
        x1 = self.width - 20
        y1 = self.height - 20
        self.canv.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.canv.setLineWidth(0.6)
        self.canv.rect(x0, y0, x1 - x0, y1 - y0)

        if len(self.values) == 1:
            x = (x0 + x1) / 2
            self.canv.circle(x, y0 + (y1 - y0) / 2, 3, stroke=0, fill=1)
            return

        min_value = min(self.values)
        max_value = max(self.values)
        span = max_value - min_value or 1
        points = []
        for idx, value in enumerate(self.values):
            x = x0 + (idx / max(len(self.values) - 1, 1)) * (x1 - x0)
            y = y0 + ((max_value - value) / span) * (y1 - y0)
            points.append((x, y))

        # CORRECTION ICI :
        # On crée des segments reliant les points consécutifs
        segments = []
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i+1]
            segments.append((p1[0], p1[1], p2[0], p2[1]))

        self.canv.setStrokeColor(COLOR_SECONDARY := colors.HexColor("#0284c7"))
        self.canv.setLineWidth(1.2)
        self.canv.lines(segments)
        self.canv.setFillColor(COLOR_PRIMARY)
        for x, y in points:
            self.canv.circle(x, y, 2.6, stroke=0, fill=1)

        if self.labels:
            self.canv.setFont("Helvetica", 8)
            self.canv.setFillColor(COLOR_TEXT)
            step = max(1, len(self.labels) // 4)
            for idx, label in enumerate(self.labels):
                if idx % step != 0 and idx != len(self.labels) - 1:
                    continue
                x = x0 + (idx / max(len(self.values) - 1, 1)) * (x1 - x0)
                self.canv.drawString(x - 10, y0 - 8, label[:8])


def classify_opponent_type(username):
    if not username:
        return "humain"
    lowered = username.lower()
    if any(token in lowered for token in ["bot", "engine", "stockfish", "computer", "ai", "chess.com"]):
        return "autre"
    return "humain"


def infer_move_suffix(is_check=False, is_checkmate=False, delta=None):
    if is_checkmate:
        return "#"
    if is_check:
        return "+"
    if delta is None:
        return ""
    if delta <= -400:
        return "??"
    if delta <= -120:
        return "?"
    if delta >= 400:
        return "!!"
    if delta >= 160:
        return "!"
    return ""


def build_player_state_path(base_dir, player_name):
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", player_name).strip("_") or "player"
    return os.path.join(base_dir, "json", f"player_{safe_name}.json")


def resolve_project_base_dir():
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent


def load_state(path):
    if not path or not os.path.exists(path):
        return {"player": None, "games": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            # Rétrocompatibilité : si les parties sont encore sous forme de liste, on convertit en dictionnaire indexé par 'id'
            if isinstance(data.get("games"), list):
                debug_log("Conversion des parties (Liste -> Dictionnaire) pour rétrocompatibilité.", "INFO")
                data["games"] = {g["id"]: g for g in data["games"] if "id" in g}
            elif not isinstance(data.get("games"), dict):
                data["games"] = {}
            return data
    except Exception:
        pass
    return {"player": None, "games": {}}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))


def fetch_player_games(username, months=6):
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    debug_log(f"Récupération des archives Chess.com pour {username} (mois={months})", "INFO")

    def request_with_retry(url, retries=3):
        last_error = None
        for attempt in range(retries):
            try:
                debug_log(f"Requête Chess.com ({attempt + 1}/{retries}) -> {url}", "DEBUG")
                response = requests.get(url, timeout=25, headers=headers)
                if response.status_code in {403, 429} and attempt < retries - 1:
                    debug_log(f"Code HTTP {response.status_code} pour {url}; nouvelle tentative", "WARNING")
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                debug_log(f"Réponse OK pour {url} (status={response.status_code})", "DEBUG")
                return response
            except requests.RequestException as exc:
                last_error = exc
                debug_log(f"Échec requête {url}: {exc}", "WARNING")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        raise last_error or requests.RequestException("Échec de la requête Chess.com")

    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    response = request_with_retry(archives_url)
    data = response.json()
    archives = data.get("archives", [])
    debug_log(f"Nombre d'archives trouvées: {len(archives)}", "INFO")
    if not archives:
        return []

    recent_archives = archives[-months:] if months and months > 0 else archives
    games = []
    for index, archive_url in enumerate(recent_archives, start=1):
        debug_log(f"Traitement archive {index}/{len(recent_archives)}: {archive_url}", "INFO")
        archive_response = request_with_retry(archive_url)
        payload = archive_response.json()
        archive_games = payload.get("games", [])
        debug_log(f"Archive {index}: {len(archive_games)} partie(s) récupérée(s)", "INFO")
        games.extend(archive_games)
    debug_log(f"Total de parties récupérées: {len(games)}", "INFO")
    return games


def parse_game_record(game, username):
    game_url = game.get("url")
    debug_log(f"Analyse d'une partie: {game_url or game.get('end_time') or 'inconnue'}", "INFO")
    pgn_text = game.get("pgn") or ""
    if not pgn_text:
        return None

    try:
        game_obj = chess.pgn.read_game(StringIO(pgn_text))
    except Exception:
        return None

    if not game_obj:
        return None

    white = game.get("white", {}) or {}
    black = game.get("black", {}) or {}
    white_name = white.get("username") or game.get("white", {}).get("username") or ""
    black_name = black.get("username") or game.get("black", {}).get("username") or ""

    result = game.get("result") or "*"
    if result == "win" and white_name == username:
        result_text = "1-0"
    elif result == "win" and black_name == username:
        result_text = "0-1"
    else:
        result_text = "1/2-1/2" if result == "draw" else "*"

    board = game_obj.board()
    moves = list(game_obj.mainline_moves())
    debug_log(f"Partie parsée avec {len(moves)} coups", "DEBUG")
    details = []
    notable_moves = []
    blunders = 0
    good_moves = 0
    opening_phase = []
    middlegame_phase = []
    endgame_phase = []
    board_before = game_obj.board()

    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine(depth=resolve_stockfish_depth(12))

    for idx, move in enumerate(moves, start=1):
        if idx % 10 == 0 or idx == 1:
            debug_log(f"Analyse du coup {idx}/{len(moves)}", "DEBUG")
        move_san = board_before.san(move)
        is_check = board_before.is_check()
        is_checkmate = False
        maybe_eval = None
        best_move = None
        delta = 0

        if engine:
            try:
                eval_before, eval_after, move_obj = analyzer.analyze_move(board_before, move_san)
                board_after = board_before.copy()
                board_after.push(move_obj)
                player_multiplier = 1 if board_before.turn == chess.WHITE else -1
                val_before = get_eval_value(eval_before, board_before) * player_multiplier
                val_after = get_eval_value(eval_after, board_after) * player_multiplier
                delta = val_after - val_before
                best_move_info = analyzer.get_best_move_with_eval(board_before.copy())
                if best_move_info and best_move_info[0]:
                    best_move = best_move_info[0]
                is_check = board_after.is_check()
                is_checkmate = board_after.is_checkmate()
            except Exception:
                delta = 0

        suffix = infer_move_suffix(is_check=is_check, is_checkmate=is_checkmate, delta=delta)
        move_label = f"{move_san}{suffix}" if suffix else move_san

        if delta <= -300:
            blunders += 1
            entry = {
                "ply": idx,
                "move": move_label,
                "detail": "Coup très faible selon l'analyse Stockfish",
                "alternative": best_move,
            }
            notable_moves.append(entry)
        elif delta >= 180:
            good_moves += 1
            entry = {
                "ply": idx,
                "move": move_label,
                "detail": "Coup de qualité selon l'analyse Stockfish",
                "alternative": best_move,
            }
            notable_moves.append(entry)

        phase = "opening" if idx <= 12 else "middlegame" if idx <= 30 else "endgame"
        phase_bucket = {
            "opening": opening_phase,
            "middlegame": middlegame_phase,
            "endgame": endgame_phase,
        }[phase]
        phase_bucket.append({"move": move_label, "delta": delta})

        details.append({
            "ply": idx,
            "move": move_label,
            "delta": round(delta, 2),
            "suffix": suffix,
            "phase": phase,
        })
        board_before.push(move)

    summary = {
        "opening": {
            "good_moves": sum(1 for item in opening_phase if item.get("delta", 0) >= 180),
            "blunders": sum(1 for item in opening_phase if item.get("delta", 0) <= -300),
        },
        "middlegame": {
            "good_moves": sum(1 for item in middlegame_phase if item.get("delta", 0) >= 180),
            "blunders": sum(1 for item in middlegame_phase if item.get("delta", 0) <= -300),
        },
        "endgame": {
            "good_moves": sum(1 for item in endgame_phase if item.get("delta", 0) >= 180),
            "blunders": sum(1 for item in endgame_phase if item.get("delta", 0) <= -300),
        },
    }

    debug_log(f"Résumé de partie généré: blunders={blunders}, good_moves={good_moves}", "INFO")

    return {
        "id": game_url,
        "uuid": game.get("uuid"),
        "url": game_url,
        "date": datetime.fromtimestamp(game.get("end_time", 0)).strftime("%Y-%m-%d") if game.get("end_time") else None,
        "end_time": game.get("end_time"),
        "result": result_text,
        "time_class": game.get("time_class"),
        "time_control": game.get("time_control"),
        "rated": game.get("rated"),
        "accuracies": game.get("accuracies"),
        "opening": game.get("opening", {}).get("eco") if isinstance(game.get("opening"), dict) else None,
        "white": {"username": white_name, "elo": white.get("rating")},
        "black": {"username": black_name, "elo": black.get("rating")},
        "analysis": {
            "summary": summary,
            "details": details,
            "notable_moves": notable_moves[:10],
            "blunders": blunders,
            "good_moves": good_moves,
        },
    }


def merge_games(existing_games_dict, new_games_dict):
    # Les entrées fusionnent naturellement. Les nouvelles remplacent/s'ajoutent par ID.
    merged = dict(existing_games_dict)
    for game_id, game_data in new_games_dict.items():
        if game_id not in merged:
            merged[game_id] = game_data
    return merged


def merge_state_with_incremental_games(existing_state, new_state):
    existing_games = (existing_state or {}).get("games", {})
    incoming_games = (new_state or {}).get("games", {})
    
    # Conversion si nécessaire (au cas où d'autres scripts envoient des listes)
    if isinstance(existing_games, list):
        existing_games = {g["id"]: g for g in existing_games if "id" in g}
    if isinstance(incoming_games, list):
        incoming_games = {g["id"]: g for g in incoming_games if "id" in g}

    merged_games = merge_games(existing_games, incoming_games)
    merged_state = dict(existing_state or {"player": None, "games": {}})
    merged_state["player"] = (new_state or {}).get("player") or merged_state.get("player") or ""
    merged_state["games"] = merged_games
    merged_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return merged_state


def refresh_state_with_player_games(existing_state, player_name, months=6, state_path=None):
    state = dict(existing_state or {"player": None, "games": {}})
    debug_log(f"Refresh de l'état pour {player_name} (mois={months})", "INFO")
    
    existing_games = state.get("games", {})
    if isinstance(existing_games, list):
        existing_games = {g["id"]: g for g in existing_games if "id" in g}

    try:
        fetched_games = fetch_player_games(player_name, months=months)
        debug_log(f"{len(fetched_games)} parties brutes récupérées", "INFO")
        
        for index, game in enumerate(fetched_games, start=1):
            game_id = game.get("url")
            
            # Recherche en O(1) ultra rapide via le dictionnaire
            if game_id and game_id in existing_games:
                continue

            parsed = parse_game_record(game, player_name)
            if parsed:
                debug_log(f"Partie intégrée au state: {parsed['id']}", "INFO")
                existing_games[parsed["id"]] = parsed  # Stockage clé=valeur
                
                # Mise à jour et sauvegarde immédiate après chaque analyse
                state["player"] = player_name
                state["games"] = existing_games
                state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if state_path:
                    save_state(state_path, state)
                    debug_log(f"Sauvegarde incrémentale effectuée avec succès dans {state_path}", "INFO")

        state = {"player": player_name, "games": existing_games}
        state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        debug_log(f"État final mis à jour avec {len(existing_games)} parties", "INFO")
        return state, True, "Données récupérées depuis Chess.com"
    except Exception as exc:
        if existing_games:
            state = {"player": player_name, "games": existing_games}
            state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            debug_log(f"Utilisation de l'état existant ({len(existing_games)} parties) après erreur: {exc}", "WARNING")
            return state, False, f"Utilisation des données déjà sauvegardées : {exc}"
        debug_log(f"Aucune donnée sauvegardée disponible après erreur: {exc}", "WARNING")
        return {"player": player_name, "games": {}}, False, f"Aucune donnée sauvegardée disponible : {exc}"


def summarize_games(games):
    if not games:
        return {"games_count": 0, "results": {}, "average_elo": None, "top_openings": []}

    results = {}
    elos = []
    openings = {}
    for game in games:
        results[game.get("result", "*")] = results.get(game.get("result", "*"), 0) + 1
        white_elo = game.get("white", {}).get("elo")
        black_elo = game.get("black", {}).get("elo")
        if isinstance(white_elo, int) and white_elo > 0:
            elos.append(white_elo)
        if isinstance(black_elo, int) and black_elo > 0:
            elos.append(black_elo)
        opening = game.get("opening") or ""
        if opening:
            openings[opening] = openings.get(opening, 0) + 1

    top_openings = sorted(openings.items(), key=lambda item: item[1], reverse=True)[:5]
    return {
        "games_count": len(games),
        "results": results,
        "average_elo": round(mean(elos), 1) if elos else None,
        "top_openings": top_openings,
    }


def build_report_payload(player_name, state):
    games_data = state.get("games", {})
    # Récupération des parties sous forme de liste pour construire le rapport PDF
    if isinstance(games_data, dict):
        games = list(games_data.values())
    else:
        games = games_data

    # Tri des jeux par date (optionnel, pour l'affichage séquentiel de l'historique dans le PDF)
    games = sorted(games, key=lambda g: g.get("end_time") or 0)

    summary = summarize_games(games)
    opponent_types = {}
    elo_history = []
    opening_focus = []
    openings = {}
    
    for game in games:
        white_name = game.get("white", {}).get("username") or ""
        black_name = game.get("black", {}).get("username") or ""
        opponent_type = classify_opponent_type(black_name if white_name == player_name else white_name)
        opponent_types[opponent_type] = opponent_types.get(opponent_type, 0) + 1
        if game.get("white", {}).get("elo") and game.get("black", {}).get("elo"):
            if white_name == player_name:
                elo_history.append((game.get("date"), game.get("white", {}).get("elo")))
            else:
                elo_history.append((game.get("date"), game.get("black", {}).get("elo")))

        opening = game.get("opening") or ""
        if opening:
            bucket = openings.setdefault(opening, {"games": 0, "good_moves": 0, "blunders": 0, "samples": []})
            bucket["games"] += 1
            analysis = game.get("analysis", {}) or {}
            summary_data = analysis.get("summary", {}) or {}
            bucket["good_moves"] += summary_data.get("opening", {}).get("good_moves", 0)
            bucket["blunders"] += summary_data.get("opening", {}).get("blunders", 0)
            if analysis.get("notable_moves"):
                bucket["samples"].append(analysis["notable_moves"][0].get("move", ""))

    phase_summary = {"opening": {"good": 0, "blunders": 0}, "middlegame": {"good": 0, "blunders": 0}, "endgame": {"good": 0, "blunders": 0}}
    for game in games:
        analysis = game.get("analysis", {}) or {}
        summary_data = analysis.get("summary", {}) or {}
        for phase in phase_summary:
            phase_summary[phase]["good"] += summary_data.get(phase, {}).get("good_moves", 0)
            phase_summary[phase]["blunders"] += summary_data.get(phase, {}).get("blunders", 0)

    for opening_name, bucket in sorted(openings.items(), key=lambda item: item[1]["games"], reverse=True)[:8]:
        opening_focus.append({
            "opening": opening_name,
            "games": bucket["games"],
            "good_moves": bucket["good_moves"],
            "blunders": bucket["blunders"],
            "sample": ", ".join(bucket["samples"][:3]) if bucket["samples"] else "",
        })

    return {
        "player": player_name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "opponent_types": opponent_types,
        "elo_history": elo_history,
        "phase_summary": phase_summary,
        "opening_focus": opening_focus,
        "games": games,
    }


def build_pdf(output_path, payload):
    debug_log(f"Début génération PDF: {output_path}", "INFO")
    doc = SimpleDocTemplate(output_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=20, leading=24, textColor=COLOR_PRIMARY, spaceAfter=10)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=10, leading=14, textColor=COLOR_TEXT, spaceAfter=8)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13, leading=16, textColor=COLOR_PRIMARY, spaceAfter=8)
    normal_style = ParagraphStyle("NormalCustom", parent=styles["Normal"], fontSize=10, leading=13, textColor=COLOR_TEXT)
    bold_style = ParagraphStyle("BoldCustom", parent=normal_style, fontName="Helvetica-Bold")

    elements = [
        Paragraph(f"Rapport de joueur Chess.com : {payload['player']}", title_style),
        Paragraph(f"Généré le {payload['generated_at']}", subtitle_style),
        Spacer(1, 8),
    ]

    summary = payload.get("summary", {})
    results = summary.get("results", {})
    elements.extend([
        Paragraph("1. Vue d'ensemble", section_style),
        Paragraph(
            f"Parties analysées : {summary.get('games_count', 0)}. Résultats : {', '.join(f'{key}={value}' for key, value in results.items()) or 'aucun'}. "
            f"Élo moyen observé : {summary.get('average_elo') or 'n/a'}.",
            normal_style,
        ),
        Paragraph(
            f"Ouvertures fréquentes : {', '.join(f'{name} ({count})' for name, count in summary.get('top_openings', [])[:3]) or 'n/a'}",
            normal_style,
        ),
        Spacer(1, 10),
    ])

    elo_history = payload.get("elo_history", [])
    if elo_history:
        values = [value for _, value in elo_history[-12:]]
        labels = [date or "" for date, _ in elo_history[-12:]]
        elements.extend([
            Paragraph("2. Évolution du classement", section_style),
            SimpleLineChart(values, labels=labels),
            Spacer(1, 10),
        ])

    phase_summary = payload.get("phase_summary", {})
    elements.extend([
        Paragraph("3. Analyse par phase", section_style),
        Paragraph(
            f"Ouverture : {phase_summary.get('opening', {}).get('good', 0)} coups de qualité, {phase_summary.get('opening', {}).get('blunders', 0)} erreurs majeures. ",
            normal_style,
        ),
        Paragraph(
            f"Milieu de partie : {phase_summary.get('middlegame', {}).get('good', 0)} coups de qualité, {phase_summary.get('middlegame', {}).get('blunders', 0)} erreurs majeures. ",
            normal_style,
        ),
        Paragraph(
            f"Fin de partie : {phase_summary.get('endgame', {}).get('good', 0)} coups de qualité, {phase_summary.get('endgame', {}).get('blunders', 0)} erreurs majeures. ",
            normal_style,
        ),
        Spacer(1, 10),
    ])

    opponent_types = payload.get("opponent_types", {})
    elements.extend([
        Paragraph("4. Adversaires", section_style),
        Paragraph(
            f"Type humain : {opponent_types.get('humain', 0)} parties. Type autre : {opponent_types.get('autre', 0)} parties.",
            normal_style,
        ),
        Spacer(1, 10),
    ])

    opening_focus = payload.get("opening_focus", [])
    if opening_focus:
        elements.extend([Paragraph("5. Analyse par ouverture", section_style)])
        for item in opening_focus[:6]:
            elements.append(Paragraph(
                f"• {item['opening']} — {item['games']} partie(s), {item['good_moves']} coup(s) de qualité, {item['blunders']} erreur(s) majeure(s)",
                normal_style,
            ))
            if item.get("sample"):
                elements.append(Paragraph(f"  Exemples : {item['sample']}", normal_style))
            elements.append(Spacer(1, 4))
        elements.append(Spacer(1, 8))

    elements.extend([Paragraph("6. Coups notables", section_style)])
    # Inversion ici pour afficher les parties les plus récentes en premier
    for game in list(reversed(payload.get("games", [])))[:8]:
        analysis = game.get("analysis", {}) or {}
        notable_moves = analysis.get("notable_moves", [])
        if not notable_moves:
            continue
        moves_text = ", ".join(
            f"{move['move']} ({move.get('detail', '')}; alternative: {move.get('alternative') or 'n/a'})"
            for move in notable_moves[:4]
        )
        elements.append(Paragraph(f"{game.get('date') or 'Sans date'} — {game.get('result')} — {moves_text}", normal_style))
        elements.append(Spacer(1, 6))

    doc.build(elements)
    debug_log("PDF généré avec succès", "INFO")


def main():
    parser = argparse.ArgumentParser(description="Génère un rapport PDF à partir des parties publiques d'un joueur Chess.com")
    parser.add_argument("player", nargs="?", help="Nom d'utilisateur Chess.com")
    parser.add_argument("--months", type=int, default=6, help="Nombre de mois d'historique à récupérer")
    parser.add_argument("--state-file", default=None, help="Chemin du fichier JSON de persistance")
    parser.add_argument("--output", default=None, help="Chemin du PDF de sortie")
    parser.add_argument("--verbose", nargs="?", const=1, default=0, type=int, help="Active les logs de debug détaillés avec un niveau optionnel (1 par défaut)")
    args = parser.parse_args()

    if not args.player:
        parser.error("Un nom de joueur est requis")

    enabled, level = (True, max(int(args.verbose), 1)) if args.verbose else (False, 0)
    set_debug_enabled(enabled, level=level)
    debug_log("=== Début du traitement du rapport joueur ===", "ESSENTIAL")
    debug_log(f"Joueur demandé: {args.player}", "INFO")
    debug_log(f"Paramètres: months={args.months}, state_file={args.state_file}, output={args.output}", "DEBUG")
    base_dir = resolve_project_base_dir()
    state_path = Path(args.state_file or build_player_state_path(str(base_dir), args.player))
    safe_player_name = re.sub(r'[^a-zA-Z0-9._-]+', '_', args.player).strip('_') or 'player'
    output_path = Path(args.output or str(base_dir / f"{safe_player_name}_report.pdf"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    state = load_state(str(state_path))
    debug_log(f"État chargé depuis {state_path} (joueur={state.get('player')}, parties={len(state.get('games', {}))})", "INFO")
    
    if state.get("player") and state.get("player") != args.player:
        state = {"player": None, "games": {}}

    # Passage du state_path pour permettre l'écriture incrémentale
    state, refreshed, message = refresh_state_with_player_games(state, args.player, months=args.months, state_path=str(state_path))
    if not state.get("last_updated"):
        state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(str(state_path), state)
    
    if refreshed:
        debug_log(message, "ESSENTIAL")
    else:
        debug_log(message, "WARNING")

    payload = build_report_payload(args.player, state)
    build_pdf(str(output_path), payload)
    
    if not state.get("games"):
        debug_log("Aucun jeu chargé; le rapport sera basé sur un état vide", "WARNING")
        debug_log("Aucun jeu n'a pu être chargé. Le rapport a été généré à partir d'un état vide.", "ESSENTIAL")
    
    debug_log(f"Rapport généré : {output_path}", "ESSENTIAL")
    debug_log(f"État persistant : {state_path}", "ESSENTIAL")


if __name__ == "__main__":
    main()
