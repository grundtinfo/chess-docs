import math
import chess
import chess.svg
from datetime import datetime
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


def generate_move_comment(move_raw, move_san, board):
    """Génère un commentaire pédagogique simple pour un coup donné."""
    raw = move_raw.strip()
    raw_clean = re.sub(r'[?!+#]+', '', raw)
    
    if "??" in raw:
        return "Erreur grave, c'est une gaffe."
    if "?!" in raw:
        return "Coup douteux. Les réponses existent."
    if "!?" in raw:
        return "Coup intéressant mais potentiellement risqué, soyez vigilant."
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
        return "Capture une pièce ou un pion, souvent au cœur du piège."
    if raw_clean.startswith("D"):
        return "Développe la Dame pour maintenir l'initiative."
    if raw_clean.startswith("C"):
        return "Développe le Cavalier vers une case active."
    if raw_clean.startswith("F"):
        return "Développe le Fou et cible le centre ou la faiblesse f7/h7."
    if raw_clean.startswith("T"):
        return "Développe la Tour, souvent après l'ouverture du jeu."
    if raw_clean.startswith("R"):
        return "Sécurise le Roi ou prépare la défense."
    if raw_clean in ["e4", "d4", "e5", "d5"]:
        return "Prend le contrôle du centre."
    if raw_clean and raw_clean[0] in "abcdefgh":
        return "Avance un pion pour ouvrir le jeu ou soutenir le centre."

    theme = detect_theme(raw_clean)
    if theme:
        return theme

    return "Coup de développement utile dans cette séquence."

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

def convert_french_to_english_notation(move):
    """Convertit la notation française des pièces vers la notation anglaise SAN."""
    # Dictionnaire de conversion des pièces
    piece_map = {
        'D': 'Q',  # Dame -> Queen
        'C': 'N',  # Cavalier -> Knight
        'F': 'B',  # Fou -> Bishop
        'T': 'R',  # Tour -> Rook
        'R': 'K',  # Roi -> King
    }
    
    # Gérer les promotions : =C -> =N, etc.
    if '=' in move:
        parts = move.split('=')
        if len(parts) == 2 and parts[1] in piece_map:
            move = parts[0] + '=' + piece_map[parts[1]]
    
    # Remplacer la première lettre si c'est une pièce (mais pas après =)
    if move and move[0] in piece_map and '=' not in move[:move.find('=') if '=' in move else len(move)]:
        move = piece_map[move[0]] + move[1:]
    
    return move

def parse_moves(coups_str):
    """Parse la chaîne de coups en liste de coups en français + SAN anglais."""
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


def normalize_defense_spec(defense_text):
    """Isoler l'ordre de coup et le texte du coup de défense."""
    if not defense_text:
        return None, ""
    defense_text = defense_text.strip()
    match = re.match(r'^(\d+)\s*(?:\.{3}|\.)\s*(.+)$', defense_text)
    if match:
        return int(match.group(1)), match.group(2).strip()
    return None, defense_text


def split_move_options(moves_text):
    return [m.strip() for m in re.split(r'\s+ou\s+|\s*,\s*', moves_text) if m.strip()]

