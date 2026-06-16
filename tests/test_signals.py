import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from signals import (
    score_mnav, score_btc_yield,
    score_ma200, score_rs_30d, score_funding_rate,
    compute_score, SIGNAL_LABELS,
)

def test_score_mnav_long():
    assert score_mnav(0.9) == 1

def test_score_mnav_watch():
    assert score_mnav(1.5) == 0

def test_score_mnav_short():
    assert score_mnav(2.8) == -1

def test_score_btc_yield_long():
    assert score_btc_yield(20.0) == 1

def test_score_btc_yield_watch():
    assert score_btc_yield(8.0) == 0

def test_score_btc_yield_short():
    assert score_btc_yield(-2.0) == -1

def test_score_btc_yield_none_is_watch():
    assert score_btc_yield(None) == 0

def test_score_ma200_long():
    assert score_ma200(current=110, ma200=100) == 1

def test_score_ma200_watch():
    assert score_ma200(current=103, ma200=100) == 0

def test_score_ma200_short():
    assert score_ma200(current=90, ma200=100) == -1

def test_score_rs_30d_long():
    assert score_rs_30d(mstr_30d=25.0, btc_30d=10.0) == 1

def test_score_rs_30d_watch():
    assert score_rs_30d(mstr_30d=15.0, btc_30d=10.0) == 0

def test_score_rs_30d_short():
    assert score_rs_30d(mstr_30d=5.0, btc_30d=20.0) == -1

def test_score_funding_rate_long():
    assert score_funding_rate(0.00005) == 1

def test_score_funding_rate_watch():
    assert score_funding_rate(0.0003) == 0

def test_score_funding_rate_short():
    assert score_funding_rate(0.0006) == -1

def test_compute_score_returns_correct_total():
    indicator_scores = [1, 0, 0, 1, 1, 0]
    total, signal = compute_score(indicator_scores)
    assert total == 3
    assert signal == "LONG BIAS"

def test_compute_score_strong_long():
    total, signal = compute_score([1, 1, 1, 1, 0, 0])
    assert total == 4
    assert signal == "STRONG LONG"

def test_compute_score_strong_short():
    total, signal = compute_score([-1, -1, -1, -1, 0, 0])
    assert total == -4
    assert signal == "STRONG SHORT"

def test_compute_score_neutral():
    total, signal = compute_score([0, 0, 0, 0, 0, 0])
    assert total == 0
    assert signal == "WATCH / NEUTRAL"
