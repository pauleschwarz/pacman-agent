# my_team.py
# ---------------
# Licensing Information: Please do not distribute or publish solutions to this
# project. You are free to use and extend these projects for educational
# purposes. The Pacman AI projects were developed at UC Berkeley, primarily by
# John DeNero (denero@cs.berkeley.edu) and Dan Klein (klein@cs.berkeley.edu).
# For more info, see http://inst.eecs.berkeley.edu/~cs188/sp09/pacman.html

"""Capture-the-flag team: a raider collects food, a guard defends the border.

Both agents share one map analysis and one belief over hidden opponent
positions. Each turn adds the acting agent's own sonar reading to that belief.
The README explains every rule and the measurements behind it.
"""

from collections import Counter, deque
from heapq import heappop, heappush
import traceback

from contest.capture_agents import CaptureAgent
from contest.game import Actions, Directions
from contest.util import manhattan_distance

SIGHT = 5            # rules 2.5: opponents within this Manhattan distance are visible
LAST_FOOD = 2        # rules 2.6: the game ends when a side is down to two pellets
ENDGAME = 50         # own turns left when the roles start to depend on the score

# Raider
NEAR = 5             # steps within which a ghost, or home, counts as near
FEAR_END = 3         # a scared ghost with this few turns of fear left already counts as dangerous
LOAD = 8             # carried pellets worth banking once capsule protection runs short
SPARE = 3            # own turns kept in reserve for the way home
CAPSULE_SPARE = 6    # a second capsule is saved while the first still covers the trip plus this
CAPSULE_BONUS = 2    # preference for a capsule over food, in steps
CAPSULE_RUSH = 8     # the same preference with a dangerous ghost near
STICKY = 1           # preference for the current target, in steps
RECENT = 8           # positions remembered; revisiting one costs a step more
NEXT_TO_GHOST = 45   # extra route cost of an enemy cell next to an active ghost
NEAR_GHOST = 8       # extra route cost two steps from it
TRAP = 30            # extra route cost of entering a pocket whose exit the ghost reaches first

# Guard
HELP_CARGO = 5       # a visible invader carrying this much calls the raider back
REGION = 10          # the guard contests cells within this many steps of an invader
FOOD_WEIGHT = 2      # extra weight of our food in the invader's region
GATE_WEIGHT = 3      # extra weight of our gates once the invader carries food
CLUE_TURNS = 6       # own turns a missing pellet or a last sighting stays a destination
SHADOW = 2           # distance a scared guard keeps from a visible invader
RAID_CARGO = 2       # a scared guard on a raid heads home with this many pellets
RAID_SPARE = 2       # moves a scared guard keeps in reserve for its round trip
GUARD_SPACE = 3      # a helping raider leaves gates this close to the guard to the guard

INF = 10 ** 6
STRICT = False       # tests set this so that a bug raises instead of being logged


def create_team(first_index, second_index, is_red, first="Raider", second="Guard", num_training=0):
    team = Team()
    return [TeamAgent(first_index, team, first), TeamAgent(second_index, team, second)]


class Team:
    """State the two agents of one team share during a game."""

    def __init__(self):
        self.maze = None
        self.tracker = None
        self.helping = False  # the raider defends this turn
        self.joined = set()

    def join(self, agent, state):
        # An agent registering a second time means a new game in the same process.
        if self.maze is None or agent.index in self.joined:
            self.maze = Maze(state, agent.red, agent.get_maze_distance)
            self.tracker = Tracker(state, self.maze, agent.get_opponents(state), agent.get_team(state))
            self.helping = False
            self.joined = set()
        self.joined.add(agent.index)


