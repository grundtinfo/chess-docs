import chess
import chess.svg
from reportlab.lib import colors
from classes.config import Config
from io import StringIO
from reportlab.platypus import Flowable
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

class ChessboardFlowable(Flowable):
    def __init__(self, fen, size=150, fleches_defense=None, fleches_menace=None, fleches_oranges=None, fleches_bleues=None, fleches_blanches=None, fleches_noires=None, fleches_rouges=None, orientation=chess.WHITE):
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
        self.orientation = orientation

    def wrap(self, availWidth, availHeight): 
        return self.size, self.size

    def draw(self):
        try:
            if not self.fen: return
            board = chess.Board(self.fen)
            arrows = []
            
            # Fonction utilitaire pour parser et ajouter la flèche
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

            svg = chess.svg.board(board=board, size=self.size, arrows=arrows, orientation=self.orientation)
            drawing = svg2rlg(StringIO(svg))
            if drawing: renderPDF.draw(drawing, self.canv, 0, 0)
        except Exception as e: 
            pass

class PDFUtils:
    @staticmethod
    def ajouter_pied_page(canvas, doc, title):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(Config.COLOR_TEXT)
        canvas.drawString(36, 20, title)
        canvas.drawRightString(doc.pagesize[0] - 36, 20, f"Page {doc.page}")
        canvas.restoreState()

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
                
            min_value, max_value = max(0, min(all_vals) - 150), max(all_vals) + 150
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
