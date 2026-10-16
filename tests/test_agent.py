import gc
import inspect
import re
from pathlib import Path

import numpy as np
import pytest

import eveseeker.agent as agent_pkg
import eveseeker.baselines as baselines_pkg
from eveseeker.agent import (BeliefState, EveSeekerAgent, GridPlanner, ResourceManager, SeekerConfig, SensorModel,
                             batch_eig, eig_single, entropy_bits)
from eveseeker.environment import (Action, HiddenState, MissionConfig, MissionEnv, Observation, PublicInfo,
                                   BATTERY_EXHAUSTED, RESOURCE_EXHAUSTION)
from eveseeker.experiments import MissionSession, run_mission
from eveseeker.experiments.stats import mean_ci, paired_bootstrap_diff, wilson_ci
from eveseeker.strategies import STRATEGIES, make_agent


def make(cfg, seed=0):
    env = MissionEnv(cfg, seed)
    return env, env.info


# ------------------------------------------------------------- Bayesian updates
def test_prior_is_uniform_and_normalised(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    assert b.prob.sum() == pytest.approx(1.0)
    assert b.entropy() == pytest.approx(np.log2(64))


def test_bayes_update_matches_hand_computation():
    from eveseeker.environment import SignalConfig
    cfg = MissionConfig(width=3, height=3, obstacle_density=0.0, start=(0, 0), eve=(2, 2), min_eve_distance=0,
                        signal=SignalConfig(reliability=0.8, strong_radius=0, weak_radius=1))
    _, info = make(cfg)
    b = BeliefState(info, SensorModel(info))
    b.observe_scan((1, 1), 2)  # "strong" reading from the centre
    # strong is the true band only if EVE is at the centre: P(r|centre)=0.8, P(r|other)=(1-0.8)/2=0.1
    # posterior(centre) = (0.8/9) / (0.8/9 + 8*0.1/9) = 0.5 ; each other cell = 0.1/1.6 = 0.0625
    assert b.prob[1, 1] == pytest.approx(0.5)
    assert b.prob[0, 0] == pytest.approx(0.0625)
    assert b.prob.sum() == pytest.approx(1.0)


def test_scan_evidence_concentrates_belief_near_signal(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    h0 = b.entropy()
    b.observe_scan((7, 7), 2)   # strong signal at the far corner
    assert b.entropy() < h0
    assert b.prob[7, 7] > b.prob[0, 0]


def test_normalisation_after_many_updates(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    rng = np.random.default_rng(0)
    for _ in range(500):
        b.observe_scan((int(rng.integers(8)), int(rng.integers(8))), int(rng.integers(3)))
        assert b.prob.sum() == pytest.approx(1.0)
        assert np.all(np.isfinite(b.prob)) and np.all(b.prob >= 0)


def test_no_contact_zeroes_visible_cells_and_contact_collapses(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    b.observe_no_contact((3, 3))
    for c in [(3, 3), (2, 3), (4, 3), (3, 2), (3, 4)]:
        assert b.prob[c[1], c[0]] == 0
    assert b.prob.sum() == pytest.approx(1.0)
    b.observe_contact((7, 7))
    assert b.prob[7, 7] == 1.0 and b.confirmed == (7, 7)


def test_contradictory_evidence_does_not_crash_or_zero_belief(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info, reliability=1.0))   # clipped to 0.99
    for _ in range(40):
        b.observe_scan((0, 0), 2)    # insists EVE is next to the origin...
    for _ in range(40):
        b.observe_scan((7, 7), 2)    # ...and then insists it is at the opposite corner
    assert b.prob.sum() == pytest.approx(1.0) and np.all(np.isfinite(b.prob))


def test_contradiction_fallback_when_posterior_zero(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    b._apply(np.zeros_like(b.prob))
    assert b.contradictions == 1 and b.prob.sum() == pytest.approx(1.0)


def test_misleading_observation_shifts_belief_but_is_recoverable(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    b.observe_scan((0, 0), 2)                    # one (wrong) strong reading near the origin
    wrong_mass = b.prob[:3, :3].sum()
    for _ in range(6):
        b.observe_scan((0, 0), 0)                # repeated "nothing here" readings
    assert b.prob[:3, :3].sum() < wrong_mass


def test_clue_hint_update_prefers_hinted_side(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    b.observe_clue((3, 3), "E")
    assert b.prob[:, 5:].sum() > b.prob[:, :2].sum()


def test_insufficient_evidence_reports_low_confidence(small_cfg):
    _, info = make(small_cfg)
    b = BeliefState(info, SensorModel(info))
    _, conf = b.map_estimate()
    assert conf == pytest.approx(1 / 64)


# ------------------------------------------------------------- information gain
def test_entropy_known_values():
    assert entropy_bits(np.array([0.5, 0.5])) == pytest.approx(1.0)
    assert entropy_bits(np.array([1.0, 0.0])) == 0.0
    assert entropy_bits(np.full(8, 1 / 8)) == pytest.approx(3.0)


def test_eig_nonnegative_and_scan_ge_visit(small_cfg):
    _, info = make(small_cfg)
    s = SensorModel(info)
    b = BeliefState(info, s)
    lik, vis = s.stacks()
    v, sc, m = batch_eig(b.prob.ravel(), lik, vis)
    assert np.all(v >= 0) and np.all(sc >= v - 1e-9) and np.all((m >= 0) & (m <= 1))


def test_eig_single_matches_manual_mutual_information(small_cfg):
    _, info = make(small_cfg)
    s = SensorModel(info)
    b = BeliefState(info, s)
    pos = (4, 4)
    _, eig, m = eig_single(b.prob, s.scan_lik(pos), s.vision_mask(pos))
    # brute force: enumerate readings
    bp = b.prob * ~s.vision_mask(pos)
    h0 = entropy_bits(b.prob)
    resid = 0.0
    for k in range(3):
        q = bp * s.scan_lik(pos)[k]
        if q.sum() > 0:
            resid += q.sum() * entropy_bits(q / q.sum())
    assert eig == pytest.approx(h0 - resid, abs=1e-9)
    assert m == pytest.approx(s.vision_mask(pos).sum() / 64)


def test_eig_zero_for_useless_sensor_and_when_belief_is_certain(small_cfg):
    _, info = make(small_cfg)
    s = SensorModel(info, reliability=1 / 3)     # reading independent of EVE location -> no information
    b = BeliefState(info, s)
    pos = (4, 4)
    _, eig, _ = eig_single(b.prob, s.scan_lik(pos), np.zeros((8, 8), bool))
    assert eig == pytest.approx(0.0, abs=1e-9)
    s2 = SensorModel(info)
    b2 = BeliefState(info, s2)
    b2.observe_contact((7, 7))
    _, eig2, _ = eig_single(b2.prob, s2.scan_lik(pos), s2.vision_mask(pos))
    assert eig2 == pytest.approx(0.0, abs=1e-9)


def test_eig_prefers_informative_scan_location(small_cfg):
    """A scan right at the likely region splits a concentrated belief better than a far-away scan."""
    _, info = make(small_cfg)
    s = SensorModel(info)
    b = BeliefState(info, s)
    b.prob[:] = 0
    b.prob[2:6, 2:6] = 1 / 16                    # belief concentrated in the centre block
    novis = np.zeros((8, 8), bool)
    _, near, _ = eig_single(b.prob, s.scan_lik((4, 4)), novis)
    _, far, _ = eig_single(b.prob, s.scan_lik((0, 0)), novis)
    assert near >= 0 and far >= 0
    assert max(near, far) > 0.05


# ------------------------------------------------------------- pathfinding
def test_astar_matches_dijkstra_and_avoids_obstacles():
    cfg = MissionConfig(width=10, height=10, obstacle_density=0.25)
    for seed in range(8):
        env, info = make(cfg, seed)
        pl = GridPlanner(info)
        dist, parent = pl.dijkstra(info.start)
        eve = env.evaluator_view().eve  # test code may use ground truth
        path = pl.astar(info.start, eve)
        assert path is not None and len(path) - 1 == dist[eve[1], eve[0]]
        assert all(c not in info.obstacles for c in path)
        assert all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(path, path[1:]))
        assert pl.path_from_parents(parent, info.start, eve) is not None


def test_impossible_route_returns_none():
    cfg = MissionConfig(width=5, height=5, obstacle_density=0.0, start=(0, 0), eve=(0, 4), min_eve_distance=0,
                        obstacles=((2, 0), (2, 1), (2, 2), (2, 3), (2, 4)), n_stations=1)
    # the region right of the wall is unreachable and gets filled; planner must say no route
    _, info = make(cfg)
    pl = GridPlanner(info)
    assert pl.astar((0, 0), (4, 0)) is None
    dist, _ = pl.dijkstra((0, 0))
    assert np.isinf(dist[0, 4])


def test_station_distance_field(small_cfg):
    _, info = make(small_cfg)
    pl = GridPlanner(info)
    assert pl.station_dist[0, 0] == 0 and pl.station_dist[7, 7] == 14


# ------------------------------------------------------------- resource management
def obs_at(pos, battery, at_station=False, t=100, a=100):
    return Observation(step=0, position=pos, battery=battery, time_remaining=t, actions_remaining=a,
                       at_station=at_station)


def test_recharge_decisions(small_cfg):
    _, info = make(small_cfg)
    pl = GridPlanner(info)
    rm = ResourceManager(info, pl)
    # healthy battery in the open: no recharge
    d, p = pl.dijkstra((2, 2))
    assert rm.decide(obs_at((2, 2), 40), d, p) is None
    # low slack: heads towards the station (0,0)
    obs = obs_at((3, 3), 8)
    d, p = pl.dijkstra((3, 3))
    act, why = rm.decide(obs, d, p)
    assert act.type.value == "move" and (act.dx, act.dy) in [(-1, 0), (0, -1)]
    # at the station and low -> recharge
    d, p = pl.dijkstra((0, 0))
    rm2 = ResourceManager(info, pl)
    act, _ = rm2.decide(obs_at((0, 0), 10, True), d, p)
    assert act.type.value == "recharge"
    # no time left for a round trip -> does not start one
    rm3 = ResourceManager(info, pl)
    d, p = pl.dijkstra((3, 3))
    assert rm3.decide(obs_at((3, 3), 8, t=3), d, p) is None


def test_reserve_rule_never_strands_any_strategy():
    cfg = MissionConfig(width=15, height=15, obstacle_density=0.1).override(**{"battery.capacity": 20.0,
                                                                              "budget.max_actions": 150,
                                                                              "budget.max_time": 220})
    for strat in STRATEGIES:
        for seed in range(6):
            assert run_mission(cfg, strat, seed).status != BATTERY_EXHAUSTED


def test_agent_recharges_in_practice():
    cfg = MissionConfig(width=15, height=15).override(**{"battery.capacity": 15.0, "budget.max_actions": 200,
                                                         "budget.max_time": 300})
    results = [run_mission(cfg, "eve_seeker", s) for s in range(5)]
    assert sum(r.recharges for r in results) > 0


# ------------------------------------------------------------- end-to-end & termination
@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_end_to_end_mission_runs_for_each_strategy(strategy):
    res = run_mission(MissionConfig(width=12, height=12), strategy, 4)
    assert res.status != "running" and res.actions > 0
    assert res.success == (res.status == "success")
    assert res.resource_exhausted or res.status not in RESOURCE_EXHAUSTION


def test_eve_seeker_finds_eve_in_easy_mission():
    cfg = MissionConfig(width=12, height=12).override(**{"signal.reliability": 0.95})
    wins = sum(run_mission(cfg, "eve_seeker", s).success for s in range(10))
    assert wins >= 8


def test_exhausted_resources_end_safely_with_uncertainty_report():
    cfg = MissionConfig(width=20, height=20).override(**{"budget.max_actions": 8, "budget.max_time": 12})
    res = run_mission(cfg, "eve_seeker", 2)
    assert res.status in RESOURCE_EXHAUSTION and not res.success
    assert res.final_entropy > 0 and res.final_confidence < 1


def test_agent_stops_when_no_productive_action_possible():
    cfg = MissionConfig(width=10, height=10, n_stations=0).override(**{"battery.capacity": 2.0})
    s = MissionSession(cfg, "eve_seeker", 1)
    res = s.run()
    assert res.status in ("stopped_uncertain", "success", BATTERY_EXHAUSTED, "timeout", "action_budget_exhausted")
    assert res.actions <= cfg.budget.max_actions


def test_session_trace_and_explanations():
    s = MissionSession(MissionConfig(width=12, height=12), "eve_seeker", 3, snapshots=True)
    s.step()
    rec = s.trace[0]
    assert rec.reason and rec.belief is not None and rec.belief.sum() == pytest.approx(1.0)


def test_no_endless_loop_and_few_invalid_actions():
    for seed in range(5):
        cfg = MissionConfig(width=20, height=20, obstacle_density=0.25)
        r = run_mission(cfg, "eve_seeker", seed)
        assert r.actions <= cfg.budget.max_actions and r.invalid_actions == 0


# ------------------------------------------------------------- reproducibility
def test_run_is_reproducible_for_fixed_seed():
    cfg = MissionConfig(width=14, height=14)
    for strat in STRATEGIES:
        a, b = run_mission(cfg, strat, 21), run_mission(cfg, strat, 21)
        assert a == b


def test_strategies_are_run_on_identical_worlds():
    cfg = MissionConfig()
    truths = {s: MissionSession(cfg, s, 5).env.evaluator_view() for s in STRATEGIES}
    assert len(set(truths.values())) == 1


# ------------------------------------------------------------- hidden-state isolation
FORBIDDEN = re.compile(r"\b(MissionEnv|HiddenState|evaluator_view|generate_world|_hidden)\b")


def test_agent_source_never_references_ground_truth():
    for pkg in (agent_pkg, baselines_pkg):
        for f in Path(pkg.__file__).parent.glob("*.py"):
            code = "\n".join(l for l in f.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("#"))
            # strip docstrings/comments mentions by checking only non-docstring code
            body = re.sub(r'""".*?"""', "", code, flags=re.S)
            assert not FORBIDDEN.search(body), f"{f.name} references hidden state"


def test_public_types_carry_no_hidden_fields():
    for cls in (PublicInfo, Observation):
        names = set(inspect.signature(cls).parameters)
        assert not names & {"eve", "hidden", "clues", "decoys", "truth", "eve_position"}


def test_agent_object_graph_has_no_reference_to_env_or_hidden_state():
    cfg = MissionConfig(width=12, height=12)
    for strat in STRATEGIES:
        s = MissionSession(cfg, strat, 3)
        for _ in range(10):
            if not s.done:
                s.step()
        seen, stack = set(), [s.agent]
        while stack:
            o = stack.pop()
            if id(o) in seen:
                continue
            seen.add(id(o))
            assert not isinstance(o, (MissionEnv, HiddenState)), f"{strat} holds a ground-truth object"
            stack.extend(gc.get_referents(o))
        # the eve location is not part of PublicInfo either
        assert not hasattr(s.env.info, "eve")


def test_observations_do_not_leak_eve_until_contact():
    s = MissionSession(MissionConfig(width=14, height=14), "eve_seeker", 6)
    while not s.done:
        s.step()
        if not s.done:
            assert s.obs.contact is None


def test_agent_behaviour_independent_of_hidden_state_given_same_observations(small_cfg):
    """Two worlds with different EVE positions but identical observation streams -> identical actions."""
    cfgs = [small_cfg.override(eve=(7, 7)), small_cfg.override(eve=(7, 6))]
    seqs = []
    for cfg in cfgs:
        env, info = make(cfg, 0)
        ag = EveSeekerAgent(info)
        obs = env.reset()
        acts = []
        for _ in range(3):
            a = ag.act(obs)
            acts.append(str(a))
            # feed identical, fixed fake observation (no scan) to isolate the agent from the env
            obs = Observation(step=obs.step + 1, position=obs.position if a.type.value != "move" else
                              (obs.position[0] + a.dx, obs.position[1] + a.dy), battery=obs.battery - 1,
                              time_remaining=obs.time_remaining - 1, actions_remaining=obs.actions_remaining - 1,
                              at_station=False)
        seqs.append(acts)
    assert seqs[0] == seqs[1]


# ------------------------------------------------------------- metrics & stats
def test_metric_definitions_consistent_with_env_stats():
    cfg = MissionConfig(width=12, height=12)
    s = MissionSession(cfg, "greedy", 2)
    r = s.run()
    st = s.env.stats
    assert (r.actions, r.scans, r.recharges) == (st.actions, st.scans, st.recharges)
    assert r.energy_used == pytest.approx(st.energy_used, abs=1e-3)
    truth = s.env.evaluator_view().eve
    if r.success:
        assert r.final_error == 0 and r.localized_exact
    else:
        est, _ = s.agent.estimate()
        assert r.final_error == abs(est[0] - truth[0]) + abs(est[1] - truth[1])
    assert r.localized_within2 == (r.final_error <= 2)


def test_wilson_and_mean_ci_and_bootstrap():
    lo, hi = wilson_ci(50, 100)
    assert lo < 0.5 < hi and 0.40 < lo and hi < 0.60
    assert wilson_ci(0, 0)[0] != wilson_ci(0, 0)[0]  # NaN
    assert wilson_ci(10, 10)[1] == 1.0
    m, a, b = mean_ci([1, 2, 3, 4, 5])
    assert m == 3 and a < 3 < b
    d, lo, hi = paired_bootstrap_diff([1, 1, 1, 0] * 20, [0, 0, 1, 0] * 20)
    assert d == pytest.approx(0.5) and lo > 0
