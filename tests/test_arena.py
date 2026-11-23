"""Checks for tools/arena.py. From the repository root:

    venv/bin/python -m unittest discover -s tests -p "test_arena.py" -v
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import unittest

from contest import capture

REPO = Path(__file__).resolve().parent.parent


class ReplayTest(unittest.TestCase):
    def test_rejects_conflicting_games_before_writing_output(self):
        cases = (
            (["baseline", "--layouts", "RANDOM1-2,RANDOM2"], False, "duplicate game identity"),
            (["first/opponent.py", "second/opponent.py"], True, "duplicate game identity"),
            (["first/opponent.py", "second/Opponent.py"], True, "replay filename collision"),
        )
        for args, save_replays, message in cases:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as folder:
                folder = Path(folder)
                output = folder / "games.jsonl"
                replays = folder / "replays"
                cmd = [sys.executable, str(REPO / "tools/arena.py"), "my_team.py", *args, "--out", str(output)]
                if save_replays:
                    cmd.extend(["--replays", str(replays)])
                result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse(output.exists())
                self.assertFalse(replays.exists())

    def test_replays_reproduce_the_games(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            subprocess.run([sys.executable, str(REPO / "tools/arena.py"), "my_team.py", "baseline",
                            "--layouts", "defaultCapture", "--jobs", "2", "--replays", str(folder / "replays"),
                            "--out", str(folder / "games.jsonl")], cwd=REPO, check=True, capture_output=True)
            rows = [json.loads(line) for line in (folder / "games.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            for row in rows:
                path = folder / "replays" / ("baseline-%s-%s.replay" % (row["seed"], row["color"]))
                record = pickle.loads(path.read_bytes())
                # Replaying the recorded moves must give the same game the arena reported.
                actions = record["actions"]
                self.assertEqual((record["length"], record["red_team_name"], record["blue_team_name"]),
                                 (1200, "Red", "Blue"))
                self.assertEqual(hashlib.sha256(json.dumps(actions).encode()).hexdigest()[:16], row["digest"])
                with contextlib.redirect_stdout(io.StringIO()):
                    state = capture.CaptureRules().new_game(record["layout"], record["agents"], None,
                                                            record["length"], False, False).state
                for action in actions:
                    state = state.generate_successor(*action)
                sign = 1 if row["color"] == "red" else -1
                self.assertEqual(sign * state.get_score(), row["score"])
                self.assertNotEqual(row["score"], 0)


if __name__ == "__main__":
    unittest.main()
