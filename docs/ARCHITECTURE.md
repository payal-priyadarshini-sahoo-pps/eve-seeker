# Architecture

```
                 ┌──────────────────────────── evaluation only ───────────────────────────┐
                 │  HiddenState (EVE, clues, decoys)  ──►  compute_metrics / truth tab    │
                 └───────────────▲────────────────────────────────────────────────────────┘
                                 │ private to the simulator
 MissionConfig ──► generate_world ──► MissionEnv ── PublicInfo (static map, costs, sensor spec) ──┐
 (JSON, seeded)                        │  step(Action)                                           │
                                       ▼                                                         ▼
                                  Observation  ─────────────────────────────────────────►  Agent.act(obs)
        (position, battery, budgets, scan reading, new clue hints, contact)                       │
                                                                                                   │ Action
   ┌───────────────────────────── EVE-Seeker ─────────────────────────────┐                        │
   │ SensorModel ─► BeliefState (Bayes) ─► batch_eig (information gain)   │◄───────────────────────┘
   │ GridPlanner (Dijkstra/A*) ─► ResourceManager (return-to-station,     │
   │ recharge rules) ─► candidate scoring ─► first step of best plan      │
   └──────────────────────────────────────────────────────────────────────┘
   Baselines (random, greedy) and the no-EIG ablation reuse the same belief, planner and resource rules.
```

| Package | Role |
|---|---|
| `eveseeker/environment` | config + validation, world generation, signal math, `MissionEnv`, observations |
| `eveseeker/agent` | sensor model, Bayesian belief, information gain, planning, resources, EVE-Seeker |
| `eveseeker/baselines` | random walk and greedy agents |
| `eveseeker/experiments` | mission runner, metrics, statistics, benchmark CLI |
| `eveseeker/visualization` | Streamlit dashboard, grid rendering, result plots |
| `configs/`, `scripts/`, `tests/`, `reports/`, `results/` | sample missions, CLI helpers, tests, mission reports, benchmark output |

**Hidden-state boundary.** Agents receive only `PublicInfo` (static map, costs, nominal sensor spec; it has no
EVE/clue/decoy fields) and `Observation`. `MissionEnv` keeps ground truth in a private attribute exposed only via
`evaluator_view()`, which is called by `compute_metrics` and the dashboard's labelled ground-truth tab. Three tests
enforce this: a source scan of `agent/` and `baselines/`, a reachability walk over each agent's object graph, and a
check that observations contain no EVE position before contact. (Python cannot make this airtight; it is a
disciplined interface plus tests.)
