import math
import chess
import chess.svg
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable, KeepTogether, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from io import StringIO
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF
import re
import json

# =====================================================================
# CHESSBOARD FLOWABLE
# =====================================================================
class ChessboardFlowable(Flowable):
    def __init__(self, fen, size=150, fleches_defense=None, fleches_menace=None):
        Flowable.__init__(self)
        self.fen = fen
        self.size = size
        self.fleches_defense = fleches_defense or []
        self.fleches_menace = fleches_menace or []

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

        svg = chess.svg.board(board=board, size=self.size, arrows=arrows)
        drawing = svg2rlg(StringIO(svg))
        renderPDF.draw(drawing, self.canv, 0, 0)


# =====================================================================
# ANALYSE INTELLIGENTE
# =====================================================================

def detect_theme(coup):
    if "xf7" in coup:
        return "Attaque sur f7 (point faible clé)."
    if "xh7" in coup:
        return "Attaque sur h7 (roi exposé)."
    if "D" in coup and ("h5" in coup or "h4" in coup):
        return "Sortie agressive de la Dame."
    if "C" in coup and ("d6" in coup or "e5" in coup):
        return "Cavalier en avant-poste."
    return ""


def classify_trap(piege):
    coups = piege["coups"]
    if "#" in coups:
        return "Mat"
    if "x" in coups:
        return "Gain matériel"
    return "Tactique"


def estimate_difficulty(piege):
    coups = piege["coups"]
    if "??" in coups:
        return "Facile"
    if "!" in coups:
        return "Intermédiaire"
    return "Avancé"


def analyze_position(fen):
    board = chess.Board(fen)
    attackers = list(board.attackers(not board.turn, board.king(board.turn)))
    if attackers:
        return "Le roi est en danger immédiat."
    return "Position relativement sûre."


# =====================================================================
# GENERATION DES COUPS COMMENTÉS
# =====================================================================

def generate_moves(piege):
    raw = piege.get("coups", "")
    pattern = r"(\d+)\.\s*([^\s]+)(?:\s+([^\s]+))?"
    matches = re.finditer(pattern, raw)

    lines = []

    def commenter(coup):
        if "#" in coup:
            return "Mat immédiat."
        if "+" in coup:
            return "Échec."
        if "??" in coup:
            return "Erreur critique."
        if "!" in coup:
            return "Très bon coup."
        if coup in ["e4", "d4"]:
            return "Contrôle du centre."
        if coup.startswith("C"):
            return "Développement du cavalier."
        if coup.startswith("F"):
            return "Développement du fou."
        if coup.startswith("D"):
            return "Sortie de la Dame."
        if "x" in coup:
            return "Capture."
        return "Développement."

    for match in matches:
        num, w, b = match.groups()

        lines.append({"coup": f"{num}. {w}", "commentaire": commenter(w)})
        if b:
            lines.append({"coup": f"{num}... {b}", "commentaire": commenter(b)})

    # Ajouts pédagogiques
    lines.append({"coup": "Thème", "commentaire": classify_trap(piege)})
    lines.append({"coup": "Difficulté", "commentaire": estimate_difficulty(piege)})
    lines.append({"coup": "Idée", "commentaire": piege["conseil_defense"]})
    lines.append({"coup": "Défense", "commentaire": piege["coup_defense"]})

    return lines


# =====================================================================
# 2. BASE DE DONNÉES DES 20 PIÈGES 
# =====================================================================
with open('json/trappes_data.json', 'r', encoding='utf-8') as f:
    trappes_data = json.load(f)


# =====================================================================
# PDF
# =====================================================================

