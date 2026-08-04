"""Tests for core.infrastructure.thresholds_config.

Values are the OFFICIAL BRAIN hard lines, cross-validated 2026-08-01.
These tests pin the numbers so a future edit can't silently drift away
from the validated source.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import thresholds_config as cfg  # noqa: E402


def test_official_hard_lines_match_cross_validated_values():
    # zread.ai QuantGPT + dafu-zhu + alexisdpc (2026-08-01)
    assert cfg.SHARPE_MIN == 1.25
    assert cfg.FITNESS_MIN == 1.0
    assert cfg.TURNOVER_MIN == 0.01
    assert cfg.TURNOVER_MAX == 0.70
    assert cfg.MAX_WEIGHT_MAX == 0.10
    assert cfg.SELF_CORR_MAX == 0.7


def test_internal_floor_stricter_than_platform():
    # Our quality filter should be at or above the official minimums.
    assert cfg.SUBMIT_SHARPE_FLOOR >= cfg.SHARPE_MIN
    assert cfg.SUBMIT_FITNESS_FLOOR >= cfg.FITNESS_MIN
    assert cfg.SUBMIT_TURNOVER_MAX <= cfg.TURNOVER_MAX


def test_as_dict_is_flat_and_complete():
    d = cfg.as_dict()
    assert d["SHARPE_MIN"] == 1.25
    assert d["MAX_WEIGHT_MAX"] == 0.10
    assert len(d) == 12
