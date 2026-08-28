import os
import sys
import re
import json
import chess
import hashlib
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Ajoute le répertoire parent au chemin de recherche des modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importation depuis le nouveau dossier "classes"
from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import StockfishAnalyzer
from classes.ai_analyzer import AIAnalyzer
from classes.pdf_components import ChessboardFlowable, PDFUtils
from classes.json_cache import CacheManager

def classify_trap(piege):
    coups = piege["coups"]
    if "#" in coups: return "Mat"
    if "x" in coups: return "Gain matériel"
    return "Tactique"

def estimate_difficulty(piege):
    coups = piege["coups"]
    if "??" in coups: return "Facile"
    if "!" in coups: return "Intermédiaire"
    return "Avancé"

def analyze_position(fen):
    board = chess.Board(fen)
    if list(board.attackers(not board.turn, board.king(board.turn))):
        return "Le roi est en danger immédiat."
    return "Position relativement sûre."

def get_trap_orientation(piege):
    return chess.WHITE if piege.get("defenseur") == "Blancs" else chess.BLACK

def validate_fen(fen):
    if not fen: return False
    try:
        chess.Board(fen)
        return True
    except ValueError:
        return False

def normalize_defense_spec(defense_text):
    if not defense_text: return None, ""
    match = re.match(r'^(\d+)\s*(?:\.{3}|\.)\s*(.+)$', defense_text.strip())
    if match: return int(match.group(1)), match.group(2).strip()
    return None, defense_text.strip()

def split_move_options(moves_text):
    return [m.strip() for m in re.split(r'\s+ou\s+|\s*,\s*', moves_text) if m.strip()]

def generate_moves_table(piege, stockfish_depth=18):
    Logger.debug_log(f"Génération table des coups pour le piège {piege.get('nom', 'sans nom')}", "INFO")
    StockfishAnalyzer().get_engine(depth=stockfish_depth)
    moves = ChessUtils.parse_moves(piege.get("coups", ""))
    rows, board, current_row = [], chess.Board(), None

    # Chargement du cache dédié aux pièges
    cache = CacheManager.load_cache(CacheManager.TRAP_CACHE_FILE)
    cache_updated = False

    for i, move in enumerate(moves):
        move_san = move.get("san", "")
        future_moves = [m.get("san", "") for m in moves[i+1:]]
        
        # Clé unique basée sur la position exacte (FEN) et le coup joué
        fen_before = board.fen()
        cache_key = f"trap_{fen_before}_{move_san}"
        
        # Vérification du cache : si vide ou absent, on regénère
        if cache_key in cache and cache[cache_key].get("commentaire") and cache[cache_key].get("coup_annote"):
            commentaire = cache[cache_key]["commentaire"]
            coup_annote = cache[cache_key]["coup_annote"]
            Logger.debug_log(f"[Cache Hit] Coup {move_san}", "DEBUG")
        else:
            commentaire, coup_annote, _, _ = AIAnalyzer.generate_move_comment(move.get("raw", ""), move_san, board, is_trap=True, future_moves=future_moves)
            Logger.debug_log(f"[Génération IA] {move_san} -> {commentaire.strip()}", "DEBUG")
            cache[cache_key] = {"commentaire": commentaire, "coup_annote": coup_annote}
            cache_updated = True
        
        try: board.push(board.parse_san(move_san))
        except Exception: pass
        fen_after = board.fen()

        if move.get("color") == "white":
            current_row = {"move_number": move["move_number"], "white": coup_annote, "white_comment": commentaire, "white_fen": fen_after, "black": "", "black_comment": "", "black_fen": None}
            rows.append(current_row)
        else:
            if not current_row or current_row["move_number"] != move["move_number"]:
                current_row = {"move_number": move["move_number"], "white": "", "white_comment": "", "white_fen": None, "black": coup_annote, "black_comment": commentaire, "black_fen": fen_after}
                rows.append(current_row)
            else:
                current_row.update({"black": coup_annote, "black_comment": commentaire, "black_fen": fen_after})
                
    # Sauvegarde uniquement s'il y a eu des modifications
    if cache_updated:
        CacheManager.save_cache(cache, CacheManager.TRAP_CACHE_FILE)
        
    return rows

