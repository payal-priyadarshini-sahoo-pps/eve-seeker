import json

import numpy as np
import pytest

from eveseeker.environment import (Action, ConfigError, MissionConfig, MissionEnv, ACTION_BUDGET,
                                   BATTERY_EXHAUSTED, STOPPED, SUCCESS, TIMEOUT)
from eveseeker.environment.signals import band_of_distance, true_direction


# ------------------------------------------------------------- configuration
def test_default_config_valid_and_roundtrip():
    cfg = MissionConfig()
    assert MissionConfig.from_dict(json.loads(json.dumps(cfg.to_dict()))) == cfg


@pytest.mark.parametrize("bad", [
    {"width": 2}, {"obstacle_density": 0.9}, {"signal": {"reliability": 1.5}},
    {"signal": {"strong_radius": 5, "weak_radius": 3}}, {"battery": {"capacity": 0}},
    {"clues": {"distribution": "weird"}}, {"unknown_key": 1}, {"start": [99, 0]}, {"budget": {"max_time": 0}},
])
def test_invalid_configs_rejected(bad):
    with pytest.raises(ConfigError):
        MissionConfig.from_dict(bad)


def test_json_loading_and_missing_file(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"width": 9, "height": 9, "signal": {"reliability": 0.9}}))
    assert MissionConfig.from_json(p).signal.reliability == 0.9
    with pytest.raises(ConfigError):
        MissionConfig.from_json(tmp_path / "nope.json")
    p.write_text("{not json")
    with pytest.raises(ConfigError):
        MissionConfig.from_json(p)


def test_shipped_configs_load():
    from pathlib import Path
    files = list((Path(__file__).resolve().parents[1] / "configs").glob("*.json"))
    assert files
    for f in files:
        MissionEnv(MissionConfig.from_json(f), seed=1)


def test_override_nested():
    cfg = MissionConfig().override(**{"signal.reliability": 0.5, "width": 12})
    assert cfg.signal.reliability == 0.5 and cfg.width == 12


# ------------------------------------------------------------- movement & obstacles
def test_move_and_obstacle_blocking(small_cfg):
    cfg = small_cfg.override(obstacles=((1, 0),))
    env = MissionEnv(cfg, 0)
    env.reset()
    obs = env.step(Action.move(1, 0))            # into obstacle
    assert not obs.action_valid and obs.position == (0, 0)
    obs = env.step(Action.move(-1, 0))           # off the map
    assert not obs.action_valid
    obs = env.step(Action.move(0, 1))
    assert obs.action_valid and obs.position == (0, 1)
    assert env.stats.invalid_actions == 2
    assert not env.step(Action.move(1, 1)).action_valid  # diagonal rejected


def test_unreachable_pockets_become_walls():
    # wall of obstacles isolating the corner (3,3)
    cfg = MissionConfig(width=6, height=6, obstacle_density=0.0, start=(0, 0), eve=(5, 5), min_eve_distance=0,
                        obstacles=((2, 3), (3, 2), (4, 3), (3, 4)), n_stations=1)
    env = MissionEnv(cfg, 0)
    assert (3, 3) in env.info.obstacles


def test_eve_in_walled_off_region_rejected():
    cfg = MissionConfig(width=6, height=6, obstacle_density=0.0, start=(0, 0), eve=(3, 3), min_eve_distance=0,
                        obstacles=((2, 3), (3, 2), (4, 3), (3, 4)), n_stations=1)
    with pytest.raises(ConfigError):
        MissionEnv(cfg, 0)


# ------------------------------------------------------------- energy, recharge, termination
def test_action_costs(small_cfg):
    env = MissionEnv(small_cfg, 0)
    env.reset()
    b = small_cfg.battery
    env.step(Action.move(1, 0))
    assert env.battery == pytest.approx(b.capacity - b.move_cost)
    env.step(Action.scan())
    assert env.battery == pytest.approx(b.capacity - b.move_cost - b.scan_cost)
    env.step(Action.wait())
    assert env.battery == pytest.approx(b.capacity - b.move_cost - b.scan_cost - b.wait_cost)
    assert env.stats.time_used == 1 + small_cfg.budget.scan_time + 1


def test_recharge_only_at_station_and_capped(small_cfg):
    env = MissionEnv(small_cfg, 0)
    env.reset()
    assert env.step(Action.recharge()).action_valid       # at station (full -> capped, still valid)
    assert env.battery == small_cfg.battery.capacity
    env.step(Action.move(1, 0))
    env.step(Action.move(1, 0))
    obs = env.step(Action.recharge())
    assert not obs.action_valid and obs.message.startswith("not on")
    env.step(Action.move(-1, 0)); env.step(Action.move(-1, 0))
    before = env.battery
    env.step(Action.recharge())
    assert env.battery == min(small_cfg.battery.capacity, before + small_cfg.battery.recharge_rate)


