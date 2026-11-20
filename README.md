# Pacman Agent · team Slowalemans

Our entry for the UPF Eutopia Pacman Capture-the-Flag contest (Artificial Intelligence, 2026-27).
The team is a single file, `my_team.py`, using only the standard library and the course framework.

## Setup

```sh
git clone https://github.com/pauleschwarz/pacman-agent.git
cd pacman-agent
git submodule update --init
python3.8 -m venv venv
venv/bin/pip install -r pacman-contest/requirements.txt
venv/bin/pip install -e pacman-contest
```

`git submodule update --init` checks out the framework commit we tested (`54cd83c`). The assignment's
`--remote` fetches the newest one instead.

Play one match against the course baseline, as in the assignment (add `-q --delay-step 0` to skip the window):

```sh
cd pacman-contest/src/contest
../../../venv/bin/python capture.py -r baseline_team -b ../../../my_team.py
```

Run the tests (about 20 seconds) and a benchmark (each match in its own process, time limits enforced):

```sh
venv/bin/python -m unittest discover -s tests -v
venv/bin/python tools/arena.py my_team.py baseline --layouts RANDOM1-20,fixed --jobs 6
```

## How the team plays

One agent is the **raider**, the other the **guard**. `create_team` gives both the same `Team` object; the
first registration of each game fills it with a map analysis and a belief about where hidden opponents are.
Every tuning number is a named constant at the top of `my_team.py`, with its meaning in one line.

### Shared map analysis (`Maze`)

- **Gates** are our border cells with an open neighbour on the enemy side. Every crossing goes through one.
- **Pockets.** Repeatedly removing cells with a single open neighbour peels off all dead ends.
  `pocket_exits` maps each removed cell to the junction where its pocket meets the rest of the maze.
  A Pacman inside a pocket can only escape through that junction.

### Tracking hidden opponents (`Tracker`)

An opponent is visible only within 5 squares of one of us; otherwise we get a noisy distance (±6).
The tracker keeps an exact probability distribution over the cells each opponent can occupy:

1. **Predict.** The global move counter (`timeleft`) tells which agents moved since the last update.
   Only an opponent that actually moved spreads its probability over staying or stepping to a neighbour.
2. **Observe.** Remove cells that contradict what we know: the opponent's side (Pacman or ghost),
   our two lines of sight, and the acting agent's sonar reading.
3. **Respawn.** If nothing survives, the opponent was eaten and restarts at its spawn, possibly one step further.

Both agents update the same belief, so every turn adds a new sonar reading. A test plays real games and checks
on every turn that the true position of each opponent never drops to probability zero.

### Raider

**When to go home.** With food on board, the raider banks if at most two enemy pellets remain, if its remaining
own turns barely cover the way home (three in reserve), if a dangerous ghost and home are both within five steps,
or if it carries five or more and the enemies' scared timers would run out before it gets back. A scared ghost
whose fear ends within three turns already counts as dangerous.

**Where to go with a ghost in sight.** The raider reasons about who arrives first:

- `threat(q)`: the earliest turn a visible opponent can stand on enemy cell `q`; a scared ghost counts only
  from the end of its timer.
- `safe_reach`: breadth-first search over cells we reach strictly before that turn.
- `escape_slack(q)`: the latest turn we may stand on `q` and still get home first,
  `slack(q) = min(threat(q) - 1, max over neighbours r of slack(r) - 1)`, computed outward from home.

Food is a safe target if we reach it in time to escape: `arrive(f) <= slack(f)`. In the unit-test corridor
(home at x=0, ghost at x=4) the slacks of x=1..4 are 2, 1, 0, -1: a pellet at x=1 is safe, one at x=2 is not,
because the ghost gets there as soon as we do. The raider takes the nearest safe pellet, prefers a capsule it
reaches first, and banks along cells it reaches first.

**Otherwise** it uses risk-weighted Dijkstra: every step costs 1, plus 1 for each visit to that cell among the
last eight positions (this breaks loops), and enemy cells cost 45 more next to an active ghost, 8 at distance
two, and 30 more when the ghost could reach the pocket exit before we get in and back out. A scared ghost adds
nothing while its timer exceeds our arrival time plus one. The first step never lands next to an active ghost if another
move exists.

**Choosing among targets.** A capsule may cost 2 steps more than food, 8 with a dangerous ghost near. While
the enemies stay scared longer than the trip to a capsule plus six turns, the raider does not aim for another
capsule (it may still cross one on the way to food). The current target wins ties by one step, which stops
dithering between equal choices.

