import os
import re
import json
import chess
import chess.svg
from datetime import datetime
from io import StringIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable, KeepTogether, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

# =====================================================================
# COULEURS
# =====================================================================
COLOR_PRIMARY = colors.HexColor("#1e293b")
COLOR_SECONDARY = colors.HexColor("#0284c7")
COLOR_TEXT = colors.HexColor("#334155")
COLOR_BG_LIGHT = colors.HexColor("#f8fafc")
COLOR_BORDER = colors.HexColor("#e2e8f0")
COLOR_MINT = colors.HexColor("#0f766e")


class ChessboardFlowable(Flowable):
    def __init__(self, fen, size=150, fleches_defense=None, fleches_menace=None, orientation=chess.WHITE):
        Flowable.__init__(self)
        self.fen = fen
        self.size = size
        self.fleches_defense = fleches_defense or []
        self.fleches_menace = fleches_menace or []
        self.orientation = orientation

    def wrap(self, availWidth, availHeight):
        return self.size, self.size

    def draw(self):
        board = chess.Board(self.fen)
        arrows = []
        for notation in self.fleches_menace:
            arrows.append(chess.svg.Arrow(
                chess.parse_square(notation[:2]),
                chess.parse_square(notation[2:]),
                color="#FF0000"
            ))
        for notation in self.fleches_defense:
            arrows.append(chess.svg.Arrow(
                chess.parse_square(notation[:2]),
                chess.parse_square(notation[2:]),
                color="#00AA00"
            ))
        svg = chess.svg.board(board=board, size=self.size, arrows=arrows, orientation=self.orientation)
        drawing = svg2rlg(StringIO(svg))
        renderPDF.draw(drawing, self.canv, 0, 0)


def convert_french_to_english_notation(move):
    piece_map = {
        'D': 'Q',
        'C': 'N',
        'F': 'B',
        'T': 'R',
        'R': 'K',
    }
    if '=' in move:
        parts = move.split('=')
        if len(parts) == 2 and parts[1] in piece_map:
            move = parts[0] + '=' + piece_map[parts[1]]
    if move and move[0] in piece_map and '=' not in move[:move.find('=') if '=' in move else len(move)]:
        move = piece_map[move[0]] + move[1:]
    return move


def parse_moves(coups_str):
    pattern = r'(\d+)\.\s*([^\s]+)(?:\s+([^\s]+))?'
    matches = re.findall(pattern, coups_str)
    moves = []
    for num, white, black in matches:
        white_raw = white.strip()
        white_san = convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', white_raw))
        moves.append({"raw": white_raw, "san": white_san, "move_number": int(num), "color": "white"})
        if black:
            black_raw = black.strip()
            black_san = convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', black_raw))
            moves.append({"raw": black_raw, "san": black_san, "move_number": int(num), "color": "black"})
    return moves


def generate_move_comment(move_raw, move_san, board):
    raw = move_raw.strip()
    raw_clean = re.sub(r'[?!+#]+', '', raw)
    if "??" in raw:
        return "Erreur grave, c'est une gaffe."
    if "?!" in raw:
        return "Coup douteux. Les réponses existent."
    if "!?" in raw:
        return "Coup intéressant mais potentiellement risqué."
    if "!!" in raw:
        return "Coup exceptionnel, une trouvaille brillante."
    if "?" in raw:
        return "Coup douteux ou erreur, soyez vigilant."
    if "!" in raw:
        return "Coup fort, bonne découverte tactique."
    if "#" in raw:
        return "Mat direct, la combinaison fonctionne."
    if "+" in raw:
        return "Donne échec et met la pression sur le roi."
    if "x" in raw_clean:
        return "Capture une pièce ou un pion, souvent au cœur de la lutte."
    if raw_clean.startswith("D"):
        return "Développe la Dame pour maintenir l'initiative."
    if raw_clean.startswith("C"):
        return "Développe le Cavalier vers une case active."
    if raw_clean.startswith("F"):
        return "Développe le Fou et cible le centre ou les cases faibles."
    if raw_clean.startswith("T"):
        return "Développe la Tour, souvent après l'ouverture du jeu."
    if raw_clean.startswith("R"):
        return "Sécurise le Roi ou prépare la défense."
    if raw_clean in ["e4", "d4", "e5", "d5"]:
        return "Prend le contrôle du centre."
    if raw_clean and raw_clean[0] in "abcdefgh":
        return "Avance un pion pour ouvrir le jeu ou soutenir le centre."
    if board.is_check():
        return "Ce coup donne échec et met la pression sur l'adversaire."
    return "Coup de développement utile dans cette position."


