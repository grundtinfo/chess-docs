import os
import concurrent.futures
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
            # File d'attente d'exécution avec 1 worker pour gérer le timeout
            cls._instance._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
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
        # Maintient le cache avec une purge dynamique plus agressive (50%)
        # pour éviter la saturation mémoire sur les parties de plus de 100 coups.
        MAX_CACHE = 3000
        PURGE_AMOUNT = 1500
        
        if len(self._eval_cache) > MAX_CACHE:
            keys_to_delete = list(self._eval_cache.keys())[:PURGE_AMOUNT]
            for k in keys_to_delete:
                del self._eval_cache[k]
                
        if len(self._best_move_cache) > MAX_CACHE:
            keys_to_delete = list(self._best_move_cache.keys())[:PURGE_AMOUNT]
            for k in keys_to_delete:
                del self._best_move_cache[k]

    def _reset_engine(self):
        """Réinitialise l'instance Stockfish en cas de blocage (Watchdog)."""
        Logger.debug_log("Réinitialisation forcée du moteur Stockfish suite à un blocage...", "WARNING")
        if self.engine:
            try:
                self.engine.__del__() # Tente de tuer le processus proprement
            except Exception:
                pass
        self.engine = None
        self._init_attempted = False
        self.get_engine()

    def _run_with_watchdog(self, task_name, func, *args, **kwargs):
        """
        Exécute une fonction Stockfish. Ajuste le timeout dynamiquement 
        selon la profondeur ET le nombre de coups de façon exponentielle.
        """
        if not self.engine:
            return None
            
        import math
        depth = self.engine.get_engine_parameters().get("Depth", Config.DEFAULT_STOCKFISH_DEPTH)
        
        # Récupération du numéro de coup pour ajustement exponentiel
        move_number = 1
        try:
            fen = self.engine.get_fen_position()
            if fen:
                move_number = int(fen.split()[-1])
        except Exception:
            pass
        
        # Timeout exponentiel : (5 + depth * 1.5) * e^(move_number / 100)
        # Accorde plus de temps aux calculs profonds en fin de parties longues
        calculated_timeout = (5 + depth * 1.5) * math.exp(move_number / 100.0)
        timeout = min(int(calculated_timeout), 120) # Limite stricte à 120s
        
        future = self._executor.submit(func, *args, **kwargs)
        elapsed = 0
        
        while elapsed < timeout:
            try:
                # Attend 1 seconde maximum pour voir si le calcul est fini
                return future.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                elapsed += 1
                Logger.debug_log(f"[{task_name}] Calcul en cours (Profondeur: {depth}, Coup: {move_number}) - {elapsed}s / {timeout}s", "INFO")
        
        # Si on sort de la boucle, le moteur est figé
        Logger.debug_log(f"[{task_name}] Stockfish a figé (Timeout de {timeout}s dépassé). Reprise de l'application...", "ERROR")
        self._reset_engine()
        return None

    def _get_cached_eval(self, fen):
        if not self.engine: return {"type": "cp", "value": 0}
        if fen in self._eval_cache:
            Logger.debug_log("Étape Stockfish : Évaluation trouvée dans le cache mémoire.", "DEBUG")
            return self._eval_cache[fen]
        
        Logger.debug_log("Étape Stockfish : Calcul de l'évaluation pour la position...", "DEBUG")
        self._check_cache_limits()
        self.engine.set_fen_position(fen)
        
        # Modification : Appel sécurisé
        evaluation = self._run_with_watchdog("Évaluation", self.engine.get_evaluation)
        if not evaluation:
            return {"type": "cp", "value": 0} # Sécurité pour que le programme continue
            
        self._eval_cache[fen] = evaluation
        return evaluation

    def _get_cached_best_move(self, fen):
        if not self.engine: return None
        if fen in self._best_move_cache:
            return self._best_move_cache[fen]
        self._check_cache_limits()
        self.engine.set_fen_position(fen)
        
        # Modification : Appel sécurisé
        best_move = self._run_with_watchdog("Meilleur Coup", self.engine.get_best_move)
        if not best_move:
            return None # Sécurité pour que le programme continue
            
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

    def get_fast_pv_sequence(self, board, max_moves=6):
        """Extrait la ligne principale quasi-instantanément en exploitant la Transposition Table."""
        if not self.engine: return []
        
        seq_eng = []
        original_depth = self.engine.get_engine_parameters().get("Depth", Config.DEFAULT_STOCKFISH_DEPTH)
        
        try:
            # Profondeur minimale : le calcul tape directement dans le cache interne de Stockfish
            self.engine.set_depth(2)
            sim_board = board.copy()
            
            for _ in range(max_moves):
                if sim_board.is_game_over(): break
                
                self.engine.set_fen_position(sim_board.fen())
                
                best_uci = self._run_with_watchdog("Séquence Rapide", self.engine.get_best_move)
                
                if not best_uci: break
                
                move_obj_sim = sim_board.parse_uci(best_uci)
                seq_eng.append(sim_board.san(move_obj_sim))
                sim_board.push(move_obj_sim)
        finally:
            # Restauration immédiate de la profondeur de calcul
            self.engine.set_depth(original_depth)
            
        return seq_eng