### Guard

- **Stay home.** Every defensive path stays on our half: one step across the border would turn the guard
  into a Pacman that cannot catch anyone.
- **Patrol.** Each possible opponent cell votes for its nearest gate, weighted by probability and by
  1 / (1 + distance). The guard waits at the gate with the most votes.
- **Clues.** Food that disappears from our side, or the last sighting of an invader, becomes a destination
  for six own turns.
- **Hidden invader.** An opponent on our side that nobody sees is hunted at its most likely cell
  according to the tracker.
- **Visible invader.** The guard picks the move that, in this order, (1) keeps the invader from reaching
  one of our capsules before us, (2) shrinks what the invader can still reach before us or a defending
  teammate within 10 steps of it (every cell counts, food more, our gates too once it carries food), and
  (3) gets closer. Simple chasing fails: a Pacman that keeps moving away from one ghost is never caught.
  Counting the whole half instead of 10 steps made the guard hold distant chokepoints on large maps.
- **Scared.** A scared guard cannot eat anyone. It raids enemy food when a round trip, plus two spare moves,
  fits in its timer, using the raider's rules. It heads home with two pellets or when the window is down to
  the way home plus two. It drops the raid if its next step would end on our side next to a visible invader.
  Without a raid it keeps two steps from a visible invader, so it can strike once the timer ends.

### Team rules

- **Help.** A raider on our side turns back to defend when a visible invader carries five or more pellets.
  Both agents then shrink the invader's region together. Patrolling, the helper leaves the gates within
  three steps of the guard to the guard.
- **Endgame.** In the last 50 own turns, a team that is ahead banks and defends with both agents;
  a team that is behind sends the guard raiding too.

### Robustness

- Every action is checked against the legal moves. If a bug raised an exception during a real match, the agent
  logs it and plays a legal move instead of forfeiting the game; the tests run with `STRICT = True`, so the
  same bug fails them. A map the analysis cannot handle (for example one without any crossing) is treated the
  same way.
- Measured on a MacBook Air (Apple M5): the slowest move took 55 ms, setup at most 1.3 s on the largest map
  (limits: 1 s and 15 s).
- Shared state is rebuilt when a new game starts in the same process. No file, network or thread use.

### Fair play

The agents use only the observation the framework hands them: positions of opponents within sight, the noisy
distances, and fields the observation keeps for every agent (Pacman or ghost, scared timer, food carried).
The global move counter comes from `state.data.timeleft`, since the framework has no getter for it.
Nothing reads the real game state, other agents' objects or files.

## Results

Final measurement on games never used during development: random mazes RANDOM6000–6199 and the 12 fixed
layouts with five fresh seeds each, every layout in both colors, full 1,200-move games, unchanged course framework
(`pacman-contest` commit `54cd83c`). The UPF tournament plays three fixed and three random layouts per pairing,
so both kinds matter. Points count 3 per win and 1 per draw, as a share of the maximum.

`v0` is our earlier lab-4 practice team, the starting point of this version.
`sonar`, `race` and `center` are variants of it with other guard and banking rules.

| Opponent | Random mazes W/D/L | Points | Fixed layouts W/D/L | Points |
|---|---:|---:|---:|---:|
| course baseline | 400/0/0 | 100.0% | 108/11/1 | 93.1% |
| v0 | 259/41/100 | 68.2% | 59/25/36 | 56.1% |
| sonar | 282/37/81 | 73.6% | | |
| race | 285/30/85 | 73.8% | | |
| center | 302/40/58 | 78.8% | | |

- 2,240 games without a crash, illegal move, timeout or time warning. The slowest move took 55 ms, the slowest
  setup 1.3 s (jumboCapture). Half of the games had a 99th-percentile move time under 4 ms.
- The baseline draws on `testCapture`, which has no food, and once on `tinyCapture`. The one loss is on
  `strategicCapture`: in its long corridors a single guard following an invader never catches it.
- Against `v0` the final version's share of points varied between 56% and 68% across our measurement sets.
  Expect the lower end against a strong opponent.
- On this laptop, more than six parallel matches caused occasional wall-clock stalls over one second even for
  moves that computed in milliseconds. Replayed alone, the same games ran without warnings and with identical moves.

Raw results: `results/final-random.jsonl`, `results/final-fixed.jsonl`, summary in `results/final-summary.txt`.
Reproduce with:

```sh
venv/bin/python tools/arena.py my_team.py baseline <v0>/my_team.py --layouts RANDOM6000-6199 --jobs 6
venv/bin/python tools/arena.py my_team.py baseline <v0>/my_team.py --layouts fixed --repeat 5 --seed final --jobs 6
```

