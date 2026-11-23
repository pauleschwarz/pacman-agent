"""Checks for tools/report.py. From the repository root:

    venv/bin/python -m unittest discover -s tests -p "test_report.py" -v
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import report  # noqa: E402


def game(layout="RANDOM1", color="red", seed="s", outcome="W", score=3, opponent="baseline", **fields):
    row = dict(opponent=opponent, layout=layout, color=color, seed=seed, error=False,
               outcome=outcome, score=score, banked=max(score or 0, 0), conceded=max(-(score or 0), 0))
    row.update(fields)
    return row


class ReportTest(unittest.TestCase):
    def run_report(self, *lines):
        """Writes the lines to a file and returns exit code, stdout and stderr of the command."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "games.jsonl"
            path.write_bytes(b"\n".join(l if isinstance(l, bytes) else
                                         (l if isinstance(l, str) else json.dumps(l)).encode() for l in lines))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = report.main([str(path)])
            return code, out.getvalue(), err.getvalue()

    def test_rows_per_layout_and_total(self):
        code, out, err = self.run_report(
            game("RANDOM1", "red", outcome="W", score=4),
            game("RANDOM1", "blue", outcome="L", score=-2),
            game("RANDOM2", "red", outcome="D", score=0),
            game("RANDOM2", "blue", error=True, outcome="W", score=9),  # an error never counts as a win
            "",
        )
        self.assertEqual((code, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[2], "| baseline | RANDOM1 | 2 | 1/0/1 | 50.0% | 1.0 | 2.0 | 1.0 | 0 |")
        self.assertEqual(lines[3], "| baseline | RANDOM2 | 2 | 0/1/0 | 33.3% | 0.0 | 0.0 | 0.0 | 1 |")
        self.assertEqual(lines[4], "| baseline | **all** | 4 | 1/1/1 | 44.4% | 0.7 | 1.3 | 0.7 | 1 |")

    def test_older_files_without_food_counts(self):
        old = game()
        del old["banked"], old["conceded"]
        code, out, _ = self.run_report(old)
        self.assertEqual(code, 0)
        self.assertIn("| baseline | RANDOM1 | 1 | 1/0/0 | 100.0% | 3.0 | - | - | 0 |", out)

    def test_only_errors(self):
        code, out, _ = self.run_report(game(error=True, outcome=None, score=None))
        self.assertEqual(code, 0)
        self.assertIn("| baseline | RANDOM1 | 1 | 0/0/0 | - | - | - | - | 1 |", out)

    def test_bad_input_names_file_and_line(self):
        for bad, message in (("{not json", ""),
                             (json.dumps(game(outcome="X")), "outcome"),
                             (json.dumps(game(outcome=[])), "outcome"),
                             (json.dumps(game(outcome={})), "outcome"),
                             (json.dumps(game(color=None)), "color"),
                             (json.dumps(game(score=1.5)), "score"),
                             (json.dumps(game(error="no")), "error"),
                             (json.dumps(game()), "twice"),
                             ("[1, 2]", "JSON object"),
                             (b"\xff", "utf-8")):
            with self.subTest(bad=bad):
                code, out, err = self.run_report(game(), "", bad)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("games.jsonl:3:", err)
                self.assertIn(message, err)

    def test_matches_the_published_final_results(self):
        # The README reports these totals for the fixed layouts.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(report.main([str(REPO / "results/final-fixed.jsonl")]), 0)
        self.assertIn("| baseline | **all** | 120 | 108/11/1 | 93.1% |", out.getvalue())
        self.assertIn("| agent | **all** | 120 | 59/25/36 | 56.1% |", out.getvalue())


class CompareTest(unittest.TestCase):
    def compare(self, before, after):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, games in (("before", before), ("after", after)):
                paths.append(str(Path(folder) / (name + ".jsonl")))
                Path(paths[-1]).write_text("".join(json.dumps(g) + "\n" for g in games))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = report.main(["--compare", *paths])
            return code, out.getvalue().splitlines()

    def test_identical_files_change_nothing(self):
        games = [game("RANDOM1", "red", outcome="W", score=3), game("RANDOM1", "blue", outcome="L", score=-1)]
        code, lines = self.compare(games, games)
        self.assertEqual(code, 0)
        self.assertEqual(lines[2], "| baseline | 2 | 0 | 0 | 50.0% | 50.0% | +0.00 +- 0.00 |")

    def test_pairs_games_and_skips_the_rest(self):
        before = [game("RANDOM1", "red", outcome="L", score=-2),
                  game("RANDOM1", "blue", outcome="W", score=1),
                  game("RANDOM2", "red", outcome="W", score=5),       # missing after
                  game("RANDOM3", "red", outcome="W", score=5)]
        after = [game("RANDOM1", "blue", outcome="W", score=1),        # order does not matter
                 game("RANDOM1", "red", outcome="W", score=1),
                 game("RANDOM3", "red", error=True, outcome="L", score=-9),
                 game("RANDOM4", "red", outcome="W", score=5)]        # missing before
        code, lines = self.compare(before, after)
        self.assertEqual(code, 0)
        # Changes +3 and 0: mean 1.5, standard deviation 2.12, margin 2 * 2.12 / sqrt(2) = 3.
        self.assertEqual(lines[2], "| baseline | 2 | 1 | 0 | 50.0% | 100.0% | +1.50 +- 3.00 |")
        self.assertEqual(lines[-1], "Skipped 3 games that only one file has or that ended in an error.")

    def test_one_game_has_no_margin(self):
        code, lines = self.compare([game(outcome="W", score=5)], [game(outcome="D", score=0)])
        self.assertEqual(code, 0)
        self.assertEqual(lines[2], "| baseline | 1 | 0 | 1 | 100.0% | 33.3% | -5.00 +- ? |")

    def test_needs_two_files(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            report.main(["--compare", "only.jsonl"])
        self.assertEqual(stop.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
