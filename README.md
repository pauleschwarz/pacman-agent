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
or if it carries eight or more and the enemies' scared timers would run out before it gets back. A scared ghost
whose fear ends within three turns already counts as dangerous. While both opponents are Pacmen on our side,
nobody defends their half, so a full load alone is no reason to bank.

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
- Measured on a MacBook Air (Apple M5) with version 16: the slowest move took 55 ms, setup at most 1.3 s on the
  largest map (limits: 1 s and 15 s). Version 18 adds one constant-time check per raider move.
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

The final team is version 18 (fourth round under Development). It differs from version 16 only in when the
raider banks. Both versions on the same games:

| Opponent | Version | Random mazes W/D/L | Points | Fixed layouts W/D/L | Points |
|---|---|---:|---:|---:|---:|
| course baseline | 18 | 399/0/1 | 99.8% | 107/13/0 | 92.8% |
| course baseline | 16 | 400/0/0 | 100.0% | 108/11/1 | 93.1% |
| v0 | 18 | 271/33/96 | 70.5% | 56/27/29 (112 games) | 58.0% |
| v0 | 16 | 259/41/100 | 68.2% | 59/25/36 | 56.1% |

- Paired game by game, version 18 against 16 gains +0.03 ± 0.04 points per game on random mazes (score
  +0.93 ± 0.19) and +0.00 ± 0.05 on the fixed layouts (score +0.71 ± 0.54): no loss against either opponent.
- The one baseline loss (RANDOM6001, red): the baseline's attacker ate our capsule, our scared guard died on a
  raid, walked back through the long corridor from its start, and the attacker banked 28. Version 16 won that game.
- The fixed-layout games against `v0` ran while other programs kept the laptop's load average above 100 in Low
  Power Mode. 31 games hit time limits on both sides. Replayed alone, 23 ran cleanly and count. Eight stay out:
  seven on jumboCapture, where the red team's first agent ran out of its 15 s startup, because the framework's
  maze-distance precomputation took 34–58 s on the loaded laptop (1.3 s when quiet), and one on distantCapture,
  whose first run ran out of startup time and whose replay alone still had a 1.9 s move of ours (the file keeps
  the first run). The startup timeouts hit both teams the same way.
- Raw results: `results/final-v18-random.jsonl`, `results/final-v18-fixed.jsonl` (replayed games marked
  `replayed_alone`). The rest of this section describes version 16.

### Against other teams' agents

We collected 33 public agents of other teams from GitHub (forks of the course template and a code search): 9 from
2024, 12 from 2025, 5 from this year and 7 of unknown year. They served only as opponents and are not in this
repository. Results name them by year and number (`2026-3`); the folder names are kept locally.

| Games (fresh, never used in development) | Version 16 | Version 18 | Paired points per game |
|---|---:|---:|---:|
| the eight strongest, 11 fixed layouts and RANDOM9000–9019, both colors (482 games) | 63.3% | 69.3% | +0.18 ± 0.06 |
| all 33, 11 fixed layouts and RANDOM9100–9104, both colors (1,000 games) | 86.7% | 86.8% | +0.00 ± 0.02 |
| course baseline, RANDOM9200–9249 (100 games) | 100/0/0 | 100/0/0 | |

Against all 33 the score per game rose by +2.13 ± 0.37. In those games 27 of the 33 agents got at most 15% of
the points against version 18. Against each of the strongest three (`2026-3`, `unknown-4`, `2026-4`; two from
this year) version 18 still scored under half of the points (36.5%, 41.7%, 46.9%; 35/15/46 games together).
They attack with both agents and often eat our capsule. Raw results: `results/dev/round4-confirm-*.jsonl`.

### Version 16

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
- Nothing was measured on the tournament cluster.
- Against agents that attack with both agents, a single guard rarely catches anyone, and our capsule is often
  eaten; against each of the three strongest public agents we found we still score under half of the points.
- The framework charges its maze-distance precomputation to the red team's first agent. On jumboCapture it took
  1.3 s on a quiet laptop but 34–58 s under heavy load, past the 15 s startup limit. On a crowded machine the
  red team can forfeit that layout at startup, whichever team it is.

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

