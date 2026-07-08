import chess
import chess.svg
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
