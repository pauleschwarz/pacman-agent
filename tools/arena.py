"""Play many headless matches in parallel and report results from one team's view.

    venv/bin/python tools/arena.py my_team.py baseline --layouts RANDOM1-20 --jobs 8
    venv/bin/python tools/arena.py my_team.py baseline --layouts tinyCapture --replays replays

Every match runs in its own process with time enforcement (-c). Each layout is
played twice with the same game seed, once per color. A match counts as an
error when the engine reports a crash, timeout or time warning, when a
traceback reaches the log, or when the process fails.
"""
import argparse
import hashlib
from itertools import product
import json
import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import subprocess
import sys
from time import perf_counter

REPO = Path(__file__).resolve().parent.parent
CONTEST = REPO / "pacman-contest/src/contest"
FIXED = sorted(p.stem for p in (CONTEST / "layouts").glob("*Capture.lay"))


def team_path(name):
    if name == "baseline":
        return CONTEST / "baseline_team.py"
    return Path(name).resolve()


def label(path):
    if path == CONTEST / "baseline_team.py":
        return "baseline"
    return path.parent.name if path.name == "my_team.py" else path.stem


def expand(spec):
    """'RANDOM1-3,defaultCapture,fixed' -> list of layout names."""
    layouts = []
    for part in spec.split(","):
        if part == "fixed":
            layouts += FIXED
        elif part.startswith("RANDOM") and "-" in part:
            low, high = part[6:].split("-")
            layouts += ["RANDOM%d" % n for n in range(int(low), int(high) + 1)]
        else:
            layouts.append(part)
    return layouts


def play_one(red, blue, layout, seed, replay=""):
    """Runs inside the child process and prints one JSON line."""
    from contest import capture, game as engine
    path = layout if layout.startswith("RANDOM") else str(CONTEST / "layouts" / (layout + ".lay"))
    options = capture.read_command(["-r", red, "-b", blue, "-l", path, "-q", "-c", "-i", "1200",
                                    "--delay-step", "0", "--setRandomSeed", seed])
    random.seed(seed)  # building a RANDOM layout reseeds the global generator
    inits = [[] for _ in options["agents"]]
    moves = [[] for _ in options["agents"]]
    for agent, init, move in zip(options["agents"], inits, moves):
        agent.register_initial_state = timed(agent.register_initial_state, init)
        agent.choose_action = timed(agent.choose_action, move)
    game, = capture.run_games(**options)
    if replay:
        # The same record capture.py --record writes, so capture.py --replay can show the game.
        record = dict(layout=options["layouts"][0], agents=[engine.Agent() for _ in options["agents"]],
                      actions=game.move_history, length=options["length"],
                      red_team_name=options["red_team_name"], blue_team_name=options["blue_team_name"])
        Path(replay).write_bytes(pickle.dumps(record))
    team_moves = [sorted(moves[0] + moves[2]), sorted(moves[1] + moves[3])]
    agents = game.state.data.agent_states
    print(json.dumps(dict(
        score=game.state.get_score(), moves=len(game.move_history),
        digest=hashlib.sha256(json.dumps(game.move_history).encode()).hexdigest()[:16],
        returned=[agents[0].num_returned + agents[2].num_returned, agents[1].num_returned + agents[3].num_returned],
        crashed=game.agent_crashed, timeout=game.agent_timeout,
        warnings=game.total_agent_time_warnings,
        init_time=[max(inits[0] + inits[2], default=0), max(inits[1] + inits[3], default=0)],
        max_time=[t[-1] if t else 0 for t in team_moves],
        p99_time=[t[int(0.99 * (len(t) - 1))] if t else 0 for t in team_moves])))


def timed(function, samples):
    def call(*args):
        start = perf_counter()
        try:
            return function(*args)
        finally:
            samples.append(perf_counter() - start)
    return call


