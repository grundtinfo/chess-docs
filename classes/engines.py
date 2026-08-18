import os
from classes.logger import Logger
from classes.config import Config
from classes.chess_utils import ChessUtils

try:
    from stockfish import Stockfish
    STOCKFISH_AVAILABLE = True
except ImportError:
    STOCKFISH_AVAILABLE = False
    Logger.debug_log("Stockfish non disponible. Les commentaires seront générés sans analyse.", "WARNING")

class StockfishAnalyzer:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.engine = None
            cls._instance._init_attempted = False
            cls._instance._eval_cache = {}
            cls._instance._best_move_cache = {}
        return cls._instance
    
    def get_engine(self, depth=None):
        if not STOCKFISH_AVAILABLE: return None
        if self._init_attempted: return self.engine
        
        self._init_attempted = True
        try:
            stockfish_path = None
            local_sf = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stockfish", "stockfish", "stockfish-ubuntu-x86-64-bmi2")
            if os.path.exists(local_sf): stockfish_path = local_sf
            
            if not stockfish_path:
                import shutil
                stockfish_path = shutil.which("stockfish")
            
            # NOUVEAU BLOC
            resolved_depth = ChessUtils.resolve_stockfish_depth(explicit_depth=depth)
            params = {
                "Threads": Config.STOCKFISH_THREADS,
                "Hash": Config.STOCKFISH_HASH
            }
            if stockfish_path:
                self.engine = Stockfish(path=stockfish_path, depth=resolved_depth, parameters=params)
            else:
                self.engine = Stockfish(depth=resolved_depth, parameters=params)
        except Exception:
            self.engine = None
        return self.engine

    def _check_cache_limits(self):
        # Maintient le cache en dessous de 3000 FEN pour éviter la saturation RAM
        if len(self._eval_cache) > 3000:
            self._eval_cache.clear()
        if len(self._best_move_cache) > 3000:
            self._best_move_cache.clear()

    # --- NOUVEAU BLOC ---
    def _get_cached_eval(self, fen):
        if not self.engine: return {"type": "cp", "value": 0}
        if fen in self._eval_cache:
            Logger.debug_log("Étape Stockfish : Évaluation trouvée dans le cache mémoire.", "DEBUG")
            return self._eval_cache[fen]
        
        Logger.debug_log("Étape Stockfish : Calcul de l'évaluation pour la position...", "DEBUG")
        self._check_cache_limits()
        self.engine.set_fen_position(fen)
        evaluation = self.engine.get_evaluation()
        self._eval_cache[fen] = evaluation
        return evaluation

    def _get_cached_best_move(self, fen):
        if not self.engine: return None
        if fen in self._best_move_cache:
            return self._best_move_cache[fen]
        self._check_cache_limits()
        self.engine.set_fen_position(fen)
        best_move = self.engine.get_best_move()
        self._best_move_cache[fen] = best_move
        return best_move

    def clear_cache(self):
        """Purge les dictionnaires de cache pour libérer la RAM."""
        self._eval_cache.clear()
        self._best_move_cache.clear()
        Logger.debug_log("Cache de Stockfish vidé avec succès.", "INFO")
    
    def analyze_move(self, board, move_san):
        engine = self.get_engine()
        if not engine: return None, None, None
        try:
            fen_before = board.fen()
            eval_before = self._get_cached_eval(fen_before)
            move_obj = board.parse_san(move_san)
            board.push(move_obj)
            fen_after = board.fen()
            eval_after = self._get_cached_eval(fen_after)
            board.pop()
            return eval_before, eval_after, move_obj
        except Exception:
            return None, None, None
    
    def get_best_move_with_eval(self, board):
        engine = self.get_engine()
        if not engine: return None, None, None
        try:
            fen = board.fen()
            best_move_uci = self._get_cached_best_move(fen) 
            if not best_move_uci: return None, None, None
            move_obj = board.parse_uci(best_move_uci)
            best_move_san_en = board.san(move_obj) 
            best_move_french = ChessUtils.convert_english_to_french_notation(best_move_san_en) 
            board_copy = board.copy()
            board_copy.push(move_obj)
            best_eval = self._get_cached_eval(board_copy.fen())
            return best_move_french, best_eval, best_move_uci
        except Exception:
            return None, None, None