A fourth round used the agents of other teams (see Results). Version 16 against all 33 on the fixed layouts and
RANDOM7000–7009 (1,452 games, `round4-pool-v16.jsonl`) scored 85.1% of the points, but only 35–39% against the
three strongest. Replays of 112 games against the four strongest showed why (rough figures again):

- Hardly anyone dies, under 0.5 times per agent and game. The game is a race: our raider banked 16.5 pellets per
  game and our guard 1.7, each of the opponent's two attackers about 9.
- 40% of the pellets they ate from our side went while our guard was scared, 65% while both of them were on our side.
- They ate our capsule in 83 of the 112 games. In those games we scored 36.5% of the points, in the other 29 games 63.2%.

Each candidate then played the same 336 games against the eight strongest (the 11 fixed layouts other than
`testCapture` and RANDOM8000–8009, both colors, seed `dev1`; `round4-*.jsonl`). Version 16 scored 63.4% there.
The table shows each candidate's points and the paired change in points per game.

| Change | Points | Paired change |
|---|---:|---:|
| raider turns back for an invader carrying 2 (`HELP_CARGO` 2) | 61.9% | -0.04 ± 0.04 |
| raider on our side defends whenever both opponents invade | 61.7% | -0.04 ± 0.06 |
| both of the above | 59.9% | -0.10 ± 0.05 |
| guard raids whenever both opponents invade | 50.6% | -0.38 ± 0.07 |
| the same, only while no invader is visible | 56.2% | -0.22 ± 0.06 |
| scared guard banks with 4 or 8 pellets (`RAID_CARGO`) | 64.0%, 62.6% | +0.02 ± 0.04, -0.02 ± 0.04 |
| gates weigh 6 once the invader carries food (`GATE_WEIGHT`) | 63.3% | -0.00 ± 0.01 |
| guard contests 6 or 15 steps around the invader (`REGION`) | 59.9%, 63.5% | -0.10 ± 0.05, +0.01 ± 0.06 |
| raider on our side takes a visible invader within 2 or 3 steps | 64.0%, 63.7% | +0.02 ± 0.02, +0.01 ± 0.03 |
| guard goes to a capsule a hidden invader's likely cell is within 6 or 10 of, if it gets there first | 62.4%, 61.8% | -0.03 ± 0.02, -0.05 ± 0.04 |
| guard goes to a capsule any opponent's likely cell is within 8 or 12 of | 63.5%, 63.1% | +0.01 ± 0.05, -0.01 ± 0.06 |
| guard always stays at a capsule while we have one | 56.4% | -0.21 ± 0.07 |
| raider banks a load of 3, 8 or 12 (`LOAD`) | 58.6%, 64.9%, 63.2% | -0.14 ± 0.07, +0.05 ± 0.07, -0.01 ± 0.08 |
| no load-based banking while both opponents are on our side | 65.2% | +0.06 ± 0.06 |
| load 8 and no load-based banking while both opponents are on our side | 67.2% | +0.12 ± 0.07 |
| load 12 and the same | 65.1% | +0.05 ± 0.08 |

More defence cost more attack than it saved, and the capsule rules did not stop the capsule being eaten in time.
Only carrying more leaned positive. The best of 23 candidates on the same games is likely to look better than it
is, so before measuring further we fixed the rule: keep load 8 with no load-based banking against two invaders
only if fresh games show more than twice the standard error against the eight strongest, no loss beyond that
against all 33, no loss against the baseline, no error of ours and passing tests. It met all five (Results).
Its slowest move in those games, 0.38 s against the baseline, came from load: replayed alone, the same game took
at most 11 ms per move with the same moves. That is version 18.

A fifth round looked at what still decides the games against the strongest. Replays of version 18's 132 games
against the three strongest (the `round5-base.jsonl` games below; rough figures as before):

- Against `2026-3` it ate about as many of our pellets in won games as in lost ones (27 and 26 per game). Our
  raider made the difference: it banked 30 pellets per won game and 9 per lost one. These games are a race,
  and we lose it when our raider is slower or stuck.