def match(team, opponent, layout, color, timeout, seed, replay=None):
    red, blue = (team, opponent) if color == "red" else (opponent, team)
    cmd = [sys.executable, __file__, "--one", str(red), str(blue), layout, seed]
    if replay is not None:
        cmd.append(str(replay))
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=REPO)
        stdout, output, code = done.stdout, done.stdout + done.stderr, done.returncode
    except subprocess.TimeoutExpired as expired:
        stdout, output, code = "", str(expired.stdout or "") + str(expired.stderr or ""), "timeout"
    row = dict(opponent=label(opponent), layout=layout, color=color, seed=seed, exit=code)
    try:
        # The result is the last line on stdout; engine warnings go to stderr.
        result = json.loads(stdout.strip().splitlines()[-1]) if code == 0 else {}
    except (IndexError, ValueError):
        result = {}
    ours = 0 if color == "red" else 1
    sign = 1 if color == "red" else -1
    # A crash or timeout of either side invalidates the game; a time warning counts only for us.
    error = (not result or "Traceback" in output or result["crashed"] or result["timeout"]
             or any(result["warnings"][ours::2]))
    row.update(error=bool(error), log=output[-3000:] if error else "")
    if result:
        score = sign * result["score"]
        row.update(score=score, outcome="W" if score > 0 else "L" if score < 0 else "D",
                   moves=result["moves"], digest=result["digest"], banked=result["returned"][ours],
                   conceded=result["returned"][1 - ours], init_time=result["init_time"][ours],
                   max_time=result["max_time"][ours], p99_time=result["p99_time"][ours],
                   warnings=sum(result["warnings"][ours::2]),
                   opponent_error=bool(result["crashed"] or result["timeout"]
                                       or any(result["warnings"][1 - ours::2])))
    return row


def summarize(rows):
    by_opponent = {}
    for row in rows:
        by_opponent.setdefault(row["opponent"], []).append(row)
    for name, games in by_opponent.items():
        count = lambda outcome: sum(g.get("outcome") == outcome and not g["error"] for g in games)
        scores = [g["score"] for g in games if "score" in g]
        errors = sum(g["error"] for g in games)
        slowest = lambda key: max((g.get(key, 0) for g in games), default=0)
        mean = lambda key: sum(g.get(key, 0) for g in games) / max(1, len(scores))
        print("%-12s games %3d  W/D/L %3d/%3d/%3d  points %5.1f%%  mean %+6.2f (banked %5.2f conceded %5.2f)"
              "  errors %d  slowest move %.3fs init %.3fs"
              % (name, len(games), count("W"), count("D"), count("L"),
                 100 * (3 * count("W") + count("D")) / (3 * max(1, len(games))), sum(scores) / max(1, len(scores)),
                 mean("banked"), mean("conceded"), errors, slowest("max_time"), slowest("init_time")))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--one":
        play_one(*sys.argv[2:])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("team")
    parser.add_argument("opponents", nargs="+")
    parser.add_argument("--layouts", default="RANDOM1-10")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--repeat", type=int, default=1, help="games per layout and color, each with its own seed")
    parser.add_argument("--seed", default="arena", help="prefix of every game seed")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--replays", type=Path, help="folder for a replay of every game, for capture.py --replay; one folder per run, "
                        "since a second run overwrites replays of the same games")
    args = parser.parse_args()
    team = team_path(args.team)
    opponents = [team_path(name) for name in args.opponents]
    replay_dir = args.replays.resolve() if args.replays else None
    tasks = []
    identities = set()
    replay_paths = set()
    for opponent, layout, repeat, color in product(opponents, expand(args.layouts), range(args.repeat), ("red", "blue")):
        name = label(opponent)
        seed = args.seed + "-" + layout + ("-%d" % repeat if repeat else "")
        identity = (name, layout, color, seed)
        if identity in identities:
            parser.error("duplicate game identity: %r; use distinct opponent labels and layouts" % (identity,))
        identities.add(identity)

        replay = None
        if replay_dir is not None:
            replay = replay_dir / ("%s-%s-%s.replay" % (name, seed, color))
            # Keep replay names distinct on case-insensitive filesystems too.
            path_key = str(replay.resolve()).casefold()
            if path_key in replay_paths:
                parser.error("replay filename collision: %s" % replay)
            replay_paths.add(path_key)
        tasks.append((team, opponent, layout, color, args.timeout, seed, replay))
    if replay_dir is not None:
        replay_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda task: match(*task), tasks))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w") as stream:
            for row in rows:
                print(json.dumps(row), file=stream)
    for row in rows:
        if row["error"]:
            print("ERROR", row["opponent"], row["layout"], row["color"], row["exit"], file=sys.stderr)
    summarize(rows)
    sys.exit(1 if any(row["error"] for row in rows) else 0)


if __name__ == "__main__":
    main()
