import os
import re
import json
import chess
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Import depuis notre librairie commune
from chess_lib import (
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_TEXT, COLOR_BG_LIGHT, COLOR_BORDER, COLOR_MINT,
    ChessboardFlowable, parse_moves, generate_move_comment, convert_french_to_english_notation
)

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

def validate_fen(fen, trap_name=""):
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

def generate_moves_table(piege):
    moves = parse_moves(piege.get("coups", ""))
    rows, board, current_row = [], chess.Board(), None

    for move in moves:
        move_san = move.get("san", "")
        commentaire = generate_move_comment(move.get("raw", ""), move_san, board, is_trap=True)
        try: board.push(board.parse_san(move_san))
        except Exception: pass
        fen_after = board.fen()

        if move.get("color") == "white":
            current_row = {"move_number": move["move_number"], "white": move["raw"], "white_comment": commentaire, "white_fen": fen_after, "black": "", "black_comment": "", "black_fen": None}
            rows.append(current_row)
        else:
            if not current_row or current_row["move_number"] != move["move_number"]:
                current_row = {"move_number": move["move_number"], "white": "", "white_comment": "", "white_fen": None, "black": move["raw"], "black_comment": commentaire, "black_fen": fen_after}
                rows.append(current_row)
            else:
                current_row.update({"black": move["raw"], "black_comment": commentaire, "black_fen": fen_after})
    return rows