class Maze:
    """Static facts about the map, seen from one team."""

    def __init__(self, state, red, distance):
        walls = state.get_walls()
        self.red = red
        self.middle = walls.width // 2
        self.neighbors = {}
        for p in walls.as_list(False):
            self.neighbors[p] = [(Actions.vector_to_direction((q[0] - p[0], q[1] - p[1])), q)
                                 for q in Actions.get_legal_neighbors(p, walls) if q != p]
        # Gates are our border cells with an open neighbour on the enemy side.
        self.gates = [p for p, edges in self.neighbors.items()
                      if self.home(p) and any(not self.home(q) for _, q in edges)]
        self.nearest_gate = {p: min(self.gates, key=lambda g: distance(p, g)) for p in self.neighbors}
        self.center = min(self.gates, key=lambda g: sum(distance(g, h) for h in self.gates))
        self.exit = pocket_exits(self.neighbors)

    def home(self, p):
        return (p[0] < self.middle) == self.red


def pocket_exits(neighbors):
    """Peel dead ends. Each removed cell maps to the cell where its pocket meets the loops."""
    degree = {p: len(edges) for p, edges in neighbors.items()}
    leaves = deque(p for p in degree if degree[p] == 1)
    parent = {}
    while leaves:
        p = leaves.popleft()
        degree[p] = 0
        for _, q in neighbors[p]:
            if degree[q]:
                parent[p] = q
                degree[q] -= 1
                if degree[q] == 1:
                    leaves.append(q)
                break
    exits = {}
    for p, q in reversed(list(parent.items())):
        exits[p] = exits.get(q, q)
    return exits


class Tracker:
    """Exact Bayes filter over the cells each hidden opponent can occupy.

    Predict: an opponent that moved since the last update stays or steps to a
    neighbour with equal probability. Observe: drop cells that contradict its
    Pacman/ghost role, our two lines of sight or the acting agent's sonar.
    """

    def __init__(self, state, maze, opponents, team):
        self.maze = maze
        self.opponents = opponents
        self.team = team
        self.start = {i: state.get_initial_agent_position(i) for i in opponents}
        self.belief = {i: {self.start[i]: 1.0} for i in opponents}
        self.clock = None

    def update(self, state, index):
        # timeleft counts global moves, so it tells which agents moved since our last update.
        clock = state.data.timeleft
        if self.clock is None:
            movers = set(self.opponents)
        else:
            count = state.get_num_agents()
            movers = {(index - k) % count for k in range(1, min(self.clock - clock, count) + 1)}
        self.clock = clock
        me = state.get_agent_position(index)
        friends = [state.get_agent_position(i) for i in self.team]
        readings = state.get_agent_distances()
        for i in self.opponents:
            seen = state.get_agent_position(i)
            if seen is not None:
                self.belief[i] = {seen: 1.0}
                continue
            pacman = state.get_agent_state(i).is_pacman
            reading = readings[i] if readings and i < len(readings) else None

            def possible(cell):
                return (self.maze.home(cell) == pacman
                        and all(manhattan_distance(cell, f) > SIGHT for f in friends)
                        and (reading is None or state.get_distance_prob(manhattan_distance(me, cell), reading) > 0))

            belief = self.elapse(self.belief[i]) if i in movers else self.belief[i]
            belief = {p: w for p, w in belief.items() if possible(p)}
            if not belief:
                # Only a respawn moves an opponent farther than one step. It may have moved once since.
                belief = {p: w for p, w in self.elapse({self.start[i]: 1.0}).items() if possible(p)}
            if not belief:
                belief = {p: 1.0 for p in self.maze.neighbors if possible(p)}
            total = sum(belief.values())
            self.belief[i] = {p: w / total for p, w in belief.items()} if total else {self.start[i]: 1.0}

    def elapse(self, belief):
        result = Counter()
        for p, w in belief.items():
            moves = self.maze.neighbors[p]
            share = w / (len(moves) + 1)
            result[p] += share
            for _, q in moves:
                result[q] += share
        return result


