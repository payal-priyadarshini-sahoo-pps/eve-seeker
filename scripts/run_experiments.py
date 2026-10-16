"""Thin wrapper: python scripts/run_experiments.py --trials 60 --out results"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eveseeker.experiments.run_experiments import main  # noqa: E402

if __name__ == "__main__":
    main()