def generate_fen_positions(piege):
    moves = parse_moves(piege.get("coups", ""))
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
        index = 2 * (defense_order - 1) if piege.get("defenseur") == "Noirs" else 2 * defense_order - 3
        fen_intermediaire = positions[index] if 0 <= index < len(positions) else positions[-2]
    else:
        fen_intermediaire = positions[-3] if len(positions) >= 3 else positions[-2]

    fen_defense = fen_intermediaire
    if len(defense_options) == 1:
        try:
            board_def = chess.Board(fen_intermediaire)
            board_def.push(board_def.parse_san(convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', defense_options[0]))))
            fen_defense = board_def.fen()
        except Exception: pass

    return fen_final, fen_intermediaire, fen_defense

def ajouter_pied_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(COLOR_TEXT)
    canvas.drawString(36, 20, "Guide des 20 Pièges d'Ouverture")
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()

def generer_pdf():
    print("="*70)
    print("🔄 Génération du guide des pièges d'ouverture...")
    
    with open('../json/trappes_data.json', 'r', encoding='utf-8') as f: trappes_data = json.load(f)
        
    doc = SimpleDocTemplate("../guide_pieges_et_defenses.pdf", pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, leading=26, textColor=COLOR_PRIMARY, spaceAfter=15)
    intro_style = ParagraphStyle('Intro', parent=styles['Normal'], fontSize=11, leading=16, textColor=COLOR_TEXT, spaceAfter=8)
    legend_heading = ParagraphStyle('LegendHeading', parent=styles['Heading2'], fontSize=14, leading=18, textColor=COLOR_MINT, spaceAfter=10)
    trap_heading = ParagraphStyle('TrapHeading', parent=styles['Heading2'], fontSize=16, leading=20, textColor=COLOR_PRIMARY, spaceAfter=8)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontSize=10, leading=14, textColor=COLOR_TEXT)
    bold_style = ParagraphStyle('CustomBold', parent=normal_style, fontName='Helvetica-Bold')

    elements = [
        Paragraph("Guide des Pièges d'Ouverture", title_style), Spacer(1, 10),
        Paragraph("Ce guide met l'accent sur la détection des menaces tactiques.", intro_style),
        Paragraph("Dernière mise à jour le " + datetime.now().strftime("%d/%m/%Y à %H:%M"), intro_style), Spacer(1, 15),
        Paragraph("Légende Globale", legend_heading), Spacer(1, 5)
    ]
    
    legend_table = Table([
        [Paragraph("<b>Section</b>", normal_style), Paragraph("<b>Description</b>", normal_style)],
        [Paragraph("Diagrammes", bold_style), Paragraph("Position finale, intermédiaire de détection, et défense.", normal_style)],
        [Paragraph("Table des coups", bold_style), Paragraph("Coups avec commentaires analytiques.", normal_style)]
    ], colWidths=[120, 420])
    legend_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), COLOR_BG_LIGHT), ('LINEBELOW', (0,0), (-1,0), 1, COLOR_PRIMARY), ('PADDING', (0,0), (-1,-1), 6)]))
    elements.extend([legend_table, PageBreak()])

    for idx, piege in enumerate(trappes_data):
        if idx > 0: elements.append(PageBreak())
        
        # Le log ajouté ici pour le suivi dans la console !
        print(f"[INFO] Analyse du piège d'ouverture {idx+1}/{len(trappes_data)} : {piege.get('nom', 'Sans nom')}")
        
        bloc = [Paragraph(f"{idx+1}. {piege['nom']}", trap_heading)]
        fen_final, fen_inter, fen_def = generate_fen_positions(piege)
        
        if not fen_final or not validate_fen(fen_final): continue
        
        meta = f"<b>Analyse :</b> {analyze_position(fen_final)} | <b>Type :</b> {classify_trap(piege)} | <b>Difficulté :</b> {estimate_difficulty(piege)}"
        bloc.extend([Paragraph(meta, normal_style), Spacer(1, 10)])

        table_data = [[Paragraph("<b>Diag</b>", normal_style), Paragraph("<b>Blanc</b>", normal_style), Paragraph("<b>Commentaire</b>", normal_style), Paragraph("<b>Noir</b>", normal_style), Paragraph("<b>Commentaire</b>", normal_style)]]
        orient = get_trap_orientation(piege)
        
        for row in generate_moves_table(piege):
            fen = row.get("black_fen") or row.get("white_fen")
            diag = ChessboardFlowable(fen, size=105, orientation=orient) if fen else ""
            table_data.append([diag, Paragraph(row.get("white",""), bold_style), Paragraph(row.get("white_comment",""), normal_style), Paragraph(row.get("black",""), bold_style), Paragraph(row.get("black_comment",""), normal_style)])

        t_coups = Table(table_data, colWidths=[120, 45, 145, 45, 145], repeatRows=1)
        t_coups.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), COLOR_PRIMARY), ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, COLOR_BG_LIGHT]), ('PADDING', (0,0), (-1,-1), 6), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
        bloc.append(t_coups)
        elements.extend([KeepTogether(bloc), Spacer(1, 15)])

        t_diags = Table([[Paragraph("<b>1) Piège</b>", normal_style), Paragraph("<b>2) Détection</b>", normal_style), Paragraph("<b>3) Défense</b>", normal_style)],
                         [ChessboardFlowable(fen_final, 130, fleches_menace=piege.get("fleches_menace",[]), orientation=orient),
                          ChessboardFlowable(fen_inter, 130, fleches_menace=piege.get("fleches_menace",[]), orientation=orient),
                          ChessboardFlowable(fen_def, 130, fleches_defense=piege.get("fleches_defense",[]), orientation=orient)]], colWidths=[180, 180, 180])
        t_diags.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('BACKGROUND', (0,0), (-1,0), COLOR_BG_LIGHT), ('BOX', (0,0), (-1,-1), 1, COLOR_BORDER)]))
        elements.extend([KeepTogether([t_diags, Spacer(1, 15)]), Paragraph(f"<b>Idée :</b> {piege.get('conseil_defense', '')}", normal_style), Paragraph(f"<b>Défense :</b> {piege.get('coup_defense', '')} - {piege.get('explication_defense', '')}", normal_style)])

    doc.build(elements, onFirstPage=ajouter_pied_page, onLaterPages=ajouter_pied_page)
    print("✅ PDF généré avec succès")

if __name__ == "__main__":
    generer_pdf()
