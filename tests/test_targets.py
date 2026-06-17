import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from targets import compute_nav_per_share, compute_targets, compute_funding_cost


def test_compute_nav_per_share_from_btc_per_share():
    result = compute_nav_per_share(
        btc_price=80000,
        btc_per_share_diluted=0.002203,
        mnav_diluted=None,
        mstr_price=None,
    )
    assert result == pytest.approx(80000 * 0.002203, rel=0.001)


def test_compute_nav_per_share_from_mnav_fallback():
    result = compute_nav_per_share(
        btc_price=80000,
        btc_per_share_diluted=None,
        mnav_diluted=0.80,
        mstr_price=144.0,
    )
    assert result == pytest.approx(144.0 / 0.80, rel=0.001)


def test_compute_targets_long():
    nav = 180.0
    mstr_price = 124.5
    atr14 = 8.0

    result = compute_targets(
        signal_direction="long",
        mstr_price=mstr_price,
        nav_per_share=nav,
        atr14=atr14,
    )

    assert result["tp1_price"] == pytest.approx(nav * 1.5, rel=0.001)
    assert result["tp2_price"] == pytest.approx(nav * 2.0, rel=0.001)
    assert result["sl_price"] == pytest.approx(mstr_price - 2 * atr14, rel=0.001)
    assert result["tp1_pct"] == pytest.approx((nav * 1.5 / mstr_price - 1) * 100, rel=0.01)
    assert result["sl_pct"] == pytest.approx((result["sl_price"] / mstr_price - 1) * 100, rel=0.01)


def test_compute_targets_short():
    nav = 180.0
    mstr_price = 250.0
    atr14 = 10.0

    result = compute_targets(
        signal_direction="short",
        mstr_price=mstr_price,
        nav_per_share=nav,
        atr14=atr14,
    )

    assert result["tp1_price"] == pytest.approx(nav * 1.2, rel=0.001)
    assert result["tp2_price"] == pytest.approx(nav * 0.9, rel=0.001)
    assert result["sl_price"] == pytest.approx(mstr_price + 2 * atr14, rel=0.001)


def test_compute_targets_long_falls_back_to_atr_when_mnav_disagrees_with_direction():
    # mstr_price(124.5)가 이미 tp1(nav*1.5=120.0)보다 비쌈 — mNAV가 long 방향과 어긋남 → ATR 대체
    result = compute_targets(
        signal_direction="long",
        mstr_price=124.5,
        nav_per_share=80.0,
        atr14=8.0,
    )
    assert result["tp1_price"] == pytest.approx(140.5, rel=0.001)
    assert result["tp2_price"] == pytest.approx(156.5, rel=0.001)
    assert result["sl_price"] == pytest.approx(108.5, rel=0.001)
    assert result["tp1_label"] == "ATR 2×"
    assert result["tp2_label"] == "ATR 4×"


def test_compute_targets_short_falls_back_to_atr_when_mnav_disagrees_with_direction():
    # mstr_price(124.5)가 이미 tp1(nav*1.2=216.0)보다 싸짐 — mNAV가 short 방향과 어긋남 → ATR 대체
    result = compute_targets(
        signal_direction="short",
        mstr_price=124.5,
        nav_per_share=180.0,
        atr14=8.0,
    )
    assert result["tp1_price"] == pytest.approx(108.5, rel=0.001)
    assert result["tp2_price"] == pytest.approx(92.5, rel=0.001)
    assert result["sl_price"] == pytest.approx(140.5, rel=0.001)
    assert result["tp1_label"] == "ATR 2×"
    assert result["tp2_label"] == "ATR 4×"


def test_compute_targets_returns_none_for_watch():
    result = compute_targets(
        signal_direction="watch",
        mstr_price=124.5,
        nav_per_share=180.0,
        atr14=8.0,
    )
    assert result is None


def test_compute_funding_cost():
    cost = compute_funding_cost(rate_8h=0.00021, position_usd=100)
    assert cost == pytest.approx(0.00021 * 3 * 100, rel=0.001)
