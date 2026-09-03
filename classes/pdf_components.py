import chess
import chess.svg
from reportlab.lib import colors
from classes.config import Config
from io import StringIO
from reportlab.platypus import Flowable
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF
from classes.logger import Logger

_SVG_DRAWING_CACHE = {}

class ChessboardFlowable(Flowable):
    def __init__(self, fen, size=150, fleches_defense=None, fleches_menace=None, fleches_oranges=None, fleches_bleues=None, fleches_blanches=None, fleches_noires=None, fleches_rouges=None, fleches_bordeaux=None, orientation=chess.WHITE):
        Flowable.__init__(self)
        self.fen = fen
        self.size = size
        self.fleches_defense = fleches_defense or []
        self.fleches_menace = fleches_menace or []
        self.fleches_oranges = fleches_oranges or []
        self.fleches_bleues = fleches_bleues or []
        self.fleches_blanches = fleches_blanches or []
        self.fleches_noires = fleches_noires or []
        self.fleches_rouges = fleches_rouges or []
        self.fleches_bordeaux = fleches_bordeaux or []
        self.orientation = orientation

    def wrap(self, availWidth, availHeight): 
        return self.size, self.size

    def draw(self):
        try:
            if not self.fen: return
            
            # Clé unique pour vérifier si la position exacte a déjà été convertie en dessin PDF
            cache_key = (
                self.fen, self.size, self.orientation,
                tuple(self.fleches_defense), tuple(self.fleches_menace),
                tuple(self.fleches_oranges), tuple(self.fleches_bleues),
                tuple(self.fleches_blanches), tuple(self.fleches_noires), tuple(self.fleches_rouges),
                tuple(self.fleches_bordeaux)
            )
            
            if cache_key in _SVG_DRAWING_CACHE:
                Logger.debug_log("Étape Rendu PDF : Diagramme d'échiquier récupéré depuis le cache mémoire.", "DEBUG")
                drawing = _SVG_DRAWING_CACHE[cache_key]
            else:
                Logger.debug_log(f"Étape Rendu PDF : Génération SVG d'un nouvel échiquier (FEN: {self.fen[:15]}...).", "DEBUG")
                board = chess.Board(self.fen)
                arrows = []
                
                def add_arrows(notations, hex_color):
                    for notation in notations:
                        if not notation or len(notation) < 4: continue
                        try: arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:4]), color=hex_color))
                        except ValueError: pass

                add_arrows(self.fleches_menace, "#FF0000")
                add_arrows(self.fleches_defense, "#00AA00")
                add_arrows(self.fleches_oranges, "orange")
                add_arrows(self.fleches_bleues, "blue")
                add_arrows(self.fleches_blanches, "white")
                add_arrows(self.fleches_noires, "black")
                add_arrows(self.fleches_rouges, "red")
                add_arrows(self.fleches_bordeaux, "#800020") # Hex pour le Bordeaux

                svg = chess.svg.board(board=board, size=self.size, arrows=arrows, orientation=self.orientation)
                drawing = svg2rlg(StringIO(svg))
                if len(_SVG_DRAWING_CACHE) < 500:
                    _SVG_DRAWING_CACHE[cache_key] = drawing

            if drawing: 
                renderPDF.draw(drawing, self.canv, 0, 0)
        except Exception: 
            pass

