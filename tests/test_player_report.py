import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from chesscom_report import (
    build_player_state_path,
    classify_opponent_type,
    infer_move_suffix,
    merge_state_with_incremental_games,
    refresh_state_with_player_games,
)


class PlayerReportTests(unittest.TestCase):
    def test_classify_opponent_type_uses_human_default(self):
        self.assertEqual(classify_opponent_type('gandalf123'), 'humain')
        self.assertEqual(classify_opponent_type('chess-bot'), 'autre')

    def test_build_player_state_path_uses_json_subfolder(self):
        base_dir = Path('/tmp/chess-docs')
        self.assertEqual(
            build_player_state_path(str(base_dir), 'Alice'),
            str(base_dir / 'json' / 'player_Alice.json')
        )

    def test_infer_move_suffix_marks_checks_and_blunders(self):
        self.assertEqual(infer_move_suffix(is_check=True), '+')
        self.assertEqual(infer_move_suffix(is_checkmate=True), '#')
        self.assertEqual(infer_move_suffix(delta=-400), '??')
        self.assertEqual(infer_move_suffix(delta=-120), '?')
        self.assertEqual(infer_move_suffix(delta=300), '!')

    def test_refresh_state_uses_existing_games_when_fetch_fails(self):
        existing_state = {"player": "Alice", "games": [{"id": "cached", "result": "*"}]}
        with patch("chesscom_report.fetch_player_games", side_effect=requests.HTTPError("403")):
            new_state, refreshed, message = refresh_state_with_player_games(existing_state, "Alice", months=1)
        self.assertFalse(refreshed)
        self.assertEqual(new_state["games"], existing_state["games"])
        self.assertIn("données déjà sauvegardées", message)

    def test_merge_state_with_incremental_games_preserves_existing_entries(self):
        existing_state = {"player": "Alice", "games": [{"id": "cached", "result": "*"}]}
        incoming_state = {"player": "Alice", "games": [{"id": "new", "result": "1-0"}]}
        merged_state = merge_state_with_incremental_games(existing_state, incoming_state)
        self.assertEqual(len(merged_state["games"]), 2)
        self.assertEqual(merged_state["player"], "Alice")
        self.assertIn("last_updated", merged_state)


if __name__ == '__main__':
    unittest.main()
