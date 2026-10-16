# Results summary (actual experiments)

Produced by `python -m eveseeker.experiments.run_experiments --trials 60 --out results`
(4,800 missions, 340 s on this laptop). Raw data: `results/experiment_results.csv`; per-condition summary:
`results/summary.csv` and `results/results_table.md`; paired comparisons: `results/paired_comparisons.csv`;
setup: `results/run_metadata.json`; figures: `results/plot_*.png`.

**Design.** Base mission: 20x20 map, 10% obstacles, 2 stations, battery 40, 100 actions / 150 time ticks, scan
reliability 0.8, 3 uniform clues. Six one-factor-at-a-time sweeps (map size, obstacle density, signal reliability,
misleading-decoy probability, battery, clue distribution). Every condition x strategy uses the **same 60 seeds
(0-59)**, so strategies face identical worlds and identical noise streams. Intervals: Wilson 95% for success rates; paired
bootstrap (2,000 resamples) for the success-rate difference EVE-Seeker minus other.
Note the base configuration appears once in every sweep (same seeds, same numbers), so the pooled figures below count it six times.

## Pooled over all 20 condition rows (60 missions each)
| Strategy | Success | Mean actions | Mean energy | Mean scans | Final error (cells) | Within 2 cells |
|---|---|---|---|---|---|---|
| Random walk | 0.052 | 97.8 | 110.5 | 11.7 | 11.3 | 0.07 |
| Greedy (MAP target) | 0.541 | 71.7 | 84.4 | 10.2 | 5.0 | 0.63 |
| EVE-Seeker w/o EIG (ablation) | 0.561 | 68.1 | 78.8 | 9.0 | 4.6 | 0.64 |
| **EVE-Seeker** | **0.698** | **61.9** | **65.7** | **4.5** | **3.8** | **0.75** |

## Per-condition success rate (n = 60 each; 95% Wilson half-width is roughly ±0.10-0.13 at mid-range rates)
| Factor | Level | Random | Greedy | EVE-Seeker | No-EIG ablation |
|---|---|---|---|---|---|
| map size | 12x12 | 0.12 | 0.97 | 0.98 | 0.98 |
| | 20x20 (base) | 0.05 | 0.57 | 0.75 | 0.58 |
| | 28x28 | 0.05 | 0.32 | 0.40 | 0.28 |
| obstacles | 0.0 | 0.07 | 0.50 | 0.77 | 0.53 |
| | 0.10 (base) | 0.05 | 0.57 | 0.75 | 0.58 |
| | 0.25 | 0.02 | 0.52 | 0.68 | 0.55 |
| scan reliability | 0.95 | 0.05 | 0.55 | 0.78 | 0.58 |
| | 0.8 (base) | 0.05 | 0.57 | 0.75 | 0.58 |
| | 0.6 | 0.05 | 0.40 | 0.58 | 0.52 |
| | 0.4 | 0.05 | 0.25 | 0.58 | 0.40 |
| decoy prob. (2 decoys) | 0.0 | 0.05 | 0.58 | 0.72 | 0.58 |
| | 0.3 | 0.05 | 0.55 | 0.67 | 0.50 |
| | 0.6 | 0.05 | 0.47 | 0.67 | 0.43 |
| battery | 25 | 0.00 | 0.25 | 0.47 | 0.32 |
| | 40 (base) | 0.05 | 0.57 | 0.75 | 0.58 |
| | 80 | 0.10 | 0.88 | 0.90 | 0.93 |
| clues | none | 0.05 | 0.57 | 0.62 | 0.55 |
| | uniform (base) | 0.05 | 0.57 | 0.75 | 0.58 |
| | near target | 0.05 | 0.58 | 0.65 | 0.53 |
| | far from target | 0.05 | 0.60 | 0.75 | 0.60 |

## What the data supports
1. **EVE-Seeker had the highest success rate in 19 of 20 rows** (tied at 12x12, where the task is nearly saturated; the
   no-EIG ablation was higher at battery 80, 0.93 vs 0.90).
2. **Paired comparison on identical seeds:** the success-rate difference vs. greedy has a 95% interval excluding zero in 12 of
   20 rows (all positive, none negative); vs. the no-EIG ablation in 14 of 20 (all positive). Typical gain at the base
   configuration: +0.18 vs greedy [0.05, 0.32] and +0.17 vs ablation [0.02, 0.30].
3. **It reached EVE with fewer actions and about half the scans** (4.5 vs ~10) and less energy. Resource-exhaustion rate at base
   reliability: EVE-Seeker 0.23, greedy 0.43, ablation 0.42, random 0.95 (`plot_efficiency_vs_reliability.png`).
4. **No advantage when resources are plentiful** (battery 80) or the task is easy (12x12): all belief-based agents then do well.
5. **Random walk** is near-useless (5%): the task needs directed search.

## What it does *not* show
* **Small samples.** n = 60 per cell gives wide intervals; many pairwise rows overlap, and the ranking of conditions is
  not reliable (e.g. EVE-Seeker's 0.58 at reliability 0.6 and 0.4 should not be read as "noise does not matter" -- it is
  within sampling error of a modest decline). ~60 interval comparisons were made without multiple-comparison correction, and
  the base configuration is reused across sweeps, so rows are not independent. Treat this as consistent evidence, not proof.
* **Decoy robustness is modest:** EVE-Seeker dropped 0.72 -> 0.67 with decoys, greedy 0.58 -> 0.47; the agent's model ignores
  decoys, so this is robustness by redundancy (clearing cells by sight, repeated scans), not explicit modelling.
* **The ablation is not a pure test of "information gain":** removing EIG also changes the scan policy (fixed schedule
  instead of value-driven) and the scoring (belief mass per cost). It shows the whole value-driven design beats the
  simpler variant, not that the entropy term alone is responsible.
* **Hyperparameters were set by hand** (not tuned on benchmark seeds); baseline parameters (scan every 4 steps) were
  also not tuned, so a stronger greedy baseline probably exists. Results apply to this simulator only.
* Voluntary stops: 8.6% of EVE-Seeker missions ended with `stopped_uncertain`, nearly all within ~2 actions of the
  budget limit; these are counted in `resource_exhausted` (stop with <= 5% budget left).
* `final_entropy` is undefined for the random agent (no belief).
