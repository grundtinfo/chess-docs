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
# PALETTE DE COULEURS (Charte Graphique Moderne)
# =====================================================================
COLOR_PRIMARY = colors.HexColor("#1e293b")    # Ardoise foncé (Titres et entêtes)
COLOR_SECONDARY = colors.HexColor("#0284c7")  # Bleu ciel profond (Accents et diagrammes)
COLOR_TEXT = colors.HexColor("#334155")       # Ardoise neutre (Texte normal)
COLOR_BG_LIGHT = colors.HexColor("#f8fafc")   # Fond très clair (Alternance lignes)
COLOR_BORDER = colors.HexColor("#e2e8f0")     # Lignes de séparation discrètes
COLOR_MINT = colors.HexColor("#0f766e")       # Menthe (Pour les succès ou la défense)

# =====================================================================
# CHESSBOARD FLOWABLE (Inchangé pour ne pas casser tes diagrammes)
# =====================================================================
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


# =====================================================================
# ANALYSE INTELLIGENTE (Logique conservée)
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

def get_trap_orientation(piege):
    defenseur = piege.get("defenseur")
    if defenseur == "Blancs":
        return chess.WHITE
    else:
        return chess.BLACK

def generate_moves(piege):
    """Génère dynamiquement la liste des coups avec commentaires à partir du champ 'coups'."""
    raw = piege.get("coups", "")
    pattern = r"(\d+)\.\s*([^\s]+)(?:\s+([^\s]+))?"
    matches = re.finditer(pattern, raw)

    lines = []

    def commenter(coup):
        """Génère un commentaire intelligent pour chaque coup."""
        if "#" in coup:
            return "Mat immédiat."
        if "+" in coup:
            return "Échec."
        if "??" in coup:
            return "Erreur grossière."
        if "?!" in coup:
            return "Coup douteux."
        if "?" in coup and "!" not in coup:
            return "Coup imprécis."
        if "!" in coup and "?" not in coup:
            return "Très bon coup."
        if coup in ["e4", "d4"]:
            return "Contrôle du centre."
        if coup.startswith("C"):
            return "Développement du cavalier."
        if coup.startswith("F"):
            return "Développement du fou."
        if coup.startswith("D"):
            return "Sortie de la Dame."
        if coup.startswith("T"):
            return "Mouvement de tour."
        if "x" in coup:
            return "Capture."
        if coup.endswith("=D") or coup.endswith("=C") or coup.endswith("=F") or coup.endswith("=T"):
            return "Promotion."
        return "Développement."

    for match in matches:
        num, w, b = match.groups()

        lines.append({"coup": f"{num}. {w}", "commentaire": commenter(w)})
        if b:
            lines.append({"coup": f"{num}... {b}", "commentaire": commenter(b)})

    return lines


