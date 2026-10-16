# EVE-Seeker: an uncertainty-aware autonomous search agent

WALL-E must find a hidden target, EVE, on a grid map using **noisy, sometimes misleading signals** while managing a
limited battery, time and action budget. EVE-Seeker is an explainable probabilistic planner: it keeps a **Bayesian
belief** over EVE's location, chooses where to go and when to scan by **expected information gain**, navigates with
**Dijkstra/A\***, and manages energy with explicit return-to-station and recharge rules.

> **Research question.** Can an agent that selects observations by expected information gain locate a hidden target
> more efficiently than simpler strategies under uncertainty and resource limits?
> **Answer from our experiments:** in this simulator, yes in most conditions with moderate effect sizes and
> small samples (60 missions per cell); not when the task is easy or resources are plentiful. See
> [docs/RESULTS.md](docs/RESULTS.md) for numbers and caveats. No claim of novelty is made.

There is **no machine learning, reinforcement learning or deep learning** in this project.

## Quick start (Windows PowerShell)

```powershell
cd path\to\wall-e-eve-ai-agent
py -3.11 -m venv .venv                 # or: python -m venv .venv
.\.venv\Scripts\Activate.ps1           # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt

python scripts\run_mission.py --config configs\default_mission.json --seed 7      # one mission + report in reports\
streamlit run eveseeker\visualization\dashboard.py --server.address localhost --server.port 8501   # then open http://localhost:8501
python -m pytest -q                                                              # 68 tests
python -m eveseeker.experiments.run_experiments --trials 60 --out results        # full benchmark (~6 min)
```
Other strategies: `--strategy random|greedy|eve_seeker|eve_seeker_no_eig`. Other missions: `configs\*.json`.

## What is in the repository
```
eveseeker/environment/    config + validation, world generation, signal math, MissionEnv, observations
eveseeker/agent/          sensor model, Bayesian belief, information gain, planner, resources, EVE-Seeker
eveseeker/baselines/      random-walk and greedy agents
eveseeker/experiments/    runner, metrics, statistics, benchmark CLI
eveseeker/visualization/  Streamlit dashboard, grid rendering, result plots
configs/  scripts/  tests/  reports/ (mission reports)  results/ (benchmark output)  docs/
```
Architecture diagram: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Algorithms: [docs/TECHNICAL.md](docs/TECHNICAL.md).
Results: [docs/RESULTS.md](docs/RESULTS.md). Viva preparation: [docs/VIVA.md](docs/VIVA.md).

## How it works (short)
1. **Belief:** `b(e)` over free cells; each scan reading / clue hint multiplies by its likelihood and renormalises
   (Bayes). Cells seen empty are set to 0 (hard evidence). Contact with EVE is the only confirmed knowledge.
2. **Information gain:** for each reachable cell, the exact mutual information between EVE's location and
   "what I'd see on arrival (+ a scan there)", in bits.
3. **Decision:** maximise EIG / (energy + 0.5·time) among options that are reachable, within budget and still leave
   enough battery to return to a station; hunt for direct contact when the budget is nearly spent.
4. **Safety:** recharge trips when slack is low, never strand itself; stop and report uncertainty when nothing
   useful is feasible.

## Hidden-state boundary
Agents only see `PublicInfo` and `Observation`. EVE, clue and decoy positions live inside `MissionEnv`
(`evaluator_view()` is for the evaluator and the dashboard's red "EVALUATION-ONLY" tab). Tests check this by source
scan, object-graph walk, and observation inspection.

## Dashboard
Strategy and mission selection, seed, noise/battery/budget overrides, Step / +10 / Run / Reset / New seed / Rerun.
Shows the belief heatmap, trail, discovered clues (with hint arrows), EVE estimate, entropy, battery and budgets,
the current action with a plain-language reason, full action/observation history, mission status, benchmark
comparison and a live head-to-head runner.

## Limitations and future work
* Single stationary target; known static map; Manhattan-range signals that ignore walls.
* The agent's sensor model ignores decoys (misleading sources) -- a model with an outlier component or a learned
  reliability would be more robust. Planning is one step of lookahead (destination + optional scan).
* Hyper-parameters are hand-set; the ablation changes the scan policy as well as the scoring.
* 60 missions per benchmark cell: wide confidence intervals.
* Possible next steps: non-myopic planning (rollouts/MCTS), moving targets, estimating sensor reliability online,
  multi-robot search, wall-occluded signals, tuned baselines.

## Repository

The EVE-Seeker source code, documentation, tests, experiment results, and mission reports are available in this public GitHub repository:

**GitHub:** https://github.com/payal-priyadarshini-sahoo-pps/eve-seeker

### Clone the project

```powershell
git clone https://github.com/payal-priyadarshini-sahoo-pps/eve-seeker.git
cd eve-seeker
```

See the Quick Start section above for installation and execution instructions.