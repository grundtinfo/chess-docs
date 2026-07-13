import chess
import chess.svg
from reportlab.lib import colors
from classes.config import Config
from io import StringIO
from reportlab.platypus import Flowable
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

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
        try:
            if not self.fen: return
            board = chess.Board(self.fen)
            arrows = []
            for notation in self.fleches_menace:
                try: arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:]), color="#FF0000"))
                except ValueError: pass
            for notation in self.fleches_defense:
                try: arrows.append(chess.svg.Arrow(chess.parse_square(notation[:2]), chess.parse_square(notation[2:]), color="#00AA00"))
                except ValueError: pass

            svg = chess.svg.board(board=board, size=self.size, arrows=arrows, orientation=self.orientation)
            drawing = svg2rlg(StringIO(svg))
            if drawing: renderPDF.draw(drawing, self.canv, 0, 0)
        except Exception: pass
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
    def __init__(self, values_player, values_opponent, labels=None, width=460, height=200):
        super().__init__()
        self.vp = values_player or []
        self.vo = values_opponent or []
        self.labels = labels or []
        self.width = width
        self.height = height

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        if not self.vp or len(self.vp) < 2: return
        x0, y0, x1, y1 = 40, 25, self.width - 20, self.height - 15
        
        self.canv.setStrokeColor(Config.COLOR_BORDER)
        self.canv.setLineWidth(0.6)
        self.canv.rect(x0, y0, x1 - x0, y1 - y0)
        
        all_vals = self.vp + self.vo
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
            points = [(x0 + (idx / max(len(values) - 1, 1)) * (x1 - x0), 
                       y0 + ((value - min_value) / span) * (y1 - y0)) 
                      for idx, value in enumerate(values)]

            segments = [(points[i][0], points[i][1], points[i+1][0], points[i+1][1]) for i in range(len(points) - 1)]
            self.canv.setStrokeColor(colors.HexColor(color_hex))
            self.canv.setLineWidth(1.8)
            self.canv.lines(segments)
            
            self.canv.setFillColor(colors.HexColor(color_hex))
            for x, y in points: self.canv.circle(x, y, 2.5, stroke=0, fill=1)

        draw_line(self.vo, "#f97316")
        draw_line(self.vp, "#0284c7")

        if self.labels:
            self.canv.setFont("Helvetica", 8)
            self.canv.setFillColor(Config.COLOR_TEXT)
            step = max(1, len(self.labels) // 6)
            for idx, label in enumerate(self.labels):
                if idx % step != 0 and idx != len(self.labels) - 1: continue
                x = x0 + (idx / max(len(self.vp) - 1, 1)) * (x1 - x0)
                self.canv.drawString(x - 10, y0 - 12, str(label)[:10])
