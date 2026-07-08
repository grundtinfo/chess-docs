from reportlab.lib import colors

class Config:
    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "llama3.1:8b"
    DEFAULT_STOCKFISH_DEPTH = 18

    COLOR_PRIMARY = colors.HexColor("#1e293b")
    COLOR_SECONDARY = colors.HexColor("#0284c7")
    COLOR_TEXT = colors.HexColor("#334155")
    COLOR_BG_LIGHT = colors.HexColor("#f8fafc")
    COLOR_BORDER = colors.HexColor("#e2e8f0")
    COLOR_MINT = colors.HexColor("#0f766e")