class PDFUtils:
    @staticmethod
    def header_footer_callback(canvas, doc, title=""):
        canvas.saveState()
        
        # Récupération des chapitres dessinés sur la page courante
        chapters = getattr(canvas, 'chapters_on_page', [])
        
        # Initialisation du dictionnaire d'état des chapitres si inexistant
        if not hasattr(canvas, 'current_chapters_state'):
            canvas.current_chapters_state = {}
            
        # Mise à jour de l'état des chapitres selon le niveau
        for lvl, chap_title in chapters:
            canvas.current_chapters_state[lvl] = chap_title
            # Efface les sous-niveaux orphelins si on remonte dans la hiérarchie
            for k in list(canvas.current_chapters_state.keys()):
                if k > lvl:
                    del canvas.current_chapters_state[k]

        canvas.setFont('Helvetica', 9)
        try:
            from classes.config import Config
            canvas.setFillColor(Config.COLOR_TEXT)
        except Exception:
            canvas.setFillColorRGB(0.2, 0.2, 0.2)
        
        # L'en-tête affiche le niveau le plus haut actuellement actif.
        if doc.page > 0 and canvas.current_chapters_state:
            smallest_level = min(canvas.current_chapters_state)
            canvas.drawString(36, doc.pagesize[1] - 25, canvas.current_chapters_state[smallest_level])
        
        # Pied de page : Dernier niveau de chapitrage de la page (le plus profond)
        footer_text = f"{title} | " if title else ""
        if canvas.current_chapters_state:
            max_level = max(canvas.current_chapters_state.keys())
            last_level_title = canvas.current_chapters_state.get(max_level, "")
            
            if last_level_title:
                footer_text += f"{last_level_title}"
                
        if footer_text:
            canvas.drawString(36, 20, footer_text)
            
        canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
        
        # Réinitialisation stricte pour la page suivante
        canvas.chapters_on_page = []
        canvas.restoreState()

class ChapterMarker(Flowable):
    """
    Marqueur invisible permettant de remonter à header_footer_callback
    le chapitre courant et son niveau d'importance (1 = Titre principal, 2 = Sous-titre, etc.).
    """
    def __init__(self, title, level=1):
        Flowable.__init__(self)
        self.title = title
        self.level = level

    def wrap(self, availWidth, availHeight):
        return 0, 0

    def draw(self):
        if not hasattr(self.canv, 'chapters_on_page'):
            self.canv.chapters_on_page = []
        self.canv.chapters_on_page.append((self.level, self.title))

class WinDrawLossBar(Flowable):
    """Dessine une barre horizontale proportionnelle pour les Victoires/Nuls/Défaites."""
    def __init__(self, wins, draws, losses, width=300, height=15):
        Flowable.__init__(self)
        self.wins = wins
        self.draws = draws
        self.losses = losses
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return self.width, self.height

    def draw(self):
        total = self.wins + self.draws + self.losses
        if total == 0: return
        
        w_w = self.width * (self.wins / total)
        d_w = self.width * (self.draws / total)
        l_w = self.width * (self.losses / total)
        
        current_x = 0
        self.canv.setFont("Helvetica-Bold", 9)
        
        def draw_segment(w, val, color_hex):
            nonlocal current_x
            if w > 0:
                self.canv.setFillColor(colors.HexColor(color_hex))
                self.canv.rect(current_x, 0, w, self.height, stroke=0, fill=1)
                # Affichage du nombre uniquement si la zone est assez large
                if w > 20:
                    self.canv.setFillColor(colors.white)
                    # Centrage vertical ajusté
                    self.canv.drawCentredString(current_x + w/2, self.height/2 - 3, str(val))
                current_x += w

        draw_segment(w_w, self.wins, "#22c55e")  # Vert (Victoires)
        draw_segment(d_w, self.draws, "#94a3b8") # Gris (Nuls)
        draw_segment(l_w, self.losses, "#ef4444") # Rouge (Défaites)