def get_orientation(item):
    orientation = item.get("Orientation", "Blancs")
    return chess.BLACK if orientation.lower().startswith("n") else chess.WHITE


def generate_moves(item):
    coups_str = item.get("coups", "")
    moves = parse_moves(coups_str)
    rows = []
    board = chess.Board()
    current_row = None
    for move in moves:
        move_raw = move.get("raw", "")
        move_san = move.get("san", "")
        try:
            board.push(board.parse_san(move_san))
            fen_after = board.fen()
        except Exception:
            fen_after = board.fen()
        commentaire = generate_move_comment(move_raw, move_san, board)
        if move["color"] == "white":
            current_row = {
                "move_number": move["move_number"],
                "white": move_raw,
                "white_comment": commentaire,
                "white_fen": fen_after,
                "black": "",
                "black_comment": "",
                "black_fen": None
            }
            rows.append(current_row)
        else:
            if current_row is None or current_row["move_number"] != move["move_number"]:
                current_row = {
                    "move_number": move["move_number"],
                    "white": "",
                    "white_comment": "",
                    "white_fen": None,
                    "black": move_raw,
                    "black_comment": commentaire,
                    "black_fen": fen_after
                }
                rows.append(current_row)
            else:
                current_row["black"] = move_raw
                current_row["black_comment"] = commentaire
                current_row["black_fen"] = fen_after
    return rows


def generate_fen_positions(item):
    coups_str = item.get("coups", "")
    moves = parse_moves(coups_str)
    board = chess.Board()
    positions = []
    for move in moves:
        try:
            board.push(board.parse_san(move["san"]))
            positions.append(board.fen())
        except Exception:
            positions.append(None)
    return positions


