import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from classes.chess_utils import ChessUtils
from scripts.chesscom_report import is_bot_game


class PlayerReportTests(unittest.TestCase):
    def test_classify_opponent_type_uses_human_default(self):
        self.assertEqual(ChessUtils.classify_opponent_type('gandalf123'), 'humain')
        self.assertEqual(ChessUtils.classify_opponent_type('chess-bot'), 'robot')

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
        self.assertTrue(is_bot_game({"white": {"username": "Alice"}, "black": {"username": "ChessBot"}}, "Alice"))
        self.assertFalse(is_bot_game({"white": {"username": "Alice"}, "black": {"username": "Bob"}}, "Alice"))

    def test_calculate_precision_from_details_ignores_unanalyzed_plies(self):
        precision = ChessUtils.calculate_precision_from_details([
            {"color": "white", "precision": 0},
            {"color": "black", "precision": -9999},
            {"color": "black", "precision": -100},
        ])
        self.assertEqual(precision["white"], 100.0)
        self.assertIsNotNone(precision["black"])


if __name__ == '__main__':
    unittest.main()
