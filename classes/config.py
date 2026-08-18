import os
from reportlab.lib import colors

class Config:
    DEFAULT_STOCKFISH_DEPTH = 18
    # Allocation dynamique : laisse au moins 2 cœurs libres pour le système/WSL
    STOCKFISH_THREADS = max(1, (os.cpu_count() or 4) - 2)
    # Empreinte RAM optimisée (512 Mo au lieu de 6144 Mo)
    STOCKFISH_HASH = 512

    COLOR_PRIMARY = colors.HexColor("#1e293b")
    COLOR_SECONDARY = colors.HexColor("#0284c7")
    COLOR_TEXT = colors.HexColor("#334155")
    COLOR_BG_LIGHT = colors.HexColor("#f8fafc")
    COLOR_BORDER = colors.HexColor("#e2e8f0")
    COLOR_MINT = colors.HexColor("#0f766e")
