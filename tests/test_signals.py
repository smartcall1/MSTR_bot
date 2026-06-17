import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from signals import (
    score_mnav, score_btc_yield,
    score_ma200, score_rs_30d, score_funding_rate,
    score_strc_depeg, is_strc_severe_depeg,
    compute_score, compute_all_indicators, SIGNAL_LABELS,
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

def test_score_strc_depeg_none_is_watch():
    assert score_strc_depeg(None) == 0

def test_score_strc_depeg_at_par():
    assert score_strc_depeg(100.0) == 0

def test_score_strc_depeg_at_threshold_is_watch():
    assert score_strc_depeg(95.0) == 0  # discount == 5%, not > 5

def test_score_strc_depeg_mild_depeg_is_short():
    assert score_strc_depeg(94.0) == -1  # discount 6% > 5%

def test_score_strc_depeg_premium_is_watch():
    assert score_strc_depeg(102.0) == 0  # premium is not bullish

def test_is_strc_severe_depeg_none_is_false():
    assert is_strc_severe_depeg(None) is False

def test_is_strc_severe_depeg_at_threshold_is_false():
    assert is_strc_severe_depeg(90.0) is False  # discount == 10%, not > 10

def test_is_strc_severe_depeg_beyond_threshold_is_true():
    assert is_strc_severe_depeg(89.0) is True  # discount 11% > 10%

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


def test_fetch_yfinance_data_includes_strc_price():
    mock_mstr_hist = pd.DataFrame({
        "Close": [100.0] * 199 + [110.0],
        "High": [105.0] * 200,
        "Low": [95.0] * 200,
    })
    mock_btc_hist = pd.DataFrame({"Close": [50000.0] * 40})
    mock_strc_hist = pd.DataFrame({"Close": [94.5]})

    def ticker_side_effect(symbol):
        m = MagicMock()
        if symbol == "MSTR":
            m.history.return_value = mock_mstr_hist
        elif symbol == "BTC-USD":
            m.history.return_value = mock_btc_hist
        elif symbol == "STRC":
            m.history.return_value = mock_strc_hist
        return m

    with patch("signals.yf.Ticker", side_effect=ticker_side_effect):
        from signals import fetch_yfinance_data
        result = fetch_yfinance_data()

    assert result is not None
    assert result["strc_price"] == 94.5


def test_fetch_yfinance_data_strc_price_none_when_empty():
    mock_mstr_hist = pd.DataFrame({
        "Close": [100.0] * 199 + [110.0],
        "High": [105.0] * 200,
        "Low": [95.0] * 200,
    })
    mock_btc_hist = pd.DataFrame({"Close": [50000.0] * 40})
    mock_strc_hist = pd.DataFrame({"Close": []})

    def ticker_side_effect(symbol):
        m = MagicMock()
        if symbol == "MSTR":
            m.history.return_value = mock_mstr_hist
        elif symbol == "BTC-USD":
            m.history.return_value = mock_btc_hist
        elif symbol == "STRC":
            m.history.return_value = mock_strc_hist
        return m

    with patch("signals.yf.Ticker", side_effect=ticker_side_effect):
        from signals import fetch_yfinance_data
        result = fetch_yfinance_data()

    assert result is not None
    assert result["strc_price"] is None


def test_compute_score_total_minus_six_is_strong_short():
    total, signal = compute_score([-1, -1, -1, -1, -1, -1])
    assert total == -6
    assert signal == "STRONG SHORT"


def test_compute_score_severe_depeg_forces_strong_long_to_strong_short():
    total, signal = compute_score([1, 1, 1, 1, 0, 0], strc_severe_depeg=True)
    assert total == 4
    assert signal == "STRONG SHORT"


def test_compute_score_severe_depeg_forces_long_bias_to_strong_short():
    total, signal = compute_score([1, 0, 0, 1, 1, 0], strc_severe_depeg=True)
    assert total == 3
    assert signal == "STRONG SHORT"


def test_compute_score_severe_depeg_forces_caution_to_strong_short():
    total, signal = compute_score([-1, -1, 0, 0, 0, 0], strc_severe_depeg=True)
    assert total == -2
    assert signal == "STRONG SHORT"


def test_compute_score_severe_depeg_leaves_already_strong_short_unchanged():
    total, signal = compute_score([-1, -1, -1, -1, -1, -1], strc_severe_depeg=True)
    assert total == -6
    assert signal == "STRONG SHORT"


def test_compute_score_not_severe_leaves_signal_unchanged():
    total, signal = compute_score([1, 1, 1, 1, 0, 0], strc_severe_depeg=False)
    assert total == 4
    assert signal == "STRONG LONG"


def _base_market_data(strc_price):
    return {
        "mstr_price": 110.0, "btc_price": 50000.0, "ma200": 100.0,
        "mstr_30d": 5.0, "btc_30d": 5.0, "atr14": 5.0,
        "strc_price": strc_price,
    }

def test_compute_all_indicators_includes_strc_indicator():
    market_data = _base_market_data(94.0)
    indicators, total, signal, errors, strc_severe = compute_all_indicators(
        mnav_result=None, market_data=market_data, funding_rate=None,
        btc_yield_result=None, config={},
    )
    strc_ind = next(i for i in indicators if i["name"] == "STRC 디페그")
    assert strc_ind["score"] == -1
    assert strc_ind["error"] is False
    assert strc_severe is False

def test_compute_all_indicators_strc_severe_forces_strong_short():
    market_data = _base_market_data(89.0)
    indicators, total, signal, errors, strc_severe = compute_all_indicators(
        mnav_result={"mnav_diluted": 0.9, "btc_per_share_diluted": 1.0},
        market_data=market_data, funding_rate=0.00005,
        btc_yield_result={"btc_yield": 20.0, "source": "scrape"}, config={},
    )
    assert strc_severe is True
    assert signal == "STRONG SHORT"

def test_compute_all_indicators_strc_na_when_market_data_none():
    indicators, total, signal, errors, strc_severe = compute_all_indicators(
        mnav_result=None, market_data=None, funding_rate=None,
        btc_yield_result=None, config={},
    )
    strc_ind = next(i for i in indicators if i["name"] == "STRC 디페그")
    assert strc_ind["error"] is True
    assert "yfinance(STRC)" in errors
    assert strc_severe is False
