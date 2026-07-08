import os
import sys
import json
import chess
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Ajoute le répertoire parent au chemin de recherche des modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importation depuis le nouveau dossier "classes"
from classes.config import Config
from classes.logger import Logger
from classes.chess_utils import ChessUtils
from classes.engines import OllamaManager
from classes.ai_analyzer import AIAnalyzer
from classes.pdf_components import ChessboardFlowable

def get_orientation(item):
    orientation = item.get("Orientation", "Blancs")
    return chess.BLACK if orientation.lower().startswith("n") else chess.WHITE

def generate_moves_table(item):
    coups_str = item.get("coups", "")
    moves = ChessUtils.parse_moves(coups_str)
    rows = []
    board = chess.Board()
    current_row = None
    
    for i, move in enumerate(moves):
        move_raw = move.get("raw", "")
        move_san = move.get("san", "")
        future_moves = [m.get("san", "") for m in moves[i+1:]]
        arrow_notation = None
        arrow_color = None
        
        commentaire, coup_annote = AIAnalyzer.generate_move_comment(move_raw, move_san, board, is_trap=False, future_moves=future_moves)
        
        try:
            move_obj = board.parse_san(move_san)
            is_capture = board.is_capture(move_obj)
            arrow_notation = chess.square_name(move_obj.from_square) + chess.square_name(move_obj.to_square)
            arrow_color = "#FF0000" if is_capture else "#00AA00"
            board.push(move_obj)
            fen_after = board.fen()
        except Exception:
            fen_after = board.fen()
        
        if move["color"] == "white":
            current_row = {
                "move_number": move["move_number"],
                "white": coup_annote,
                "white_comment": commentaire,
                "white_fen": fen_after,
                "white_arrow": arrow_notation,
                "white_arrow_color": arrow_color,
                "black": "", "black_comment": "", "black_fen": None, "black_arrow": None, "black_arrow_color": None
            }
            rows.append(current_row)
        else:
            if current_row is None or current_row["move_number"] != move["move_number"]:
                current_row = {
                    "move_number": move["move_number"],
                    "white": "", "white_comment": "", "white_fen": None, "white_arrow": None, "white_arrow_color": None,
                    "black": coup_annote, "black_comment": commentaire, "black_fen": fen_after,
                    "black_arrow": arrow_notation, "black_arrow_color": arrow_color
                }
                rows.append(current_row)
            else:
                current_row.update({"black": coup_annote, "black_comment": commentaire, "black_fen": fen_after, "black_arrow": arrow_notation, "black_arrow_color": arrow_color})
    return rows

def ajouter_pied_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(Config.COLOR_TEXT)
    canvas.drawString(36, 20, "Guide d'Ouvertures - Chess Docs")
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()