def generate_moves(piege):
    """Génère la liste des coups par paire avec mini-diagrammes de fin de coup blanc/noir."""
    coups_str = piege.get("coups", "")
    moves = parse_moves(coups_str)

    rows = []
    board = chess.Board()
    current_row = None

    for move in moves:
        color = move.get("color")
        move_raw = move.get("raw", "")
        move_san = move.get("san", "")
        move_number = move.get("move_number")

        try:
            board.push(board.parse_san(move_san))
        except Exception:
            pass

        commentaire = generate_move_comment(move_raw, move_san, board)
        fen_after = board.fen()

        if color == "white":
            current_row = {
                "move_number": move_number,
                "white": move_raw,
                "white_comment": commentaire,
                "white_fen": fen_after,
                "black": "",
                "black_comment": "",
                "black_fen": None
            }
            rows.append(current_row)
        else:
            if current_row is None or current_row.get("move_number") != move_number:
                current_row = {
                    "move_number": move_number,
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

def generate_fen_positions(piege):
    """Génère fen_final, fen_intermediaire et fen_defense automatiquement."""
    coups_str = piege.get("coups", "")
    moves = parse_moves(coups_str)
    
    board = chess.Board()
    positions = []
    
    # Jouer tous les coups pour obtenir les positions intermédiaires
    for i, move in enumerate(moves):
        try:
            move = board.parse_san(move["san"])
            board.push(move)
            positions.append(board.fen())
        except Exception as e:
            # Erreur parsing move, skip ce piège
            return None, None, None
    
    if len(positions) < 2:
        return positions[-1] if positions else None, None, None
    
    fen_final = positions[-1]

    coup_defense = piege.get("coup_defense", "")
    defense_order, defense_text = normalize_defense_spec(coup_defense)
    defense_options = split_move_options(defense_text)

    if defense_order is not None:
        if piege.get("defenseur") == "Noirs":
            # Position juste après le coup blanc du même numéro de demi-coup
            index = 2 * (defense_order - 1)
        else:
            # Position juste après le coup noir précédent
            index = 2 * defense_order - 3
        if 0 <= index < len(positions):
            fen_intermediaire = positions[index]
        else:
            fen_intermediaire = positions[-2]
    else:
        fen_intermediaire = positions[-3] if len(positions) >= 3 else positions[-2]

    # Si plusieurs options de défense sont recommandées, fen_intermediaire == fen_defense
    if len(defense_options) > 1:
        fen_defense = fen_intermediaire
    else:
        fen_defense = fen_intermediaire
        if defense_options:
            board_defense = chess.Board(fen_intermediaire)
            option = defense_options[0]
            defense_move_clean = convert_french_to_english_notation(re.sub(r'[?!+#x]+', '', option))
            try:
                move = board_defense.parse_san(defense_move_clean)
                board_defense.push(move)
                fen_defense = board_defense.fen()
            except Exception:
                pass

    return fen_final, fen_intermediaire, fen_defense


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
        "guide_pieges_et_defenses.pdf", 
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
    elements.append(Paragraph("Guide des Pièges d'Ouverture", title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("Ce guide met l'accent sur la détection des menaces tactiques, la compréhension des plans et l'apprentissage des réponses solides.", intro_style))
    elements.append(Paragraph("L'objectif est de renforcer la vigilance sur les cases faibles (f7/h7), la sécurité du roi, et la gestion des pièges d'ouverture.", intro_style))
    elements.append(Paragraph("Ce document sera mis à jour régulièrement en fonction des ouvertures portées à ma connaissance et des pièges que j'aurai rencontré lors de mes parties.", intro_style))
    elements.append(Paragraph("Dernière mise à jour le " + datetime.now().strftime("%d/%m/%Y à %H:%M"), intro_style))
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
        
        # --- CRÉATION D'UN BLOC REGROUPÉ ---
        bloc_introduction = []
        
        # Titre du piège
        bloc_introduction.append(Paragraph(f"{idx+1}. {piege['nom']}", trap_heading_style))

        # Générer les FEN automatiquement
        fen_final, fen_intermediaire, fen_defense = generate_fen_positions(piege)
        if not fen_final:
            continue 

        # Analyse & Métadonnées
        analyse = analyze_position(fen_final)
        type_piege = classify_trap(piege)
        difficulte = estimate_difficulty(piege)
        
        meta_text = f"<b>Analyse :</b> {analyse} | <b>Type :</b> {type_piege} | <b>Difficulté :</b> {difficulte}"
        bloc_introduction.append(Paragraph(meta_text, normal_style))
        bloc_introduction.append(Spacer(1, 10)) # Espace réduit entre intro et tableau

        # Génération des données du tableau
        rows = generate_moves(piege)
        orientation = get_trap_orientation(piege)
        
        table_data = [[
            Paragraph("<b>Diag</b>", normal_style), 
            Paragraph("<b>Coup Blanc</b>", normal_style), 
            Paragraph("<b>Commentaire</b>", normal_style), 
            Paragraph("<b>Coup Noir</b>", normal_style), 
            Paragraph("<b>Commentaire</b>", normal_style)
        ]]
        
        for row in rows:
            fen_diag = row.get("black_fen") or row.get("white_fen")
            diag = ChessboardFlowable(fen_diag, size=90, orientation=orientation) if fen_diag else ""
            table_data.append([
                diag,
                Paragraph(row.get("white", ""), bold_style),
                Paragraph(row.get("white_comment", ""), normal_style),
                Paragraph(row.get("black", ""), bold_style),
                Paragraph(row.get("black_comment", ""), normal_style)
            ])

        # Création du tableau
        table_coups = Table(table_data, colWidths=[100, 55, 145, 55, 145], repeatRows=1)
        table_coups.setStyle(TableStyle([
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

        bloc_introduction.append(table_coups)
        
        # On ajoute tout ce bloc d'un coup. ReportLab essaiera de garder 
        # le titre, l'analyse et le tableau sur la même page.
        elements.append(KeepTogether(bloc_introduction))
        elements.append(Spacer(1, 15))

        # Diagrammes (Configuration conservée mais design du tableau rafraîchi)
        orientation = get_trap_orientation(piege)

        diag_alerte = ChessboardFlowable(fen_final, size=130, fleches_menace=piege.get("fleches_menace", []), orientation=orientation)
        diag_inter = ChessboardFlowable(fen_intermediaire, size=130, fleches_menace=piege.get("fleches_menace", []), orientation=orientation)
        diag_defense = ChessboardFlowable(fen_defense, size=130, fleches_defense=piege.get("fleches_defense", []), orientation=orientation)

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
        elements.append(Paragraph(f"<b>Défense :</b> {piege.get('coup_defense', '')} - {piege.get('explication_defense', '')}", normal_style))
        elements.append(Spacer(1, 12))

    # 4. Conclusion
    elements.append(PageBreak())
    elements.append(Paragraph("Conclusion", conclusion_style))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("Entraînez-vous à repérer ces schémas dès l'ouverture et analysez les options de défense avant votre prochain coup.", normal_style))
    elements.append(Paragraph("À 650 Elo, l'objectif est d'automatiser l'alerte : si une pièce est menacée ou si un pion faible apparaît, prenez un moment pour vérifier la position complète.", normal_style))
    elements.append(Paragraph("Révisez ces pièges régulièrement, et vous transformerez ces erreurs adverses en victoire facilement.", normal_style))

    # Génération du document avec appel du pied de page
    doc.build(elements, onFirstPage=ajouter_pied_page, onLaterPages=ajouter_pied_page)

if __name__ == "__main__":
    generer_pdf()