def ajouter_pied_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(COLOR_TEXT)
    canvas.drawString(36, 20, "Guide d'Ouvertures - Chess Docs")
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(output_path, source_name, data):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=40,
        bottomMargin=40
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, leading=26, textColor=COLOR_PRIMARY, spaceAfter=15)
    intro_style = ParagraphStyle('Intro', parent=styles['Normal'], fontSize=11, leading=16, textColor=COLOR_TEXT, spaceAfter=8)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=16, leading=20, textColor=COLOR_PRIMARY, spaceAfter=10)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontSize=10, leading=14, textColor=COLOR_TEXT)
    bold_style = ParagraphStyle('CustomBold', parent=normal_style, fontName='Helvetica-Bold')

    elements = []
    title_text = data[0].get('nom', source_name) if data else source_name
    elements.append(Paragraph(f"Guide d'Ouvertures : {title_text}", title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("Ce document présente chaque position d'ouverture, les coups clés et des commentaires pédagogiques pour comprendre la séquence.", intro_style))
    elements.append(Paragraph("Toutes les données sont extraites du fichier JSON correspondant.", intro_style))
    elements.append(Paragraph("Dernière mise à jour le " + datetime.now().strftime("%d/%m/%Y à %H:%M"), intro_style))
    elements.append(Spacer(1, 15))

    legend_data = [
        [Paragraph("<b>Section</b>", normal_style), Paragraph("<b>Description</b>", normal_style)],
        [Paragraph("Diagramme", bold_style), Paragraph("Position après chaque coup pour visualiser l'évolution du point clé.", normal_style)],
        [Paragraph("Table des coups", bold_style), Paragraph("Coup blanc/noir avec commentaires fusionnés et explications JSON.", normal_style)],
        [Paragraph("Explications", bold_style), Paragraph("Commentaires supplémentaires intégrés dans la même case que le commentaire pédagogique.", normal_style)]
    ]
    legend_table = Table(legend_data, colWidths=[120, 420])
    legend_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), COLOR_BG_LIGHT),
        ('LINEBELOW', (0,0), (-1,0), 1, COLOR_PRIMARY),
        ('LINEBELOW', (0,1), (-1,-1), 0.5, COLOR_BORDER),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5)
    ]))
    elements.append(legend_table)
    elements.append(PageBreak())

    for idx, item in enumerate(data):
        if idx > 0:
            elements.append(PageBreak())

        elements.append(Paragraph(f"{idx + 1}. {item.get('nom', 'Sans titre')}", section_style))

        orientation = get_orientation(item)
        explications = item.get('explications', {}) if isinstance(item.get('explications', {}), dict) else {}

        rows = generate_moves(item)
        table_data = [[
            Paragraph("<b>Diag</b>", normal_style),
            Paragraph("<b>N°</b>", normal_style),
            Paragraph("<b>Blanc</b>", normal_style),
            Paragraph("<b>Noir</b>", normal_style),
            Paragraph("<b>Commentaire</b>", normal_style)
        ]]
        for row in rows:
            fen_row = row.get('black_fen') or row.get('white_fen')
            diag = ChessboardFlowable(fen_row, size=80, orientation=orientation) if fen_row else ""
            comment_parts = []
            if row.get('white_comment'):
                comment_parts.append(f"<b>Blanc :</b> {row['white_comment']}")
            if row.get('black_comment'):
                comment_parts.append(f"<b>Noir :</b> {row['black_comment']}")
            explication = explications.get(str(row.get('move_number', '')))
            if explication:
                comment_parts.append(f"<b>{explication}</b>")
            comment_text = '<br/>'.join(comment_parts) if comment_parts else ''
            table_data.append([
                diag,
                Paragraph(str(row.get('move_number', '')), bold_style),
                Paragraph(row.get('white', ''), bold_style),
                Paragraph(row.get('black', ''), bold_style),
                Paragraph(comment_text, normal_style)
            ])
        table = Table(table_data, colWidths=[90, 30, 100, 100, 220], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), COLOR_PRIMARY),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, COLOR_BG_LIGHT]),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, COLOR_BORDER),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))

    doc.build(elements, onFirstPage=ajouter_pied_page, onLaterPages=ajouter_pied_page)


def collect_source_files(base_dir):
    files = set()
    json_dir = os.path.join(base_dir, 'json')
    if os.path.isdir(json_dir):
        for filename in os.listdir(json_dir):
            lower = filename.lower()
            if lower.endswith('.json') and lower.startswith('opening_'):
                files.add(os.path.join(json_dir, filename))
    for root, _, filenames in os.walk(base_dir):
        for filename in filenames:
            lower = filename.lower()
            if lower.endswith('.json') and lower.startswith('opening_'):
                files.add(os.path.join(root, filename))
    return sorted(files)


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sources = collect_source_files(base_dir)
    if not sources:
        print('Aucun fichier JSON trouvé à traiter.')
        return
    for source_path in sources:
        try:
            with open(source_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as exc:
            print(f"Impossible de lire {source_path}: {exc}")
            continue
        if not isinstance(data, list):
            print(f"Le fichier {source_path} doit contenir une liste JSON.")
            continue
        output_name = f"guide_{os.path.splitext(os.path.basename(source_path))[0]}.pdf"
        output_path = os.path.join(base_dir, output_name)
        print(f"Génération de {output_path} à partir de {source_path}")
        build_pdf(output_path, os.path.basename(source_path), data)
    print('Génération terminée.')


if __name__ == '__main__':
    main()
