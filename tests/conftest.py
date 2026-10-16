import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from eveseeker.environment import MissionConfig  # noqa: E402


@pytest.fixture
def small_cfg() -> MissionConfig:
    """Tiny deterministic open map: start (0,0), EVE (7,7), station at start."""
    return MissionConfig(name="t", width=8, height=8, obstacle_density=0.0, start=(0, 0), eve=(7, 7),
                         stations=((0, 0),), clues=MissionConfig().clues.__class__(count=0),
                         min_eve_distance=0)