def build_pdf(output_path, source_name, data):
    Logger.debug_log(f"Début génération PDF ouvertures: {output_path}", "INFO")
    doc = SimpleDocTemplate(output_path, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, leading=26, textColor=Config.COLOR_PRIMARY, spaceAfter=15)
    intro_style = ParagraphStyle('Intro', parent=styles['Normal'], fontSize=11, leading=16, textColor=Config.COLOR_TEXT, spaceAfter=8)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=16, leading=20, textColor=Config.COLOR_PRIMARY, spaceAfter=10)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontSize=10, leading=14, textColor=Config.COLOR_TEXT)
    bold_style = ParagraphStyle('CustomBold', parent=normal_style, fontName='Helvetica-Bold')

    elements = []
    title_text = data[0].get('nom', source_name) if data else source_name
    elements.extend([
        Paragraph(f"Guide d'Ouvertures : {title_text}", title_style), Spacer(1, 10),
        Paragraph("Ce document présente chaque position d'ouverture, les coups clés et des commentaires pédagogiques générés par IA.", intro_style),
        Paragraph("Dernière mise à jour le " + datetime.now().strftime("%d/%m/%Y à %H:%M"), intro_style), Spacer(1, 15)
    ])

    for idx, item in enumerate(data):
        if idx > 0: elements.append(PageBreak())
        Logger.debug_log(f"Analyse de la variante {idx+1}/{len(data)} : {item.get('nom', 'Sans titre')}", "ESSENTIAL")
        elements.append(Paragraph(f"{idx + 1}. {item.get('nom', 'Sans titre')}", section_style))

        orientation = get_orientation(item)
        explications = item.get('explications', {})
        Logger.debug_log(f"Génération de la table de coups pour la variante {idx+1}", "INFO")
        rows = generate_moves_table(item)
        
        table_data = [[Paragraph("<b>Diag</b>", normal_style), Paragraph("<b>N°</b>", normal_style), Paragraph("<b>Blanc</b>", normal_style), Paragraph("<b>Noir</b>", normal_style), Paragraph("<b>Commentaire</b>", normal_style)]]
        
        for row in rows:
            fen_row = row.get('black_fen') or row.get('white_fen')
            fleches_defense, fleches_menace = [], []
            for arrow_notation, arrow_color in [(row.get('white_arrow'), row.get('white_arrow_color')), (row.get('black_arrow'), row.get('black_arrow_color'))]:
                if arrow_notation:
                    if arrow_color == "#FF0000": fleches_menace.append(arrow_notation)
                    else: fleches_defense.append(arrow_notation)
                    
            diag = ChessboardFlowable(fen_row, size=120, fleches_defense=fleches_defense, fleches_menace=fleches_menace, orientation=orientation) if fen_row else ""
            
            explication = explications.get(str(row.get('move_number', '')))
            parts = []
            if row.get('white_comment'): parts.append(f"<b>Blanc :</b> {row['white_comment']}")
            if row.get('black_comment'): parts.append(f"<b>Noir :</b> {row['black_comment']}")
            auto_comment = '<br/>'.join(parts)
            
            if explication:
                comment_text = f"<b>{explication}</b>"
                if auto_comment:
                    comment_text += f"<br/><br/><i>Analyse IA :</i><br/>{auto_comment}"
            else:
                comment_text = f"<i>Analyse IA :</i><br/>{auto_comment}"

            table_data.append([diag, Paragraph(str(row.get('move_number', '')), bold_style), Paragraph(row.get('white', ''), bold_style), Paragraph(row.get('black', ''), bold_style), Paragraph(comment_text, normal_style)])
            
        table = Table(table_data, colWidths=[130, 25, 50, 50, 285], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), Config.COLOR_PRIMARY), ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('VALIGN', (0,0), (-1,-1), 'TOP'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, Config.COLOR_BG_LIGHT]),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, Config.COLOR_BORDER), ('PADDING', (0,0), (-1,-1), 6)
        ]))
        elements.extend([table, Spacer(1, 12)])

    doc.build(elements, onFirstPage=ajouter_pied_page, onLaterPages=ajouter_pied_page)

def collect_source_files(base_dir):
    files = set()
    json_dir = os.path.join(base_dir, 'json')
    if os.path.isdir(json_dir):
        for filename in os.listdir(json_dir):
            if filename.lower().endswith('.json') and filename.lower().startswith('opening_'):
                files.add(os.path.join(json_dir, filename))
    return sorted(files)

def main(stockfish_depth=18, verbose=1, opening=None):
    enabled, level = (True, max(int(verbose), 1)) if verbose else (False, 0)
    Logger.set_debug_enabled(enabled, level=level)
    Logger.debug_log("=== Début de la génération des guides d'ouvertures ===", "ESSENTIAL")
    Logger.debug_log(f"Profondeur Stockfish retenue : {ChessUtils.resolve_stockfish_depth(stockfish_depth)}", "ESSENTIAL")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sources = collect_source_files(base_dir)
    if opening:
        sources = [os.path.join(base_dir, f'json/{opening}.json')]
    Logger.debug_log(f"Sources JSON découvertes: {len(sources)}", "INFO")
    if not sources:
        Logger.debug_log("Aucun fichier JSON trouvé.", "ERROR")
        return
        
    ollama = OllamaManager()
    ollama.start()
    
    try:
        for source_path in sources:
            try:
                with open(source_path, 'r', encoding='utf-8') as f: data = json.load(f)
                if not isinstance(data, list): continue
                output_path = os.path.join(base_dir, f"guide_{os.path.splitext(os.path.basename(source_path))[0]}.pdf")
                Logger.debug_log(f"Traitement du fichier source {source_path}", "INFO")
                Logger.debug_log(f"==== Génération de {output_path} ====", "ESSENTIAL")
                build_pdf(output_path, os.path.basename(source_path), data)
            except Exception as exc: 
                Logger.debug_log(f"Impossible de traiter {source_path}: {exc}", "ERROR")
        Logger.debug_log("Génération terminée.", "ESSENTIAL")
    finally:
        ollama.stop()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Génère les guides d'ouvertures en PDF")
    parser.add_argument("--stockfish-depth", type=int, default=18, help="Profondeur Stockfish à utiliser")
    parser.add_argument("--verbose", nargs="?", const=1, default=0, type=int, help="Active les logs de debug détaillés avec un niveau optionnel (1 par défaut)")
    parser.add_argument("--opening", type=str, help="Ouverture spécifique à générer (par exemple: 'fried_liever_attack')")
    args = parser.parse_args()
    main(stockfish_depth=args.stockfish_depth, verbose=args.verbose, opening=args.opening)