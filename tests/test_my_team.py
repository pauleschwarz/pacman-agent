"""Checks for my_team.py on real contest games. From the repository root:

    venv/bin/python -m unittest discover -s tests -v
"""
import contextlib
import io
from pathlib import Path
import random
import sys
from time import perf_counter
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from contest import capture  # noqa: E402
from contest.baseline_team import create_team as baseline_team  # noqa: E402
from contest.game import Actions  # noqa: E402
from contest.layout import Layout  # noqa: E402
from contest.text_display import NullGraphics  # noqa: E402
import my_team  # noqa: E402

my_team.STRICT = True  # a bug must fail the test instead of being logged
LAYOUTS = REPO / "pacman-contest/src/contest/layouts"


def load(name):
    if name.startswith("RANDOM"):
        text = capture.random_layout(int(name[6:]))[1]
        return Layout(name, text.split("\n"))
    return Layout(name, (LAYOUTS / (name + ".lay")).read_text().splitlines())


def play(red, blue, layout, games=1, seed="test"):
    """Plays without catching exceptions, so an illegal action or a crash raises."""
    random.seed(seed)
    agents = [red[0], blue[0], red[1], blue[1]]
    with contextlib.redirect_stdout(io.StringIO()):
        return capture.run_games([load(layout)] * games, agents, NullGraphics(), 1200, games,
                                 False, 0, "red", "blue")


def ours(is_red):
    return my_team.create_team(0, 2, True) if is_red else my_team.create_team(1, 3, False)


def baseline(is_red):
    return baseline_team(0, 2, True) if is_red else baseline_team(1, 3, False)


class CreateTeamTest(unittest.TestCase):
    def test_two_agents_share_one_team(self):
        for first, second, is_red in ((0, 2, True), (1, 3, False)):
            a, b = my_team.create_team(first, second, is_red)
            self.assertEqual((a.index, b.index), (first, second))
            self.assertEqual((a.role, b.role), ("Raider", "Guard"))
            self.assertIs(a.team, b.team)


class PocketTest(unittest.TestCase):
    def test_dead_end_cells_map_to_their_junction(self):
        # A loop a-b-c-d with a corridor d-e-f hanging off d.
        links = {"a": "bd", "b": "ac", "c": "bd", "d": "ace", "e": "df", "f": "e"}
        neighbors = {p: [(None, q) for q in qs] for p, qs in links.items()}
        self.assertEqual(my_team.pocket_exits(neighbors), {"e": "d", "f": "d"})


class EscapeTest(unittest.TestCase):
    """A corridor: home cell x=0, enemy cells x=1..4, a ghost standing at x=4."""

    def setUp(self):
        cells = [(x, 0) for x in range(5)]
        neighbors = {p: [("West", (p[0] - 1, 0))] * (p[0] > 0) + [("East", (p[0] + 1, 0))] * (p[0] < 4)
                     for p in cells}
        self.agent = my_team.TeamAgent(0, my_team.Team(), "Raider")
        self.agent.maze = SimpleNamespace(neighbors=neighbors, home=lambda p: p[0] == 0)
        self.threat = {(x, 0): 4 - x for x in range(1, 5)}  # the ghost's distance to each cell

    def test_slack_is_the_latest_safe_arrival(self):
        slack = self.agent.escape_slack(self.threat)
        # Reaching x=1 by turn 2 still lets us step home before the ghost arrives there at turn 3.
        self.assertEqual([slack[(x, 0)] for x in range(1, 5)], [2, 1, 0, -1])

    def test_reach_stops_where_the_ghost_is_first(self):
        arrive, first = self.agent.safe_reach((0, 0), ["East", "Stop"], self.threat)
        self.assertEqual(arrive, {(0, 0): 0, (1, 0): 1})
        self.assertEqual(first, {(1, 0): "East"})


class GameTest(unittest.TestCase):
    def test_full_games_on_every_layout_kind(self):
        # Fixed layouts of all sizes and random mazes, both colors, against the course baseline.
        for layout in ("defaultCapture", "tinyCapture", "testCapture", "jumboCapture", "alleyCapture",
                       "bloxCapture", "officeCapture", "RANDOM1", "RANDOM77"):
            for is_red in (True, False):
                with self.subTest(layout=layout, red=is_red):
                    red, blue = (ours(True), baseline(False)) if is_red else (baseline(True), ours(False))
                    game, = play(red, blue, layout)
                    self.assertFalse(game.agent_crashed)
                    self.assertTrue(game.state.is_over())

    def test_decisions_stay_fast(self):
        team = ours(True)
        times = []
        for agent in team:
            decide = agent.choose_action

            def timed(state, decide=decide):
                start = perf_counter()
                action = decide(state)
                times.append(perf_counter() - start)
                return action
            agent.choose_action = timed
        play(team, baseline(False), "jumboCapture")
        # The contest allows one second; the margin covers a slower, shared cluster.
        self.assertLess(max(times), 0.2)

    def test_tracker_never_rules_out_the_true_position(self):
        for layout, is_red in (("RANDOM5", True), ("defaultCapture", False)):
            team = ours(is_red)
            truth = {}
            checked = []

            for agent in team:
                observe, decide = agent.observation_function, agent.choose_action

                def observation(state, observe=observe):
                    truth.update({i: state.get_agent_position(i) for i in range(4)})
                    return observe(state)

                def checked_decision(state, decide=decide, agent=agent):
                    action = decide(state)
                    for i, belief in agent.team.tracker.belief.items():
                        self.assertGreater(belief.get(truth[i], 0), 0, (layout, i, truth[i]))
                        self.assertAlmostEqual(sum(belief.values()), 1)
                    checked.append(1)
                    return action
                agent.observation_function = observation
                agent.choose_action = checked_decision
            red, blue = (team, baseline(False)) if is_red else (baseline(True), team)
            play(red, blue, layout)
            self.assertGreater(len(checked), 200)

    def test_raider_avoids_ghosts_when_it_can(self):
        # Stepping next to an active ghost on its side invites capture; only a forced move may do it.
        def exposed(agent, state, action):
            q = Actions.get_successor(state.get_agent_position(agent.index), action)
            return (not agent.maze.home(q) and q not in agent.get_capsules(state) and
                    any(g.scared_timer <= 1 and agent.get_maze_distance(q, g.get_position()) <= 1
                        for g in agent.visible(state, invaders=False)))

        violations, moves = [], []
        for layout in ("RANDOM2", "RANDOM9", "defaultCapture"):
            team = ours(True)
            raider = team[0]
            decide = raider.choose_action

            def checked(state, decide=decide):
                action = decide(state)
                legal = state.get_legal_actions(raider.index)
                if exposed(raider, state, action) and not all(exposed(raider, state, a) for a in legal):
                    violations.append((layout, state.data.timeleft, action))
                moves.append(1)
                return action
            raider.choose_action = checked
            play(team, baseline(False), layout)
        self.assertGreater(len(moves), 500)
        self.assertEqual(violations, [])

    def test_second_game_in_one_process_starts_fresh(self):
        team = ours(True)
        trackers = []
        register = team[0].register_initial_state

        def remember(state):
            register(state)
            trackers.append(team[0].team.tracker)
        team[0].register_initial_state = remember
        games = play(team, baseline(False), "RANDOM3", games=2)
        self.assertEqual(len(games), 2)
        self.assertIsNot(trackers[0], trackers[1])
        self.assertFalse(any(g.agent_crashed for g in games))


if __name__ == "__main__":
    unittest.main()