class TeamAgent(CaptureAgent):
    def __init__(self, index, team, role):
        super().__init__(index)
        self.team = team
        self.role = role

    def register_initial_state(self, state):
        super().register_initial_state(state)
        self.start = state.get_agent_position(self.index)
        self.recent = deque(maxlen=RECENT)
        self.target = None
        self.food = set(self.get_food_you_are_defending(state).as_list())
        self.clue = None
        self.expiry = 0
        try:
            self.team.join(self, state)
        except Exception:
            # A map we cannot analyse (say, no crossing at all) must not forfeit the game.
            # Without the analysis choose_action falls back to legal moves.
            if STRICT:
                raise
            traceback.print_exc()
            self.team.maze = self.team.tracker = None
        self.maze = self.team.maze

    def choose_action(self, state):
        # The base class keeps every observation; we never read old ones.
        del self.observation_history[:-1]
        legal = state.get_legal_actions(self.index)
        try:
            self.team.tracker.update(state, self.index)
            self.note_clues(state)
            lead = self.get_score(state)
            endgame = self.turns_left(state) <= ENDGAME
            if self.role == "Guard":
                # Behind at the end, a second raider is worth more than a guard.
                action = self.raid(state, legal) if endgame and lead < 0 else self.guard(state, legal)
            elif endgame and lead > 0:
                # Ahead at the end, bank what we carry and help protect the lead.
                action = self.bank(state, legal)
                self.team.helping = not action
                action = action or self.defend(state, legal)
            else:
                self.team.helping = self.must_help(state)
                action = self.defend(state, legal) if self.team.helping else self.raid(state, legal)
        except Exception:
            # A crash forfeits the game. Log the bug and play a legal move instead.
            if STRICT:
                raise
            traceback.print_exc()
            action = None
        if action in legal:
            return action
        return Directions.STOP if Directions.STOP in legal else legal[0]

    # Shared helpers -------------------------------------------------------

    def visible(self, state, invaders):
        enemies = (state.get_agent_state(i) for i in self.get_opponents(state))
        return [e for e in enemies if e.get_position() is not None and e.is_pacman == invaders]

    def must_help(self, state):
        """A raider on our side turns back for a visible invader carrying a lot.

        One ghost rarely catches a Pacman that keeps moving away from it; two usually do.
        """
        me = state.get_agent_state(self.index)
        return (not me.is_pacman and not me.scared_timer and
                any(e.num_carrying >= HELP_CARGO for e in self.visible(state, invaders=True)))

    def bank(self, state, legal):
        """Cheapest risk-aware route home for a Pacman, or None on our side."""
        if not state.get_agent_state(self.index).is_pacman:
            return None
        pos = state.get_agent_position(self.index)
        costs, first = self.routes(pos, legal, self.visible(state, invaders=False),
                                   set(self.get_capsules(state)))
        gates = [gate for gate in self.maze.gates if gate in first]
        return first[min(gates, key=lambda g: (costs[g], g))] if gates else None

    def home_step(self, pos, goal, legal):
        """First action of a shortest path to goal that stays on our side, or None."""
        queue = deque([(pos, Directions.STOP)])
        seen = {pos}
        while queue:
            p, first = queue.popleft()
            if p == goal:
                return first
            for direction, q in self.maze.neighbors[p]:
                if q not in seen and self.maze.home(q) and (p != pos or direction in legal):
                    seen.add(q)
                    queue.append((q, direction if p == pos else first))
        return None

    def turns_left(self, state):
        return state.data.timeleft // state.get_num_agents()

    # Raider ---------------------------------------------------------------

    def raid(self, state, legal):
        pos = state.get_agent_position(self.index)
        if len(legal) == 1:
            return legal[0]
        self.recent.append(pos)
        me = state.get_agent_state(self.index)
        ghosts = self.visible(state, invaders=False)
        food = self.get_food(state).as_list()
        caps = set(self.get_capsules(state))
        dist = self.get_maze_distance
        home = min(dist(pos, gate) for gate in self.maze.gates)
        close = any(dist(pos, g.get_position()) <= NEAR and g.scared_timer <= FEAR_END for g in ghosts)
        # During capsule protection even an unseen opponent's timer is observable.
        protection = min(state.get_agent_state(i).scared_timer for i in self.get_opponents(state))
        # Nobody defends while both opponents are Pacmen on our side, so a full load is not yet a reason to bank.
        defended = not all(state.get_agent_state(i).is_pacman for i in self.get_opponents(state))
        full = me.num_carrying >= LOAD and protection <= home + SPARE and defended
        bank = me.num_carrying and (full or len(food) <= LAST_FOOD or self.turns_left(state) <= home + SPARE
                                    or (close and home <= NEAR))
        # Save the next capsule while the first still covers the trip and a short retreat.
        useful_caps = [p for p in sorted(caps) if protection <= dist(pos, p) + CAPSULE_SPARE]

        if ghosts:
            # With a ghost in sight, prefer targets we provably reach first and can still escape from.
            threat = self.threat(state)
            arrive, first = self.safe_reach(pos, legal, threat)
            slack = self.escape_slack(threat)
            if bank:
                goals = [q for q in first if self.maze.home(q)]
            else:
                goals = [f for f in food if f in first and arrive[f] <= slack[f]]
                goals += [c for c in useful_caps if c in first]
            if goals:
                def eta(p):
                    return arrive[p] - self.bonus(p, caps, close, bank), p
                self.target = min(goals, key=eta)
                return first[self.target]

        # Otherwise take the cheapest route by risk-weighted cost.
        def safe(action):
            # Reject an exposed first step whenever a safer legal action exists.
            q = Actions.get_successor(pos, action)
            return (self.maze.home(q) or q in caps or
                    all(g.scared_timer > 1 or dist(q, g.get_position()) > 1 for g in ghosts))

        allowed = [action for action in legal if safe(action)] or legal
        costs, first = self.routes(pos, allowed, ghosts, caps)
        goals = self.maze.gates if bank or not food else food + useful_caps
        reachable = [p for p in goals if p in first]
        if not reachable:
            return Directions.STOP if Directions.STOP in allowed else allowed[0]

        def priority(p):
            return costs[p] - self.bonus(p, caps, close, bank), dist(pos, p), p

        self.target = min(reachable, key=priority)
        return first[self.target]

    def bonus(self, p, caps, close, bank):
        """Steps a target may cost extra: capsules are worth a detour, more so with a ghost near,
        and keeping the current target avoids dithering between equal choices."""
        capsule = (CAPSULE_RUSH if close else CAPSULE_BONUS) if p in caps and not bank else 0
        return capsule + STICKY * (p == self.target)

    def threat(self, state):
        """Earliest turn at which a visible opponent can stand on each enemy-side cell.

        A scared ghost is harmless until its timer runs out, so its threat starts no earlier.
        """
        threat = {}
        for i in self.get_opponents(state):
            p = state.get_agent_position(i)
            if p is None:
                continue
            timer = state.get_agent_state(i).scared_timer
            for q in self.maze.neighbors:
                if not self.maze.home(q):
                    t = max(self.get_maze_distance(p, q), timer)
                    if t < threat.get(q, INF):
                        threat[q] = t
        return threat

    def safe_reach(self, pos, legal, threat):
        """Breadth-first search over cells we reach strictly before any visible opponent."""
        arrive = {pos: 0}
        first = {}
        frontier = deque([pos])
        while frontier:
            p = frontier.popleft()
            for direction, q in self.maze.neighbors[p]:
                if q in arrive or (p == pos and direction not in legal):
                    continue
                t = arrive[p] + 1
                if t >= threat.get(q, INF) and not self.maze.home(q):
                    continue
                arrive[q] = t
                first[q] = direction if p == pos else first[p]
                frontier.append(q)
        return arrive, first

    def escape_slack(self, threat):
        """Latest arrival time at each cell from which we still reach home before every opponent.

        slack(home) is unbounded; for an enemy cell q,
        slack(q) = min(threat(q) - 1, max over neighbours r of slack(r) - 1).
        """
        slack = {q: INF for q in self.maze.neighbors if self.maze.home(q)}
        queue = [(-INF, q) for q in slack]
        while queue:
            s, p = heappop(queue)
            if -s != slack[p]:
                continue
            for _, q in self.maze.neighbors[p]:
                if self.maze.home(q):
                    continue
                value = min(threat.get(q, INF) - 1, slack[p] - 1)
                if value > slack.get(q, -INF):
                    slack[q] = value
                    heappush(queue, (-value, q))
        return slack

    def routes(self, pos, legal, ghosts, caps):
        """Dijkstra from pos. Returns the cost to each cell and the first action on its cheapest route."""
        dist = self.get_maze_distance
        costs = {pos: 0}
        first = {}
        queue = [(0, pos)]
        while queue:
            cost, p = heappop(queue)
            if cost != costs[p]:
                continue
            for direction, q in self.maze.neighbors[p]:
                if q == pos or (p == pos and direction not in legal):
                    continue
                step = 1 + self.recent.count(q)
                if ghosts and not self.maze.home(q) and q not in caps:
                    arrival = dist(pos, q)
                    for g in ghosts:
                        if g.scared_timer > arrival + 1:
                            continue
                        gap = dist(g.get_position(), q)
                        step += NEXT_TO_GHOST if gap <= 1 else NEAR_GHOST if gap == 2 else 0
                        # A pocket is a trap if the ghost reaches its exit before we get in and back out.
                        mouth = self.maze.exit.get(q)
                        if mouth and self.maze.exit.get(p) != mouth:
                            if dist(g.get_position(), mouth) <= arrival + 2 * dist(q, mouth):
                                step += TRAP
                new_cost = cost + step
                if new_cost < costs.get(q, INF):
                    costs[q] = new_cost
                    first[q] = direction if p == pos else first[p]
                    heappush(queue, (new_cost, q))
        return costs, first

    # Guard ----------------------------------------------------------------

    def guard(self, state, legal):
        patrol = self.defend(state, legal)
        me = state.get_agent_state(self.index)
        if not me.scared_timer and not me.is_pacman:
            return patrol
        # A scared guard cannot catch anyone, so it raids if a round trip fits the window.
        pos = state.get_agent_position(self.index)
        dist = self.get_maze_distance
        turns = min(me.scared_timer, self.turns_left(state))
        if not me.is_pacman:
            food = self.get_food(state).as_list()
            if not any(dist(pos, p) + dist(p, self.maze.nearest_gate[p]) + RAID_SPARE < turns for p in food):
                return patrol
        elif me.num_carrying >= RAID_CARGO or turns <= min(dist(pos, gate) for gate in self.maze.gates) + RAID_SPARE:
            return self.bank(state, legal) or patrol
        action = self.raid(state, legal)
        step = Actions.get_successor(pos, action)
        if self.maze.home(step) and any(dist(step, e.get_position()) <= 1
                                        for e in self.visible(state, invaders=True)):
            return patrol
        return action

    def note_clues(self, state):
        """Remember where an invader was last seen or last ate our food."""
        pos = state.get_agent_position(self.index)
        if pos == self.start:
            self.recent.clear()
            self.target = None
        invaders = [e.get_position() for e in self.visible(state, invaders=True)]
        food = set(self.get_food_you_are_defending(state).as_list())
        missing = self.food - food
        self.food = food
        if invaders or missing:
            self.clue = min(invaders or missing, key=lambda p: (self.get_maze_distance(pos, p), p))
            self.expiry = state.data.timeleft - CLUE_TURNS * state.get_num_agents()
        elif pos == self.clue or state.data.timeleft <= self.expiry or pos == self.start:
            self.clue = None

    def defend(self, state, legal):
        post = self.patrol_gate(state)
        pos = state.get_agent_position(self.index)
        options = [(a, Actions.get_successor(pos, a)) for a in legal]
        options = [(a, q) for a, q in options if self.maze.home(q)] or options
        dist = self.get_maze_distance
        invaders = [e.get_position() for e in self.visible(state, invaders=True)]
        if invaders and state.get_agent_state(self.index).scared_timer > 0:
            # Shadow from two steps away, close enough to pursue when the timer expires.
            def shadow(option):
                gap = min(dist(option[1], p) for p in invaders)
                return gap < SHADOW, abs(gap - SHADOW), dist(option[1], post)
            return min(options, key=shadow)[0]
        if invaders:
            for action, q in options:
                if q in invaders:
                    return action
            return min(options, key=self.pressure(state, pos))[0]
        goal = self.clue or self.likely_invader(state, pos) or post
        # A shortcut across the border would turn the guard into a harmless Pacman.
        return (self.home_step(pos, goal, legal)
                or min(options, key=lambda option: dist(option[1], goal))[0])

    def likely_invader(self, state, pos):
        """Most probable cell of the nearest hidden invader, or None if nobody is on our side."""
        cells = []
        for i in self.get_opponents(state):
            if state.get_agent_state(i).is_pacman:
                belief = self.team.tracker.belief[i]
                cells.append(max(belief, key=lambda p: (belief[p], p)))
        return min(cells, key=lambda p: (self.get_maze_distance(pos, p), p)) if cells else None

    def pressure(self, state, pos):
        """Sort key for chasing the nearest visible invader.

        First keep it from reaching a capsule before us. Then shrink what it can
        still reach before us or a defending teammate within REGION steps: every
        cell counts, food more, and gates too once it carries food it could bank.
        Then get closer. Counting the whole half instead made the guard hold
        far-away chokepoints on large maps while the invader ate nearby.
        """
        dist = self.get_maze_distance
        invader = min(self.visible(state, invaders=True),
                      key=lambda e: (dist(pos, e.get_position()), e.get_position()))
        target = invader.get_position()
        capsules = self.get_capsules_you_are_defending(state)
        ahead = {p: dist(target, p) for p in self.maze.neighbors
                 if self.maze.home(p) and dist(target, p) <= REGION}
        value = {p: 1 for p in ahead}
        for p in self.food & set(ahead):
            value[p] += FOOD_WEIGHT
        if invader.num_carrying:
            for p in set(self.maze.gates) & set(ahead):
                value[p] += GATE_WEIGHT
        mate = [i for i in self.get_team(state) if i != self.index][0]
        mate_state = state.get_agent_state(mate)
        covered = {p: INF for p in value}
        if (self.role != "Guard" or self.team.helping) and not mate_state.is_pacman \
                and not mate_state.scared_timer:
            covered = {p: dist(state.get_agent_position(mate), p) for p in value}

        def key(option):
            q = option[1]
            free = sum(v for p, v in value.items() if ahead[p] <= min(dist(q, p), covered[p]))
            return sum(dist(target, x) <= dist(q, x) for x in capsules), free, dist(q, target), q
        return key

    def patrol_gate(self, state):
        """Each possible opponent cell votes for its nearest gate, weighted by probability and closeness.

        A raider helping on defense leaves the gates next to the guard to the guard.
        """
        maze = self.maze
        dist = self.get_maze_distance
        votes = Counter()
        for belief in self.team.tracker.belief.values():
            for p, w in belief.items():
                gate = maze.nearest_gate[p]
                votes[gate] += w / (1 + dist(p, gate))
        gates = maze.gates
        if self.role != "Guard":
            mate = [state.get_agent_position(i) for i in self.get_team(state) if i != self.index][0]
            gates = [g for g in gates if dist(g, mate) > GUARD_SPACE] or gates
        return max(gates, key=lambda g: (votes[g], -dist(g, maze.center)))
