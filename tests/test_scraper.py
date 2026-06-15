import pytest
from unittest.mock import patch, Mock
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper import parse_mnav_page, compute_mnav_diluted, fetch_mnav

SAMPLE_HTML = """
<html><body>
<table>
  <tr><td>mNAV (Basic)</td><td>0.72×</td></tr>
  <tr><td>BTC / Share (Basic)</td><td>0.002407</td></tr>
  <tr><td>BTC / Share (Diluted)</td><td>0.002203</td></tr>
</table>
</body></html>
"""

def test_parse_mnav_page_extracts_values():
    result = parse_mnav_page(SAMPLE_HTML)
    assert result["mnav_basic"] == pytest.approx(0.72, abs=0.001)
    assert result["btc_per_share_basic"] == pytest.approx(0.002407, abs=0.000001)
    assert result["btc_per_share_diluted"] == pytest.approx(0.002203, abs=0.000001)

def test_parse_mnav_page_returns_none_on_missing():
    result = parse_mnav_page("<html><body>no data here</body></html>")
    assert result is None

def test_compute_mnav_diluted():
    data = {
        "mnav_basic": 0.72,
        "btc_per_share_basic": 0.002407,
        "btc_per_share_diluted": 0.002203,
    }
    mnav_diluted = compute_mnav_diluted(data)
    assert mnav_diluted == pytest.approx(0.72 * (0.002407 / 0.002203), rel=0.001)

def test_fetch_mnav_uses_config_fallback_on_failure():
    config = {"mnav_override": 0.85, "btc_holdings": 845256}
    with patch("scraper.requests.get", side_effect=Exception("network error")):
        result = fetch_mnav(config)
    assert result["mnav_diluted"] == 0.85
    assert result["source"] == "config"

def test_fetch_mnav_returns_none_when_no_fallback():
    config = {"mnav_override": None, "btc_holdings": 845256}
    with patch("scraper.requests.get", side_effect=Exception("network error")):
        result = fetch_mnav(config)
    assert result is None