### Known weaknesses

- In a long corridor, a single guard following an invader never catches it (the strategicCapture loss).
- The pocket analysis finds only tree-shaped dead ends. A dead-end branch with a small loop at its end is not
  treated as a trap.
- Nothing was measured on the tournament cluster or against other teams' agents.

## Development

Development used other games than the final measurement. Raw results of every row below are in `results/dev/`;
in those files the opponent `agent` is `v0` (named after its folder). The variants themselves are not kept in the
repository. In the first phase each candidate played the same 600 random-maze games against `v0`
(RANDOM201–500, both colors).

| Version | Change | W/D/L vs v0 | Points | Kept |
|---|---|---:|---:|---|
| 1 | v0 in one file, opponents tracked by both agents | 252/104/244 | 47.8% | yes |
| 7 | guard blocks capsules, and gates while the invader carries food | 276/86/238 | 50.8% | replaced |
| 9 | guard shrinks the invader's reachable region | 296/84/220 | 54.0% | yes |
| 10 | guard waits beside our capsule | 255/59/286 | 45.8% | no |
| 11 | raider picks provably safe targets when a ghost is in sight | 335/71/194 | 59.8% | yes |
| 13 | raider helps against a heavily loaded invader; region shared by both | 346/71/183 | 61.6% | yes |
| 14 | raider detours after 15 turns blocked at the border | 338/63/199 | 59.8% | no |

A first check on the fixed layouts showed version 13 losing there (41.9% of points against `v0`).
The second phase therefore measured each candidate on the fixed layouts (10 seeds, 240 games) and on
400 new random-maze games (RANDOM2000–2199).

| Version | Change | Fixed | Random | Kept |
|---|---|---:|---:|---|
| 13 | as above | 41.9% | 61.2% | replaced |
| | without the region rule, plain chasing | 48.1% | 56.7% | no |
| 15 | region counted only within 10 steps of the invader | 54.6% | 61.9% | yes |
| 16 | guard hunts a hidden invader at its most likely cell | 55.7% | 62.4% | **final** |
| 17 | raider also turns back from the enemy side for an invader carrying 10 or more | 55.7% | 61.5% | no |

Smaller trials that did not survive: making the raider avoid every cell an opponent could reach first
(100 games, 25/13/62 against `v0`; too passive), recalling the raider for every invader (200 games, 67/36/97),
and two raiders without a guard (100 games each, 41/2/57 against `v0`, 24/0/76 against the baseline).

A second round tried five more ideas on the same phase-2 games against `v0`. Version 16 replays those games
move for move, so every game pairs exactly. No idea gained on both kinds of layout, so the team stayed as it was.

| Change | Fixed | Random | Kept |
|---|---:|---:|---|
| none (version 16) | 55.7% | 62.4% | |
| guard raids while enemy ghosts are scared and nobody invades | 52.9% | 62.1% | no |
| no capsule preference without a dangerous ghost near (`CAPSULE_BONUS` 0) | 55.7% | 63.4% | no |
| capsules avoided without a dangerous ghost near (`CAPSULE_BONUS` -4) | 55.7% | 64.2% | no |
| stronger capsule preference near a dangerous ghost (`CAPSULE_RUSH` 15) | 55.8% | 63.2% | no |
| raider routes avoid the tracker's likely cells of hidden ghosts (cost 30 per unit of probability) | 51.8% | 66.5% | no |
| the same with cost 10 | 53.5% | 65.2% | no |

The capsule changes moved the paired score by less than twice its standard error, which is noise. Avoiding
hidden ghosts (cost 30) helped on random mazes, a paired score change of +0.43 against a margin of 0.38. On the
fixed layouts it did worse, -1.15 within a margin of 1.50; two thirds of the lost points came from jumboCapture
(19 points over 20 games). It would pay off only on maze kinds we cannot predict, so we left it out.
Against two baseline defenders (`turtle`) or two baseline attackers (`rush`) on RANDOM2000–2039 and the fixed
layouts (`round2-zoo.jsonl`) the team won 101 and 102 of 104 games and drew the rest.

A third round went after the standoff at the border. In the 80 games behind the observations below, the raider
spent about 81 of its 300 turns as a Pacman within five steps of an active ghost without eating, and ate in
about 18. Three ideas tried to turn that time into food, again on the phase-2 games against `v0`
(`round3-*.jsonl`).

