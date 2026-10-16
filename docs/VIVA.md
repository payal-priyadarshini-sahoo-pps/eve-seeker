# Viva preparation

**1. What problem does the project solve?** A robot must find a hidden target on a grid using noisy proximity scans and
hints, with limited battery/time/actions. The challenge is deciding *where to go and what to measure* under uncertainty.

**2. Is this machine learning?** No. It is Bayesian inference + decision-theoretic planning (information gain) + graph search.
Nothing is trained. I should not call it ML/RL.

**3. Explain the Bayesian update.** Prior: uniform over free cells. For observation o, posterior(e) ∝ prior(e) · P(o | EVE at e).
Scan likelihood: rho if the reading equals the true band for that distance, else (1-rho)/2. Then normalise.

**4. Why can the agent be misled, and how does it recover?** A wrong reading has probability 1-rho (or comes from a decoy). One
bad reading only shifts probability; later readings from other places and cells cleared by sight pull belief back. Only
visual contact is certain.

**5. What is expected information gain?** The expected drop in belief entropy (bits) from an observation = mutual information
between EVE's location and the observation. High when outcomes are uncertain *and* differ by hypothesis. Computed exactly,
including the chance of directly seeing EVE.

**6. Why divide EIG by cost?** Information is only worth what it costs in energy and time; ratio ranks options per unit cost
(a standard greedy heuristic, not globally optimal).

**7. Why is EIG zero for a useless sensor / certain belief?** If the reading is independent of EVE's position (rho = 1/3) or
the belief is already a point mass, observing changes nothing -- there is a unit test for each.

**8. How does it handle the battery?** Every excursion must leave enough energy to reach a station (+ margin). It recharges
when slack is low, tops up opportunistically at stations, skips recharging when time is nearly gone, and stops and reports
uncertainty if nothing is feasible.

**9. Dijkstra vs A\*?** Dijkstra gives distances from the current cell to every cell (used to rank candidates). A\* finds a
single path faster using the Manhattan heuristic; tests confirm both give the same length and that blocked routes return None.

**10. How do you guarantee the agent can't cheat?** Agents receive only `PublicInfo` and `Observation`. The truth is in a
private attribute of the environment. Tests scan the agent source, walk each agent's object graph, and check that observations
contain no EVE position before contact. Caveat: Python cannot enforce this absolutely; it is interface discipline plus tests.

**11. What are the baselines?** Random walk (ignores readings), Greedy (same belief, goes to the most probable cell, scans on a
schedule), and an ablation of EVE-Seeker without EIG. All share the environment, budgets and safety rules.

**12. What did you find?** Pooled success: EVE-Seeker 0.70, greedy 0.54, ablation 0.56, random 0.05. EVE-Seeker used fewer
actions and about half the scans. Paired comparisons favour it in most conditions; no advantage on easy maps or with large
batteries. (Exact numbers: docs/RESULTS.md.)

**13. Is the result statistically conclusive?** No. 60 missions per condition gives confidence intervals of roughly ±0.1; I
used Wilson intervals and paired bootstraps, did not correct for ~60 comparisons, and the base configuration is reused across
sweeps. It is consistent evidence in one simulator, not proof of general superiority.

**14. Weaknesses of the work?** Myopic (one-step) planning; hand-set hyperparameters; agent ignores decoys in its model; ablation
changes more than one thing; baselines untuned; stationary target; known map; results only from my simulator.

**15. What does "reproducible" mean here?** The same (config, seed) gives the same world and the same noise stream (separate seeded
RNGs); strategies are compared on identical seeds; a test checks that repeated runs give identical results.

**16. How would you improve it?** Non-myopic planning (MCTS/rollouts), outlier-robust likelihood or online reliability
estimation, moving targets, wall-occluded sensors, tuning all strategies fairly, more trials.

**17. Why Manhattan range and 3 bands?** Simple, interpretable sensor consistent with 4-connected movement; the likelihood is a
closed-form table so the Bayesian update is exact. Real sensors would need a calibrated model.

**18. What happens if all evidence contradicts?** Reliability is clipped to [0.01, 0.99], so soft evidence never zeroes a cell;
if hard evidence somehow zeroes everything, belief falls back to uniform over uncleared cells and a counter records it.

## Concepts to know cold
Bayes' rule and normalisation; entropy and mutual information (bits); likelihood vs posterior; soft vs hard evidence;
exploration vs exploitation; Dijkstra/A\*; receding-horizon planning; model mismatch (decoys); confidence intervals
(Wilson), paired comparison on shared seeds; ablation; reproducibility with seeds; why n = 60 limits conclusions.
