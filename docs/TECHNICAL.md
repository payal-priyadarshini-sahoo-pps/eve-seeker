# Technical explanation

## 1. Problem model
A known grid map with obstacles and recharge stations. EVE sits in one hidden free cell. WALL-E starts at a
station with a full battery and has three budgets: **energy** (moves cost 1, scans 3, waiting 0.2; recharge
restores 10 per action at a station), **time** (scan = 2 ticks, others 1) and **actions** (valid or not).
The mission ends in `success` (EVE within visual range, Manhattan distance <= 1), `battery_exhausted` (stranded off a
station), `timeout`, `action_budget_exhausted`, or `stopped_uncertain` (the agent stops and reports its estimate).

## 2. Observations
* **Proximity scan** (SCAN): reading r in {none, weak, strong}. With d = Manhattan(WALL-E, EVE), the true band is
  strong if d <= 3, weak if d <= 7, else none. The reading equals the true band with probability rho (default 0.8),
  otherwise it is uniform over the other two bands. So wrong readings genuinely occur.
* **Decoys** (optional): with probability p a scan reflects a hidden decoy emitter instead of EVE. The agent's model does
  not know about decoys (model mismatch), so this is *systematically* misleading evidence.
* **Clues**: hidden objects revealed when WALL-E walks within 2 cells. Each gives a compass hint (N/E/S/W) towards EVE,
  correct with probability 0.75.
* **Visual contact**: free, automatic. Any cell within range 1 with no EVE is *confirmed empty* (hard evidence).
  Contact reveals EVE exactly (confirmed knowledge, not an estimate).

## 3. Bayesian belief (`agent/belief.py`)
b(e) = P(EVE at e | observations), uniform over free cells initially. Each observation multiplies by its likelihood
and renormalises:

    b'(e) ∝ b(e) · P(obs | e)

* scan: `P(r | e, p) = rho` if r equals the band of d(p,e), else `(1-rho)/2`
* clue: `P(h | e, c) = rho_c` if h is the dominant-axis direction from c to e, else `(1-rho_c)/3`
* no contact at p: likelihood 0 for cells within visual range of p, 1 elsewhere
Assumptions: scan noise is independent across scans; EVE is stationary; the agent's assumed rho equals the nominal
spec (clipped to [0.01, 0.99] so that a contradiction can never produce exactly zero probability); decoys are
unmodelled. Normalisation happens after every update; if the posterior mass is numerically zero (only possible via
hard evidence) the belief falls back to uniform over not-yet-cleared cells and `contradictions` is incremented.
**Uncertainty vs. confirmed knowledge:** soft evidence only reshapes probabilities; only visual contact (or a
cleared cell) is treated as certain.

## 4. Expected information gain (`agent/info_gain.py`)
For a candidate destination x, let m be the belief mass inside x's visual range and b' the belief with that range
removed. Arriving gives a "contact" outcome with probability m (entropy 0 afterwards). Optionally scanning adds reading k:

    EIG_visit = H(b) − (1−m)·H(b'/(1−m))
    EIG_scan  = H(b) − Σ_k P_k · H(posterior_k),   P_k = Σ_e b'(e)·P(k|e,x)

This is the exact mutual information between EVE's location and the observation(s), in bits. It is vectorised over all
candidate cells and tested against a brute-force computation, against zero for a useless sensor / certain belief, and
for non-negativity.

## 5. Planning and resource management
* **Dijkstra** gives distances/parents from the current cell to every cell each step; **A\*** is used for
  point-to-point queries and cross-checked against Dijkstra in tests. Unreachable targets yield `None`/`inf`.
* **Feasibility** of a candidate: reachable; within remaining actions and time; and
  `battery_left >= energy_to_nearest_station + margin` after the excursion (return feasibility).
* **Score** = EIG / cost, with cost = energy + 0.5·time. Visit-only and visit+scan variants of each cell compete, so scans
  happen only when their information is worth the cost. Repeated scans at a spot are discounted (x0.5 each).
* **Adaptive endgame:** when < 15% of time/actions remain, information that can no longer be acted on is worthless,
  so the agent maximises probability of directly finding EVE.
* **Recharge rules:** head to a station when slack (battery − return energy) < 6; recharge opportunistically when
  at a station below 50%; recharge to 95%; skip the trip if there is no time for it.
* **Termination:** if no feasible action has positive value the agent stops with `stopped_uncertain`, reporting its MAP
  estimate and probability. A loop watchdog forbids recently visited cells if entropy stalls.
* Receding horizon with hysteresis (keep the previous target if it scores >= 85% of the best) avoids dithering.

## 6. Baselines and ablation
| Strategy | Uses belief? | Chooses by |
|---|---|---|
| Random walk | no | random safe step, random scan 15% (readings ignored) |
| Greedy | yes (same belief) | walks to the most probable reachable cell, scans every 4 steps |
| EVE-Seeker | yes | EIG per unit cost, endgame mode |
| EVE-Seeker w/o EIG (ablation) | yes | belief mass in view per cost, scans every 4 steps |
All share the environment, observation rules, budgets and the same battery-safety/recharge logic.

## 7. Metrics (definitions)
`success` = ended in `success`. `actions`, `scans`, `recharges` = counts from the environment. `energy_used` = total energy
spent (recharged energy not subtracted). `resource_exhausted` = ended in battery/time/action exhaustion, or voluntarily
stopped with <= 5% of actions/time left. `final_error` = Manhattan distance between the agent's final estimate (MAP
cell; EVE's cell after contact; a uniformly random cell for the belief-free random agent) and EVE.
`localized_within2` = final_error <= 2. `final_entropy` = entropy of the final belief (0 after contact; undefined for random).

## 8. What is *not* in here
No machine learning, reinforcement learning or neural networks: this is an explainable probabilistic planner. Its
parameters (time weight, thresholds) were set by hand and sanity-checked on development seeds >= 1000; benchmark
seeds are 0..59, so they were not used for tuning.