def generate_fen_positions(piege):
    moves = ChessUtils.parse_moves(piege.get("coups", ""))
    board, positions = chess.Board(), []
    for move in moves:
        try:
            board.push(board.parse_san(move["san"]))
            positions.append(board.fen())
        except Exception: return None, None, None
    
    if len(positions) < 2: return positions[-1] if positions else None, None, None
    fen_final = positions[-1]

    defense_order, defense_text = normalize_defense_spec(piege.get("coup_defense", ""))
    defense_options = split_move_options(defense_text)

    if defense_order is not None:
        index = 2 * defense_order - 1 if piege.get("defenseur") == "Noirs" else 2 * defense_order - 2
        fen_intermediaire = positions[index] if 0 <= index < len(positions) else positions[-2]
    else:
        fen_intermediaire = positions[-3] if len(positions) >= 3 else positions[-2]

    fen_defense = fen_intermediaire
    if len(defense_options) == 1:
        try:
            board_def = chess.Board(fen_intermediaire)
            board_def.push(board_def.parse_san(ChessUtils.convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', defense_options[0]))))
            fen_defense = board_def.fen()
        except Exception: pass

    return fen_final, fen_intermediaire, fen_defense

def ajouter_pied_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(Config.COLOR_TEXT)
    canvas.drawString(36, 20, "Guide des 20 Pièges d'Ouverture")
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()

def estimate_trap_elo(piege, stockfish_depth):
    cache = CacheManager.load_cache(CacheManager.TRAP_CACHE_FILE)
    
    coups_str = piege.get("coups", "")
    # Empreinte MD5 et version 2 pour forcer le recalcul (tuple au lieu d'int)
    cache_key = f"elo_trap_v2_{hashlib.md5(coups_str.encode()).hexdigest()}"
    
    if cache_key in cache:
        return cache[cache_key]

    analyzer = StockfishAnalyzer()
    engine = analyzer.get_engine(depth=stockfish_depth)
    if not engine: return 1200, 1200
    
    moves = ChessUtils.parse_moves(coups_str)
    board = chess.Board()
    attacker_color_str = "white" if piege.get("defenseur") == "Noirs" else "black"
    
    details = []
    for move in moves:
        san = move.get("san")
        color = move.get("color")
        if not san: continue
        
        # On évalue tous les coups (attaquant et défenseur)
        eval_before, eval_after, move_obj = analyzer.analyze_move(board, san)
        _, best_eval, best_uci = analyzer.get_best_move_with_eval(board.copy())
        
        if eval_after and best_eval and move_obj:
            board_after = board.copy()
            board_after.push(move_obj)
            
            val_after = ChessUtils.get_eval_value(eval_after, board_after)
            
            board_best = board.copy()
            if best_uci:
                try: board_best.push(chess.Move.from_uci(best_uci))
                except Exception: pass
            val_best = ChessUtils.get_eval_value(best_eval, board_best)
            
            multiplier = 1 if board.turn == chess.WHITE else -1
            eval_player_after = val_after * multiplier
            eval_player_best = val_best * multiplier
            
            delta = eval_player_after - eval_player_best
            if board_after.is_checkmate() or (best_uci and move_obj.uci() == best_uci):
                delta = 0
                
            details.append({"color": color, "precision": delta})
        
        try: board.push(board.parse_san(san))
        except Exception: break
        
    w_elo, b_elo = ChessUtils.calculate_elo_from_details(details)
    
    if attacker_color_str == "white":
        elo_attaquant, elo_defenseur = w_elo, b_elo
    else:
        elo_attaquant, elo_defenseur = b_elo, w_elo
        
    result = (elo_attaquant, elo_defenseur)
    
    cache[cache_key] = result
    CacheManager.save_cache(cache, CacheManager.TRAP_CACHE_FILE)
    
    return result

def generer_pdf(stockfish_depth=18, verbose=1):
    enabled, level = (True, max(int(verbose), 1)) if verbose else (False, 0)
    Logger.set_debug_enabled(enabled, level=level)
    Logger.debug_log("=== Début de la génération des guides de pièges ===", "ESSENTIAL")
    Logger.debug_log("="*70, "ESSENTIAL")
    Logger.debug_log("🔄 Génération du guide des pièges d'ouverture assistée par IA...", "ESSENTIAL")
    Logger.debug_log(f"Profondeur Stockfish retenue : {ChessUtils.resolve_stockfish_depth(stockfish_depth)}", "ESSENTIAL")
    
    base_dir = Path(__file__).resolve().parent.parent
    data_path = base_dir / "json" / "trappes_data.json"
    output_path = base_dir / "guide_pieges_et_defenses.pdf"

    try:
        with data_path.open('r', encoding='utf-8') as f: trappes_data = json.load(f)
        Logger.debug_log("Calcul et tri des pièges par niveau ELO...", "ESSENTIAL")
        for piege in trappes_data:
            elo_att, elo_def = estimate_trap_elo(piege, stockfish_depth)
            piege['elo_attaquant'] = elo_att
            piege['elo_defenseur'] = elo_def
            
        trappes_data.sort(key=lambda p: (p['elo_attaquant'], p['elo_defenseur']))
            
        doc = SimpleDocTemplate(str(output_path), pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, leading=26, textColor=Config.COLOR_PRIMARY, spaceAfter=15)
        intro_style = ParagraphStyle('Intro', parent=styles['Normal'], fontSize=11, leading=16, textColor=Config.COLOR_TEXT, spaceAfter=8)
        legend_heading = ParagraphStyle('LegendHeading', parent=styles['Heading2'], fontSize=14, leading=18, textColor=Config.COLOR_MINT, spaceAfter=10)
        trap_heading = ParagraphStyle('TrapHeading', parent=styles['Heading2'], fontSize=16, leading=20, textColor=Config.COLOR_PRIMARY, spaceAfter=8)
        normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontSize=10, leading=14, textColor=Config.COLOR_TEXT)
        bold_style = ParagraphStyle('CustomBold', parent=normal_style, fontName='Helvetica-Bold')

        elements = [
            Paragraph("Guide des Pièges d'Ouverture", title_style), Spacer(1, 10),
            Paragraph("Ce guide met l'accent sur la détection des menaces tactiques expliquées par l'Intelligence Artificielle.", intro_style),
            Paragraph("Dernière mise à jour le " + datetime.now().strftime("%d/%m/%Y à %H:%M"), intro_style), Spacer(1, 15),
            Paragraph("Légende Globale", legend_heading), Spacer(1, 5)
        ]
        
        legend_table = Table([
            [Paragraph("<b>Section</b>", normal_style), Paragraph("<b>Description</b>", normal_style)],
            [Paragraph("Diagrammes", bold_style), Paragraph("Position finale, intermédiaire de détection, et défense.", normal_style)],
            [Paragraph("Table des coups", bold_style), Paragraph("Coups avec commentaires analytiques.", normal_style)]
        ], colWidths=[120, 420])
        legend_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), Config.COLOR_BG_LIGHT), ('LINEBELOW', (0,0), (-1,0), 1, Config.COLOR_PRIMARY), ('PADDING', (0,0), (-1,-1), 6)]))
        elements.extend([legend_table, PageBreak()])

        for idx, piege in enumerate(trappes_data):
            if idx > 0: elements.append(PageBreak())
            
            Logger.debug_log(f"Analyse du piège {idx+1}/{len(trappes_data)} : {piege.get('nom', 'Sans nom')}", "ESSENTIAL")
            
            bloc = [Paragraph(f"{idx+1}. {piege['nom']}", trap_heading)]
            fen_final, fen_inter, fen_def = generate_fen_positions(piege)
            
            if not fen_final or not validate_fen(fen_final): continue
            
            meta = f"<b>Analyse :</b> {analyze_position(fen_final)} | <b>Type :</b> {classify_trap(piege)} | <b>Difficulté :</b> {estimate_difficulty(piege)}"
            bloc.extend([Paragraph(meta, normal_style), Spacer(1, 10)])

            table_data = [[Paragraph("<b>Diag</b>", normal_style), Paragraph("<b>Blanc</b>", normal_style), Paragraph("<b>Commentaire IA</b>", normal_style), Paragraph("<b>Noir</b>", normal_style), Paragraph("<b>Commentaire IA</b>", normal_style)]]
            orient = get_trap_orientation(piege)
            
            for row in generate_moves_table(piege, stockfish_depth):
                fen = row.get("black_fen") or row.get("white_fen")
                diag = ChessboardFlowable(fen, size=105, orientation=orient) if fen else ""
                table_data.append([diag, Paragraph(row.get("white",""), bold_style), Paragraph(row.get("white_comment",""), normal_style), Paragraph(row.get("black",""), bold_style), Paragraph(row.get("black_comment",""), normal_style)])

            t_coups = Table(table_data, colWidths=[120, 50, 140, 50, 140], repeatRows=1)
            t_coups.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), Config.COLOR_PRIMARY), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, Config.COLOR_BG_LIGHT]), ('PADDING', (0,0), (-1,-1), 6), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
            bloc.append(t_coups)
            elements.extend([KeepTogether(bloc), Spacer(1, 15)])

            t_diags = Table([[Paragraph("<b>1) Piège</b>", normal_style), Paragraph("<b>2) Détection</b>", normal_style), Paragraph("<b>3) Défense</b>", normal_style)],
                             [ChessboardFlowable(fen_final, 130, fleches_menace=piege.get("fleches_menace",[]), orientation=orient),
                              ChessboardFlowable(fen_inter, 130, fleches_menace=piege.get("fleches_menace",[]), orientation=orient),
                              ChessboardFlowable(fen_def, 130, fleches_defense=piege.get("fleches_defense",[]), orientation=orient)]], colWidths=[180, 180, 180])
            t_diags.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('BACKGROUND', (0,0), (-1,0), Config.COLOR_BG_LIGHT), ('BOX', (0,0), (-1,-1), 1, Config.COLOR_BORDER)]))
            elements.extend([KeepTogether([t_diags, Spacer(1, 15)]), Paragraph(f"<b>Idée :</b> {piege.get('conseil_defense', '')}", normal_style), Paragraph(f"<b>Défense :</b> {piege.get('coup_defense', '')} - {piege.get('explication_defense', '')}", normal_style)])

        footer = lambda c, d: PDFUtils.ajouter_pied_page(c, d, "Guide des 20 Pièges d'Ouverture")
        doc.build(elements, onFirstPage=footer, onLaterPages=footer)
        Logger.debug_log("PDF généré avec succès", "ESSENTIAL")
    finally:
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Génère le guide des pièges et défenses en PDF")
    parser.add_argument("--stockfish-depth", type=int, default=18, help="Profondeur Stockfish à utiliser")
    parser.add_argument("--verbose", nargs="?", const=1, default=0, type=int, help="Active les logs de debug détaillés avec un niveau optionnel (1 par défaut)")
    args = parser.parse_args()
    generer_pdf(stockfish_depth=args.stockfish_depth, verbose=args.verbose)