- 64% of the pellets the three ate went while our guard was more than five steps from every invader. They ate
  our capsule 1.05 times per lost game and 0.82 times per won game.
- On `alleyCapture` we got 40% of the points against the eight strongest and 17% against the three. In one
  replay against `2026-3` the raider died twice with food, once after about 50 of its turns carrying 8
  pellets without getting home while the ghosts held the way out.

Each candidate played the same 352 games against the eight strongest: the 12 fixed layouts and
RANDOM8100–8109, both colors, seed `dev2` (`round5-*.jsonl`). Version 18 scored 73.9% there.

| Change | Points | Paired change |
|---|---:|---:|
| raider banks whatever it carries once the opponents hold all but 0 or 3 of the pellets they need | 72.8%, 70.8% | -0.03 ± 0.02, -0.09 ± 0.04 |
| scared guard walks into a visible invader to restart unscared, if respawning and walking back beats its timer by 0 or 8 moves | 73.8%, 73.9% | -0.00 ± 0.03, +0.00 ± 0.02 |
| with no ghost in sight, raider picks among the 3 or 6 cheapest pellets the one that starts the shortest nearest-first tour home | 71.2%, 74.9% | -0.07 ± 0.06, +0.04 ± 0.06 |
| with a ghost in sight and no provably safe target, a raider carrying 1 or 3 heads home | 74.0%, 75.2% | +0.00 ± 0.05, +0.04 ± 0.04 |
| raider chases a visible scared ghost within 2 or 5 steps | 71.7%, 69.6% | -0.06 ± 0.02, -0.12 ± 0.04 |
| scared guard on a raid keeps eating while both opponents are on our side | 71.7% | -0.07 ± 0.04 |
| guard chases the visible invader carrying most instead of the nearest | 72.4% | -0.04 ± 0.03 |
| tracker: an invader never stands on our remaining food or capsules, and the one opponent that moved stands where our pellet vanished; also using food carried and banked | 73.6%, 73.3% | -0.01 ± 0.02, -0.02 ± 0.02 |
| guard raids too while the score is tied, in the last 50, 100 or 150 own turns | 74.7%, 73.7%, 71.4% | +0.02 ± 0.02, -0.01 ± 0.03, -0.08 ± 0.04 |
| the same, only while no opponent is on our side | 74.2%, 73.1%, 72.6% | +0.01 ± 0.02, -0.02 ± 0.02, -0.04 ± 0.03 |

The six-pellet tour took up to 0.6 s per move and had a time warning of ours in three games. With the sharper
tracker, the games against three of the eight opponents stayed the same move for move, and against two more
all but one game: the guard already heads for a vanished pellet, so a sharper belief rarely changed a decision.

Raiding with the guard when tied is the one idea with a reason to expect a gain: at a tie near the end, a
pellet banked turns a draw (1 point) into a win (3), while one conceded only turns it into a loss (0).
We kept the round-four rule, fixed before measuring further. Both 50-turn variants played fresh games:
RANDOM9300–9339 and the 12 fixed layouts, both colors, seed `val5`, 832 games each (`round5-confirm-*.jsonl`).
Version 18 scored 71.5% there.

- Raiding whenever tied: +0.00 ± 0.02 points per game.
- Raiding only while no opponent is on our side: +0.019 ± 0.009, 1.99 standard errors, just short of the rule.
  18 of 799 games changed outcome, 12 for the better.

Version 18 stays the final team.

## Files

| File | Purpose |
|---|---|
| `my_team.py` | The team. |
| `tests/test_my_team.py` | Real games on all layout kinds and odd maps, tracker soundness, raider safety, timing, unit checks. |
| `tools/arena.py` | Parallel headless matches with time limits, error detection and a JSON line per game. |
| `results/` | Raw results of the final measurement; `results/dev/` those of development. |

## Credits

Game rules and framework by UC Berkeley (CS188), RMIT, the University of Melbourne and UPF.
The raider and guard started from our lab-4 practice team. AI assistance was used to check
tests and benchmark results and to research and try further algorithms.