| Change | Fixed | Random | Kept |
|---|---:|---:|---|
| none (version 16) | 55.7% | 62.4% | |
| feint: a raider blocked on our side first walks to the gate it reaches with the largest lead over the visible ghosts | 48.8% | 59.1% | no |
| the same, and an empty Pacman without a safe target turns back to do so | 36.8% | 51.6% | no |
| pincer: the guard raids while no opponent can reach our side before it is back; a visible ghost near our raider does not count | 56.7% | 62.3% | no |
| lookahead: with a ghost near and no safe target, expectimax over three rounds; the ghost steps towards us with probability 0.8, being caught costs what we carry plus 10 | 47.9% | 53.8% | no |
| the same, being caught costs what we carry plus 3, or plus 5 | 47.9%, 47.9% | 53.3%, 54.0% | no |
| the same, plus 3 and the ghost chasing with probability 0.5 | 49.4% | 52.6% | no |

Neither feint helped. The plain feint lost points on both kinds of layout, though its paired score change stayed
within the margin (-1.07 ± 1.30 fixed, -0.22 ± 0.54 random). Turning back and the lookahead lost by more than
the margin on random mazes (-1.45 ± 0.67 and -1.19 ± 0.70). The lookahead banked fewer pellets than version 16,
0.7 per game on the fixed layouts and 1.3 on random mazes. In the 80 games behind the rough figures below it
almost stopped the raider dying (about 0.5 to 0.1 deaths per game). Our reading: three rounds are too short to
see the detours to other food that the route planner finds, and the cost of being caught hardly changed that.
The pincer was neutral (-1.23 ± 1.29 fixed, -0.03 ± 0.57 random). Four pincer games logged one time warning for
our team while six games ran in parallel. Replayed alone, all four made the same moves without a warning
(`round3-pincer-recheck.jsonl`), so the table counts their results. Three more pincer games logged a warning
for `v0`; the arena does not count those as our errors.

Until then every candidate had played `v0`, an opponent weaker than our team. Version 16 itself is a harder
test, and the arena already takes any team as opponent. Against itself version 16 plays each blue game as the
mirror of the red one, so it wins and loses exactly as often (`round3-h2h-*-v16.jsonl`; in these files the
opponent `base` is version 16). Each candidate pairs game by game with that. The table shows the paired score
change per game against version 16.

| Candidate against version 16 | Fixed | Random |
|---|---:|---:|
| pincer | -0.15 ± 1.18 | -0.18 ± 0.44 |
| hidden-ghost avoidance, cost 30 | +0.70 ± 0.83 | +0.07 ± 0.33 |
| the same, cost 10 | +0.39 ± 0.78 | +0.06 ± 0.32 |
| capsules avoided without a dangerous ghost near (`CAPSULE_BONUS` -4) | 0.00 ± 0.00 | -0.01 ± 0.35 |

On the fixed layouts the capsule change played 239 of the 240 games move for move like version 16, and the
other one ended with the same score. Only hidden-ghost avoidance leaned positive, at both costs. Before
measuring further we fixed one rule for the stronger version, cost 30: keep it only if fresh games
(RANDOM3000–3299 and the fixed layouts with new seeds, 840 games) show a gain beyond the margin. They did not:
+0.04 ± 0.89 fixed, -0.02 ± 0.27 random (`round3-confirm-*.jsonl`). Version 16 stays the final team.

Observations from replaying development games against `v0` shaped these changes. The small analysis scripts
behind them are not in the repository, so treat these as rough figures:

- About 55% of all points were banked while the defending team was scared by a capsule.
- The raider ate food in under 5% of its turns. Most of the rest it spent near a ghost, at the border or on the enemy side.
- Guards rarely catch anyone (about 0.5 deaths per game), so the game is mostly a race for food.
- Our guard spent about 107 of its 300 turns with no invader on our side (80 games, RANDOM8000–8039). The
  first idea of the second round tried to use that time.

## Files

| File | Purpose |
|---|---|
| `my_team.py` | The team. |
| `tests/test_my_team.py` | Real games on all layout kinds and odd maps, tracker soundness, raider safety, timing, unit checks. |
| `tools/arena.py` | Parallel headless matches with time limits, error detection and a JSON line per game. |
| `results/` | Raw results of the final measurement; `results/dev/` those of development. |

## Credits

Game rules and framework by UC Berkeley (CS188), RMIT, the University of Melbourne and UPF.
The raider and guard started from our lab-4 practice team. Both versions were developed with AI assistance
(OpenAI Codex, then Anthropic Claude).