def generer_pdf():
    doc = SimpleDocTemplate("guide_20_pieges_et_defenses.pdf", pagesize=letter)
    styles = getSampleStyleSheet()

    # Custom styles for a more cheerful presentation
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, textColor=colors.darkblue, spaceAfter=12)
    intro_style = ParagraphStyle('Intro', parent=styles['Normal'], fontSize=12, textColor=colors.black, spaceAfter=6)
    legend_heading_style = ParagraphStyle('LegendHeading', parent=styles['Heading2'], fontSize=14, textColor=colors.darkgreen, spaceAfter=6)
    trap_heading_style = ParagraphStyle('TrapHeading', parent=styles['Heading2'], fontSize=14, textColor=colors.darkblue, spaceAfter=6)
    conclusion_style = ParagraphStyle('Conclusion', parent=styles['Heading1'], fontSize=16, textColor=colors.darkred, spaceAfter=8)
    normal_style = styles['Normal']

    elements = []

    # Introduction
    elements.append(Paragraph("Guide des 20 Pièges d'Ouverture", title_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("Niveau : ~650 Elo. Ce guide met l'accent sur la détection des menaces tactiques, la compréhension des plans et l'apprentissage des réponses solides.", intro_style))
    elements.append(Paragraph("L'objectif est de renforcer la vigilance sur les cases faibles (f7/h7), la sécurité du roi, et la gestion des pièges suivants.", intro_style))
    elements.append(Spacer(1, 12))

    # Légende globale
    elements.append(Paragraph("Légende Globale", legend_heading_style))
    elements.append(Spacer(1, 6))
    legend_data = [
        ["Section", "Description"],
        ["Diagrammes", Paragraph("1) Alerte : Position finale avec flèches rouges indiquant les menaces.", normal_style)],
        ["", Paragraph("2) Idée du piège : Position intermédiaire montrant l'idée tactique (flèches rouges pour menaces, vertes pour défenses possibles).", normal_style)],
        ["", Paragraph("3) Défense correcte : Position après la défense avec flèches vertes pour les coups défensifs.", normal_style)],
        ["Table des coups", Paragraph("Liste des coups avec commentaires pédagogiques pour comprendre la séquence.", normal_style)],
        ["Type/Difficulté", Paragraph("Classification du piège et niveau de difficulté estimé.", normal_style)],
        ["Idée/Défense", Paragraph("Explication de l'idée derrière le piège et la réponse recommandée.", normal_style)]
    ]
    legend_table = Table(legend_data, colWidths=[140, 400])
    legend_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,0), (-1,0), colors.lightcyan),
        ('BACKGROUND', (0,1), (-1,-1), colors.lightyellow),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3)
    ]))
    elements.append(legend_table)
    elements.append(Spacer(1, 12))
    elements.append(PageBreak())

    for idx, piege in enumerate(trappes_data):
        if idx > 0:
            elements.append(PageBreak())
        elements.append(Paragraph(piege["nom"], trap_heading_style))

        # =========================
        # ANALYSE POSITION
        # =========================
        analyse = analyze_position(piege["fen_final"])
        elements.append(Paragraph(f"Analyse : {analyse}", styles["Normal"]))

        # =========================
        # INFOS STRATEGIQUES (au début de chaque piège)
        # =========================
        type_piege = classify_trap(piege)
        difficulte = estimate_difficulty(piege)

        elements.append(Paragraph(f"Type : {type_piege}", styles["Normal"]))
        elements.append(Paragraph(f"Difficulté : {difficulte}", styles["Normal"]))
        elements.append(Spacer(1, 8))

        # =========================
        # TABLE DES COUPS (format 4 colonnes)
        # =========================
        full_moves = [m for m in piege.get("moves", []) if m["coup"] not in ["Thème", "Difficulté", "Idée", "Défense"]]

        table_data = [["Coup blanc", "Commentaire", "Coup noir", "Commentaire"]]
        for i in range(0, len(full_moves), 2):
            blanc = full_moves[i]
            noir = full_moves[i+1] if i+1 < len(full_moves) else {"coup": "", "commentaire": ""}
            table_data.append([
                blanc.get("coup", ""), blanc.get("commentaire", ""),
                noir.get("coup", ""), noir.get("commentaire", "")
            ])

        table = Table(table_data, colWidths=[100, 160, 100, 160], repeatRows=1)
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
            ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
            ('BACKGROUND', (0,1), (-1,-1), colors.whitesmoke),
            ('VALIGN', (0,0), (-1,-1), 'TOP')
        ]))

        elements.append(KeepTogether([table, Spacer(1, 10)]))

        # =========================
        # 🔥 TES 3 DIAGRAMMES RESTAURÉS
        # =========================

        fen_inter = piege.get("fen_intermediaire", piege["fen_defense"])

        diag_alerte = ChessboardFlowable(
            piege["fen_final"],
            size=130,
            fleches_menace=piege.get("fleches_menace", [])
        )

        diag_inter = ChessboardFlowable(
            fen_inter,
            size=130,
            fleches_menace=piege.get("fleches_menace", []),
            fleches_defense=piege.get("fleches_defense", [])
        )

        diag_defense = ChessboardFlowable(
            piege["fen_defense"],
            size=130,
            fleches_defense=piege.get("fleches_defense", [])
        )

        table_diags = Table([
            ["1) Alerte", "2) Idée du piège", "3) Défense correcte"],
            [diag_alerte, diag_inter, diag_defense]
        ], colWidths=[170, 170, 170], repeatRows=1)
        table_diags.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (-1,0), colors.lightgreen),
            ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey)
        ]))

        elements.append(KeepTogether([table_diags, Spacer(1, 10)]))

        # =========================
        # IDEA + DEFENSE (APRES les diagrammes)
        # =========================
        elements.append(Paragraph(f"Idée : {piege.get('conseil_defense', '')}", styles['Normal']))
        elements.append(Paragraph(f"Défense : {piege.get('coup_defense', '')}", styles['Normal']))
        elements.append(Spacer(1, 12))

    # Conclusion
    elements.append(PageBreak())
    elements.append(Paragraph("Conclusion", conclusion_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("Entraînez-vous à repérer ces schémas dès l'ouverture et analysez les options de défense avant votre prochain coup.", normal_style))
    elements.append(Paragraph("À 650 Elo, l'objectif est d'automatiser l'alerte : si une pièce est menacée ou si un pion faible apparaît, prenez un moment pour vérifier la position complète.", normal_style))
    elements.append(Paragraph("Révisez ces 20 pièges régulièrement, et vous transformerez ces erreurs adverses en victoire facilement.", normal_style))

    doc.build(elements)


if __name__ == "__main__":
    generer_pdf()