def test_battery_exhaustion_strands_agent(small_cfg):
    cfg = small_cfg.override(**{"battery.capacity": 3.0})
    env = MissionEnv(cfg, 0)
    env.reset()
    env.step(Action.move(1, 0)); env.step(Action.move(1, 0))
    obs = env.step(Action.move(1, 0))
    assert obs.done and obs.status == BATTERY_EXHAUSTED


def test_stranded_when_last_energy_spent_away_from_station(small_cfg):
    cfg = small_cfg.override(**{"battery.capacity": 1.0})
    env = MissionEnv(cfg, 0)
    env.reset()
    env.step(Action.move(1, 0))                      # battery 0 away from station -> stranded
    assert env.status == BATTERY_EXHAUSTED


def test_timeout_and_action_budget(small_cfg):
    env = MissionEnv(small_cfg.override(**{"budget.max_time": 3}), 0)
    env.reset()
    for _ in range(3):
        obs = env.step(Action.wait())
    assert obs.status == TIMEOUT
    env = MissionEnv(small_cfg.override(**{"budget.max_actions": 2}), 0)
    env.reset()
    env.step(Action.wait())
    assert env.step(Action.wait()).status == ACTION_BUDGET
    with pytest.raises(RuntimeError):
        env.step(Action.wait())


def test_success_on_contact_and_stop(small_cfg):
    cfg = small_cfg.override(eve=(2, 0), vision_range=1)
    env = MissionEnv(cfg, 0)
    env.reset()
    obs = env.step(Action.move(1, 0))
    assert obs.done and obs.status == SUCCESS and obs.contact == (2, 0)
    env = MissionEnv(small_cfg, 0)
    env.reset()
    assert env.step(Action.stop()).status == STOPPED


# ------------------------------------------------------------- observations
def test_band_function():
    assert list(band_of_distance(np.array([0, 3, 4, 7, 8]), 3, 7)) == [2, 2, 1, 1, 0]


def test_scan_noise_rate_matches_reliability(small_cfg):
    rel = 0.7
    cfg = small_cfg.override(**{"signal.reliability": rel, "battery.capacity": 1e6,
                                "budget.max_time": 10 ** 6, "budget.max_actions": 10 ** 6})
    env = MissionEnv(cfg, 3)
    env.reset()
    # EVE at (7,7); from (0,0) distance 14 -> true band 0
    readings = [env.step(Action.scan()).scan_reading for _ in range(3000)]
    frac_true = np.mean([r == 0 for r in readings])
    assert abs(frac_true - rel) < 0.04
    assert set(readings) == {0, 1, 2}  # wrong readings do occur (misleading)


def test_decoys_mislead_scans(small_cfg):
    cfg = small_cfg.override(**{"decoys.count": 1, "decoys.probability": 1.0, "battery.capacity": 1e6,
                                "signal.reliability": 1.0, "budget.max_time": 10 ** 6,
                                "budget.max_actions": 10 ** 6})
    env = MissionEnv(cfg, 5)
    env.reset()
    decoy = env.evaluator_view().decoys[0]
    expected = int(band_of_distance(abs(decoy[0]) + abs(decoy[1]), 3, 7))
    assert env.step(Action.scan()).scan_reading == expected


def test_clue_discovery_and_direction():
    assert true_direction((0, 0), (5, 1)) == "E" and true_direction((0, 0), (1, -5)) == "N"
    assert true_direction((2, 2), (2, 2)) is None
    cfg = MissionConfig(width=8, height=8, obstacle_density=0.0, start=(0, 0), eve=(7, 0), min_eve_distance=0,
                        clues=MissionConfig().clues.__class__(count=1, positions=((2, 0),), reliability=1.0, radius=2))
    env = MissionEnv(cfg, 0)
    obs = env.reset()
    assert obs.new_clues and obs.new_clues[0].hint == "E"
    assert not env.step(Action.wait()).new_clues  # discovered only once


# ------------------------------------------------------------- reproducibility
def test_same_seed_same_world_and_noise():
    cfg = MissionConfig()
    a, b = MissionEnv(cfg, 11), MissionEnv(cfg, 11)
    assert a.info == b.info and a.evaluator_view() == b.evaluator_view()
    a.reset(); b.reset()
    ra = [a.step(Action.scan()).scan_reading for _ in range(15)]
    rb = [b.step(Action.scan()).scan_reading for _ in range(15)]
    assert ra == rb
    assert MissionEnv(cfg, 12).evaluator_view() != a.evaluator_view()


def test_random_missions_have_reachable_free_cells_only():
    from eveseeker.agent.planning import GridPlanner
    for seed in range(10):
        env = MissionEnv(MissionConfig(obstacle_density=0.3), seed)
        d, _ = GridPlanner(env.info).dijkstra(env.info.start)
        free = [(x, y) for y in range(15) for x in range(15) if (x, y) not in env.info.obstacles]
        assert all(np.isfinite(d[y, x]) for x, y in free)
        assert np.isfinite(d[env.evaluator_view().eve[1], env.evaluator_view().eve[0]])