# =====================================================================
# FONCTION POUR LE PIED DE PAGE (Numérotation)
# =====================================================================
def ajouter_pied_page(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(COLOR_TEXT)
    # Gauche : Titre du guide
    canvas.drawString(36, 20, "Guide des 20 Pièges d'Ouverture")
    # Droite : Numéro de page
    canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
    canvas.restoreState()


# =====================================================================
# BASE DE DONNÉES DES 20 PIÈGES 
# =====================================================================
with open('json/trappes_data.json', 'r', encoding='utf-8') as f:
    trappes_data = json.load(f)


# =====================================================================
# PDF
# =====================================================================
def generer_pdf():
    # Définition des marges à 36 points (0.5 pouce) pour plus d'espace
    doc = SimpleDocTemplate(
        "guide_20_pieges_et_defenses.pdf", 
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=40,
        bottomMargin=40
    )
    styles = getSampleStyleSheet()

    # Styles personnalisés et aérés
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, leading=26, textColor=COLOR_PRIMARY, spaceAfter=15)
    intro_style = ParagraphStyle('Intro', parent=styles['Normal'], fontSize=11, leading=16, textColor=COLOR_TEXT, spaceAfter=8)
    legend_heading_style = ParagraphStyle('LegendHeading', parent=styles['Heading2'], fontSize=14, leading=18, textColor=COLOR_MINT, spaceAfter=10)
    trap_heading_style = ParagraphStyle('TrapHeading', parent=styles['Heading2'], fontSize=16, leading=20, textColor=COLOR_PRIMARY, spaceAfter=8)
    conclusion_style = ParagraphStyle('Conclusion', parent=styles['Heading1'], fontSize=18, leading=22, textColor=COLOR_PRIMARY, spaceAfter=10)
    
    # Style normal avec un bon interlignage pour éviter que les lignes se touchent
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontSize=10, leading=14, textColor=COLOR_TEXT)
    bold_style = ParagraphStyle('CustomBold', parent=normal_style, fontName='Helvetica-Bold')

    elements = []

    # 1. Introduction
    elements.append(Paragraph("Guide des 20 Pièges d'Ouverture", title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<b>Niveau :</b> ~650 Elo. Ce guide met l'accent sur la détection des menaces tactiques, la compréhension des plans et l'apprentissage des réponses solides.", intro_style))
    elements.append(Paragraph("L'objectif est de renforcer la vigilance sur les cases faibles (f7/h7), la sécurité du roi, et la gestion des pièges d'ouverture.", intro_style))
    elements.append(Spacer(1, 15))

    # 2. Légende globale
    elements.append(Paragraph("Légende Globale", legend_heading_style))
    elements.append(Spacer(1, 5))
    legend_data = [
        [Paragraph("<b>Section</b>", normal_style), Paragraph("<b>Description</b>", normal_style)],
        [Paragraph("Diagrammes", bold_style), Paragraph("1) <b>Piégé :</b> Position finale où la menace aboutit (mat ou gain matériel).", normal_style)],
        ["", Paragraph("2) <b>Détection :</b> Position intermédiaire où la menace est reconnaissable le plus tôt possible, avec flèches rouges pour les menaces.", normal_style)],
        ["", Paragraph("3) <b>Défense correcte :</b> Position après la défense correcte, avec flèches vertes indiquant les mouvements défensifs.", normal_style)],
        [Paragraph("Table des coups", bold_style), Paragraph("Liste des coups avec commentaires pédagogiques pour comprendre la séquence.", normal_style)],
        [Paragraph("Type/Difficulté", bold_style), Paragraph("Classification du piège et niveau de difficulté estimé.", normal_style)],
        [Paragraph("Idée/Défense", bold_style), Paragraph("Explication de l'idée derrière le piège et la réponse recommandée.", normal_style)]
    ]
    
    # Largeur ajustée aux nouvelles marges (total 540)
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

    # 3. Parcours des pièges
    for idx, piege in enumerate(trappes_data):
        if idx > 0:
            elements.append(PageBreak())
        
        elements.append(Paragraph(f"{idx+1}. {piege['nom']}", trap_heading_style))

        # Analyse & Métadonnées
        analyse = analyze_position(piege["fen_final"])
        type_piege = classify_trap(piege)
        difficulte = estimate_difficulty(piege)

        elements.append(Paragraph(f"<b>Analyse :</b> {analyse} | <b>Type :</b> {type_piege} | <b>Difficulté :</b> {difficulte}", normal_style))
        elements.append(Spacer(1, 10))

        # Table des coups modernisée - générer dynamiquement à partir du champ "coups"
        full_moves = generate_moves(piege)
        
        table_data = [[
            Paragraph("<b>Coup Blanc</b>", normal_style), 
            Paragraph("<b>Commentaire</b>", normal_style), 
            Paragraph("<b>Coup Noir</b>", normal_style), 
            Paragraph("<b>Commentaire</b>", normal_style)
        ]]
        
        for i in range(0, len(full_moves), 2):
            blanc = full_moves[i]
            noir = full_moves[i+1] if i+1 < len(full_moves) else {"coup": "", "commentaire": ""}
            table_data.append([
                Paragraph(blanc.get("coup", ""), bold_style),
                Paragraph(blanc.get("commentaire", ""), normal_style),
                Paragraph(noir.get("coup", ""), bold_style),
                Paragraph(noir.get("commentaire", ""), normal_style)
            ])

        table = Table(table_data, colWidths=[80, 190, 80, 190], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), COLOR_PRIMARY),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, COLOR_BG_LIGHT]),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, COLOR_BORDER),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6)
        ]))
        
        # Astuce ReportLab pour que les en-têtes noirs du tableau soient blancs sur fond bleu
        for col in [0, 2]:
            table.setStyle(TableStyle([('TEXTCOLOR', (col,0), (col,0), colors.white)]))

        elements.append(KeepTogether([table, Spacer(1, 15)]))

        # Diagrammes (Configuration conservée mais design du tableau rafraîchi)
        orientation = get_trap_orientation(piege)
        fen_inter = piege.get("fen_intermediaire", piege["fen_defense"])

        diag_alerte = ChessboardFlowable(piege["fen_final"], size=130, fleches_menace=piege.get("fleches_menace", []), orientation=orientation)
        diag_inter = ChessboardFlowable(fen_inter, size=130, fleches_menace=piege.get("fleches_menace", []), orientation=orientation)
        diag_defense = ChessboardFlowable(piege["fen_defense"], size=130, fleches_defense=piege.get("fleches_defense", []), orientation=orientation)

        table_diags = Table([
            [Paragraph("<b>1) Position piégée</b>", normal_style), Paragraph("<b>2) Détection du piège</b>", normal_style), Paragraph("<b>3) Défense correcte</b>", normal_style)],
            [diag_alerte, diag_inter, diag_defense]
        ], colWidths=[180, 180, 180], repeatRows=1)
        
        table_diags.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (-1,0), COLOR_BG_LIGHT),
            ('LINEBELOW', (0,0), (-1,0), 1, COLOR_SECONDARY),
            ('BOX', (0,0), (-1,-1), 1, COLOR_BORDER),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5)
        ]))

        elements.append(KeepTogether([table_diags, Spacer(1, 15)]))

        # Idée & Défense en bas de page
        elements.append(Paragraph(f"<b>Idée :</b> {piege.get('conseil_defense', '')}", normal_style))
        elements.append(Paragraph(f"<b>Défense :</b> {piege.get('coup_defense', '')}", normal_style))
        elements.append(Spacer(1, 12))

    # 4. Conclusion
    elements.append(PageBreak())
    elements.append(Paragraph("Conclusion", conclusion_style))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("Entraînez-vous à repérer ces schémas dès l'ouverture et analysez les options de défense avant votre prochain coup.", normal_style))
    elements.append(Paragraph("À 650 Elo, l'objectif est d'automatiser l'alerte : si une pièce est menacée ou si un pion faible apparaît, prenez un moment pour vérifier la position complète.", normal_style))
    elements.append(Paragraph("Révisez ces 20 pièges régulièrement, et vous transformerez ces erreurs adverses en victoire facilement.", normal_style))

    # Génération du document avec appel du pied de page
    doc.build(elements, onFirstPage=ajouter_pied_page, onLaterPages=ajouter_pied_page)

if __name__ == "__main__":
    generer_pdf()
