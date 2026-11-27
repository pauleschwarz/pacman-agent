"""Summarize an arena result file per opponent and layout, or compare two of them.

    venv/bin/python tools/report.py games.jsonl
    venv/bin/python tools/report.py --compare before.jsonl after.jsonl

The first form prints a Markdown table with one row per opponent and layout and
a total per opponent, so a weak layout stands out. Games with an error count
only in the Errors column. Points are 3 per win and 1 per draw, as a share of
the maximum.

The second form pairs the games both files finished (same opponent, layout,
color and seed), for example the current team and a changed copy run with the
same arena command. The score change comes with twice its standard error: a
change inside that margin is noise.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys

POINTS = {"W": 3, "D": 1, "L": 0}
KEY = ("opponent", "layout", "color", "seed")


def load(path):
    """Games of one arena file by (opponent, layout, color, seed).

    Raises ValueError naming the file and line of the first malformed game.
    """
    games = {}
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            try:
                line = raw.decode("utf-8")
                if not line.strip():
                    continue
                game = json.loads(line)
                check(game)
            except ValueError as problem:
                raise ValueError("%s:%d: %s" % (path, number, problem)) from None
            key = tuple(game[field] for field in KEY)
            if key in games:
                raise ValueError("%s:%d: the same game appears twice" % (path, number))
            games[key] = game
    return games


def check(game):
    if not isinstance(game, dict):
        raise ValueError("expected a JSON object")
    for field in KEY:
        if not isinstance(game.get(field), str) or not game[field]:
            raise ValueError("%s must be a nonempty string" % field)
    if not isinstance(game.get("error"), bool):
        raise ValueError("error must be true or false")
    if not game["error"]:
        outcome = game.get("outcome")
        if not isinstance(outcome, str) or outcome not in POINTS:
            raise ValueError("a finished game needs outcome W, D or L")
        if type(game.get("score")) is not int:
            raise ValueError("score must be an integer")
    # Older result files have no food counts.
    for field in ("banked", "conceded"):
        if field in game and not game["error"] and type(game[field]) is not int:
            raise ValueError("%s must be an integer" % field)


def share(games):
    """Points as a share of the maximum, or None without a finished game."""
    finished = [g for g in games if not g["error"]]
    if not finished:
        return None
    return sum(POINTS[g["outcome"]] for g in finished) / (3 * len(finished))


def row(opponent, layout, games):
    finished = [g for g in games if not g["error"]]
    count = {outcome: sum(g["outcome"] == outcome for g in finished) for outcome in POINTS}
    points = share(games)

    def mean(field):
        values = [g[field] for g in finished if field in g]
        return "%.1f" % (sum(values) / len(values)) if values else "-"
    return "| %s | %s | %d | %d/%d/%d | %s | %s | %s | %s | %d |" % (
        opponent, layout, len(games), count["W"], count["D"], count["L"],
        "-" if points is None else "%.1f%%" % (100 * points), mean("score"),
        mean("banked"), mean("conceded"),
        len(games) - len(finished))


def table(games):
    lines = ["| Opponent | Layout | Games | W/D/L | Points | Mean score | Banked | Conceded | Errors |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for opponent in sorted({key[0] for key in games}):
        mine = {key: game for key, game in games.items() if key[0] == opponent}
        for layout in sorted({key[1] for key in mine}):
            lines.append(row(opponent, layout, [g for key, g in mine.items() if key[1] == layout]))
        lines.append(row(opponent, "**all**", list(mine.values())))
    return "\n".join(lines)


def compare(before, after):
    lines = ["| Opponent | Games | Better | Worse | Points before | Points after | Score change |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    paired = {key for key in set(before) & set(after) if not before[key]["error"] and not after[key]["error"]}
    for opponent in sorted({key[0] for key in paired}):
        keys = sorted(key for key in paired if key[0] == opponent)
        gain = [POINTS[after[k]["outcome"]] - POINTS[before[k]["outcome"]] for k in keys]
        change = [after[k]["score"] - before[k]["score"] for k in keys]
        # One game has no spread, so no margin either.
        margin = "+- %.2f" % (2 * statistics.stdev(change) / len(change) ** 0.5) if len(change) > 1 else "+- ?"
        lines.append("| %s | %d | %d | %d | %.1f%% | %.1f%% | %+.2f %s |" % (
            opponent, len(keys), sum(g > 0 for g in gain), sum(g < 0 for g in gain),
            100 * share([before[k] for k in keys]), 100 * share([after[k] for k in keys]),
            sum(change) / len(change), margin))
    skipped = len(set(before) | set(after)) - len(paired)
    lines.append("")
    lines.append("Skipped %d games that only one file has or that ended in an error." % skipped)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, nargs="+", help="JSON lines written by tools/arena.py --out")
    parser.add_argument("--compare", action="store_true", help="compare two files that played the same games")
    args = parser.parse_args(argv)
    if len(args.results) != (2 if args.compare else 1):
        parser.error("give one result file, or two with --compare")
    try:
        files = [load(path) for path in args.results]
    except (OSError, ValueError) as problem:
        print(problem, file=sys.stderr)
        return 1
    print(compare(*files) if args.compare else table(files[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