class EloProgressionChart(Flowable):
    def __init__(self, data_source, target_username=None, width=460, height_per_chart=180):
        super().__init__()
        self.width = width
        self.height_per_chart = height_per_chart
        
        # Le constructeur accepte désormais directement la liste des parties brutes
        if isinstance(data_source, list) and target_username:
            self.charts_data = self._prepare_data(data_source, target_username)
        elif isinstance(data_source, dict):
            self.charts_data = data_source # Fallback de rétrocompatibilité
        else:
            self.charts_data = {}
            
        # Ajustement dynamique de la hauteur globale du Flowable en fonction du nombre de graphiques
        self.total_height = len(self.charts_data) * (self.height_per_chart + 50) if self.charts_data else 0

    def _prepare_data(self, games, target_username):
        # Tri chronologique absolu : du plus ancien au plus récent (gauche vers la droite)
        sorted_games = sorted(games, key=lambda g: g.get("end_time", 0))
        
        groups = {}
        for g in sorted_games:
            time_class = str(g.get("time_class", "Inconnu")).capitalize()
            opp_type = str(g.get("opponent_type", "Humain")).capitalize()
            cat = f"{time_class} ({opp_type})" # ex: "Daily (Humain)"
            
            if cat not in groups:
                groups[cat] = {"vp": [], "vo": [], "labels": []}
            
            is_white = str(g.get("white", {}).get("username", "")).lower() == target_username.lower()
            elo_p = g.get("analysis", {}).get("est_elo_white" if is_white else "est_elo_black", 1200)
            elo_o = g.get("analysis", {}).get("est_elo_black" if is_white else "est_elo_white", 1200)
            
            date_str = g.get("date", "").split(" ")[0] if g.get("date") else ""
            
            groups[cat]["vp"].append(elo_p)
            groups[cat]["vo"].append(elo_o)
            groups[cat]["labels"].append(date_str)
            
        return groups

    def wrap(self, avail_width, avail_height):
        return self.width, self.total_height

    def draw(self):
        if not self.charts_data: return
        
        current_y = self.total_height
        
        for cat, data in self.charts_data.items():
            vp, vo, labels = data.get("vp", []), data.get("vo", []), data.get("labels", [])
            
            current_y -= 20
            self.canv.setFont("Helvetica-Bold", 10)
            self.canv.setFillColor(Config.COLOR_PRIMARY)
            self.canv.drawString(40, current_y, f"Progression ELO : {cat}")
            
            chart_y = current_y - self.height_per_chart
            x0, y0, x1, y1 = 40, chart_y + 25, self.width - 20, current_y - 10
            
            self.canv.setStrokeColor(Config.COLOR_BORDER)
            self.canv.setLineWidth(0.6)
            self.canv.rect(x0, y0, x1 - x0, y1 - y0)
            
            all_vals = vp + vo
            if not all_vals:
                current_y = chart_y - 30
                continue
                
            min_value = min(all_vals)
            max_value = max(all_vals)
            if min_value == max_value:
                min_value -= 50
                max_value += 50
                
            span = max_value - min_value or 1

            self.canv.setFont("Helvetica", 8)
            self.canv.setFillColor(Config.COLOR_TEXT)
            num_steps = 5
            
            for i in range(num_steps + 1):
                y_pos = y0 + (i / num_steps) * (y1 - y0)
                val = min_value + (i / num_steps) * span
                self.canv.drawRightString(x0 - 5, y_pos - 3, str(int(val)))
                if 0 < i < num_steps:
                    self.canv.setStrokeColor(Config.COLOR_BORDER)
                    self.canv.setDash(2, 2)
                    self.canv.line(x0, y_pos, x1, y_pos)
                    self.canv.setDash()

            def draw_line(values, color_hex):
                if not values: return
                points = [(x0 + (idx / max(len(values) - 1, 1)) * (x1 - x0), 
                           y0 + ((value - min_value) / span) * (y1 - y0)) 
                          for idx, value in enumerate(values)]
                
                if len(points) > 1:
                    segments = [(points[i][0], points[i][1], points[i+1][0], points[i+1][1]) for i in range(len(points) - 1)]
                    self.canv.setStrokeColor(colors.HexColor(color_hex))
                    self.canv.setLineWidth(1.8)
                    self.canv.lines(segments)
                
                self.canv.setFillColor(colors.HexColor(color_hex))
                for x, y in points: self.canv.circle(x, y, 2.5, stroke=0, fill=1)

            draw_line(vo, "#f97316") # Opposant (Orange)
            draw_line(vp, "#0284c7") # Joueur (Bleu)

            if labels:
                self.canv.setFont("Helvetica", 8)
                self.canv.setFillColor(Config.COLOR_TEXT)
                step = max(1, len(labels) // 6)
                for idx, label in enumerate(labels):
                    if idx % step != 0 and idx != len(labels) - 1: continue
                    x_pos = x0 + (idx / max(len(vp) - 1, 1)) * (x1 - x0)
                    lbl_str = str(label)
                    # On allège l'axe X en affichant uniquement MM-DD si possible
                    if len(lbl_str) >= 10 and "-" in lbl_str:
                        lbl_str = lbl_str[5:10]
                    self.canv.drawString(x_pos - 10, y0 - 12, lbl_str)
            
            # Espacement pour le prochain graphique
            current_y = chart_y - 20
