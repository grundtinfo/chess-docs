import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from classes.chess_utils import ChessUtils
from classes.ai_analyzer import AIAnalyzer
from scripts.chesscom_report import is_bot_game, opponent_name, side_name


class PlayerReportTests(unittest.TestCase):
    def test_classify_opponent_type_uses_human_default(self):
        self.assertEqual(ChessUtils.classify_opponent_type('gandalf123'), 'humain')
        self.assertEqual(ChessUtils.classify_opponent_type('chess-bot'), 'robot')
        self.assertEqual(ChessUtils.classify_opponent_type('https://api.chess.com/pub/player/matolic19'), 'humain')
        self.assertEqual(ChessUtils.classify_opponent_type('ai_bot_7'), 'robot')
        self.assertEqual(ChessUtils.classify_opponent_type('said'), 'humain')

    def test_build_player_state_path_uses_json_subfolder(self):
        base_dir = '/tmp/chess-docs'
        self.assertEqual(
            ChessUtils.build_player_state_path(base_dir, 'Alice'),
            '/tmp/chess-docs/json/player_Alice'
        )

    def test_infer_move_suffix_marks_checks_and_blunders(self):
        self.assertEqual(ChessUtils.infer_move_suffix(is_check=True), '+')
        self.assertEqual(ChessUtils.infer_move_suffix(is_checkmate=True), '#')
        self.assertEqual(ChessUtils.infer_move_suffix(delta=-400), '??')
        self.assertEqual(ChessUtils.infer_move_suffix(delta=-120), '?!')
        self.assertEqual(ChessUtils.infer_move_suffix(delta=300), '!')

    def test_is_bot_game_detects_cached_and_opponent_names(self):
        self.assertTrue(is_bot_game({"opponent_type": "robot"}, "Alice"))
        self.assertFalse(is_bot_game({"opponent_type": "humain", "black": {"username": "ChessBot"}}, "Alice"))

    def test_participant_helpers_accept_plain_usernames(self):
        game = {"white": "Alice", "black": "ChessBot"}
        self.assertEqual(side_name(game, "white"), "Alice")
        self.assertEqual(opponent_name(game, "Alice"), "ChessBot")
        self.assertFalse(is_bot_game(game, "Alice"))

    def test_side_name_normalizes_chess_com_player_urls_without_reclassifying(self):
        game = {
            "white": "https://api.chess.com/pub/player/grundt07",
            "black": "https://api.chess.com/pub/player/matolic19",
            "opponent_type": "humain",
        }
        self.assertEqual(side_name(game, "white"), "grundt07")
        self.assertEqual(side_name(game, "black"), "matolic19")
        self.assertFalse(is_bot_game(game, "grundt07"))

    def test_calculate_precision_from_details_ignores_unanalyzed_plies(self):
        precision = ChessUtils.calculate_precision_from_details([
            {"color": "white", "precision": 0},
            {"color": "black", "precision": -9999},
            {"color": "black", "precision": -100},
        ])
        self.assertEqual(precision["white"], 100.0)
        self.assertIsNotNone(precision["black"])

    def test_translate_compound_opening_names_before_generic_terms(self):
        self.assertEqual(
            AIAnalyzer.translate_opening_name("King's Indian Defense"),
            "Défense Est-Indienne"
        )
        self.assertEqual(
            AIAnalyzer.translate_opening_name("English Opening"),
            "Ouverture Anglaise"
        )


if __name__ == '__main__':
    unittest.main()
