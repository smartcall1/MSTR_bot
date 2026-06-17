import logging
import requests
import yfinance as yf
import pandas as pd

log = logging.getLogger(__name__)

SIGNAL_LABELS = {
    5: "STRONG LONG", 4: "STRONG LONG",
    3: "LONG BIAS", 2: "LONG BIAS",
    1: "WATCH / NEUTRAL", 0: "WATCH / NEUTRAL", -1: "WATCH / NEUTRAL",
    -2: "CAUTION", -3: "CAUTION",
    -4: "STRONG SHORT", -5: "STRONG SHORT", -6: "STRONG SHORT",
}

SIGNAL_SEVERITY = {
    "STRONG LONG": 2, "LONG BIAS": 1, "WATCH / NEUTRAL": 0,
    "CAUTION": -1, "STRONG SHORT": -2,
}

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/premiumIndex"


def score_mnav(value):
    if value is None:
        return 0
    if value < 1.2:
        return 1
    if value > 2.5:
        return -1
    return 0


def score_btc_yield(value):
    if value is None:
        return 0
    if value > 15:
        return 1
    if value < 0:
        return -1
    return 0


def score_ma200(current, ma200):
    pct = (current - ma200) / ma200 * 100
    if pct > 5:
        return 1
    if pct < -5:
        return -1
    return 0


def score_rs_30d(mstr_30d, btc_30d):
    diff = mstr_30d - btc_30d
    if diff > 10:
        return 1
    if diff < -10:
        return -1
    return 0


def score_funding_rate(rate_8h):
    if rate_8h is None:
        return 0
    if rate_8h < 0.0001:
        return 1
    if rate_8h > 0.0005:
        return -1
    return 0


def score_strc_depeg(strc_price):
    """STRC(우선주) 디페그 점수. 할인율 5% 초과(<$95)면 -1, 그 외 0.
    프리미엄/패리티는 호재가 아니므로 +1은 없음 (편측 리스크 지표)."""
    if strc_price is None:
        return 0
    discount_pct = (100 - strc_price) / 100 * 100
    if discount_pct > 5:
        return -1
    return 0


def is_strc_severe_depeg(strc_price):
    """할인율 10% 초과(<$90)면 심각 디페그 — 리스크 오버라이드 트리거."""
    if strc_price is None:
        return False
    discount_pct = (100 - strc_price) / 100 * 100
    return discount_pct > 10


def compute_score(indicator_scores, strc_severe_depeg=False):
    total = sum(indicator_scores)
    signal = SIGNAL_LABELS.get(total, "WATCH / NEUTRAL")
    if strc_severe_depeg and SIGNAL_SEVERITY[signal] > SIGNAL_SEVERITY["STRONG SHORT"]:
        signal = "STRONG SHORT"
    return total, signal


def fetch_yfinance_data():
    """MSTR + BTC 시장 데이터 수집. 실패 시 None 반환."""
    try:
        mstr = yf.Ticker("MSTR")
        btc = yf.Ticker("BTC-USD")

        mstr_hist = mstr.history(period="1y").dropna(subset=["Close"])
        btc_hist = btc.history(period="40d").dropna(subset=["Close"])

        if mstr_hist.empty or btc_hist.empty:
            return None

        mstr_price = float(mstr_hist["Close"].iloc[-1])
        btc_price = float(btc_hist["Close"].iloc[-1])
        ma200 = float(mstr_hist["Close"].rolling(200).mean().iloc[-1])

        mstr_30d = float(
            (mstr_hist["Close"].iloc[-1] / mstr_hist["Close"].iloc[-30] - 1) * 100
        )
        btc_30d = float(
            (btc_hist["Close"].iloc[-1] / btc_hist["Close"].iloc[-30] - 1) * 100
        )

        h, l, c = mstr_hist["High"], mstr_hist["Low"], mstr_hist["Close"]
        tr = pd.concat([
            h - l,
            (h - c.shift(1)).abs(),
            (l - c.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])

        strc_hist = yf.Ticker("STRC").history(period="5d").dropna(subset=["Close"])
        strc_price = float(strc_hist["Close"].iloc[-1]) if not strc_hist.empty else None

        return {
            "mstr_price": mstr_price,
            "btc_price": btc_price,
            "ma200": ma200,
            "mstr_30d": mstr_30d,
            "btc_30d": btc_30d,
            "atr14": atr14,
            "strc_price": strc_price,
        }
    except Exception as e:
        log.warning("yfinance 데이터 수집 실패: %s", e)
        return None


def fetch_mstr_funding_rate():
    """Binance USDT-M 선물에서 MSTR 펀딩레이트(8h) 조회. 실패 시 None.

    Note: Hyperliquid에는 MSTR(MicroStrategy) 종목이 상장되어 있지 않음.
          Binance MSTRUSDT 퍼프 선물에서 lastFundingRate를 사용.
    """
    try:
        resp = requests.get(
            BINANCE_FAPI,
            params={"symbol": "MSTRUSDT"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        rate = data.get("lastFundingRate")
        if rate is None:
            log.warning("Binance MSTRUSDT 응답에 lastFundingRate 없음: %s", data)
            return None

        return float(rate)
    except Exception as e:
        log.warning("Binance MSTR 펀딩레이트 수집 실패: %s", e)
        return None


def compute_all_indicators(mnav_result, market_data, funding_rate, btc_yield_result, config):
    """
    모든 지표를 계산하여 결과 반환.
    Returns: indicators (list), total_score (int), signal (str), errors (list)
    """
    indicators = []
    errors = []

    # 1. mNAV Diluted
    if mnav_result:
        mnav_val = mnav_result["mnav_diluted"]
        sc = score_mnav(mnav_val)
        indicators.append({
            "name": "mNAV(Diluted)",
            "value_str": f"{mnav_val:.2f}×",
            "score": sc,
            "error": False,
        })
    else:
        errors.append("mNAV")
        indicators.append({"name": "mNAV(Diluted)", "value_str": "N/A", "score": 0, "error": True})

    # 2. BTC Yield (strategy.com 보도자료 자동 스크래핑, 실패 시 config 폴백)
    if btc_yield_result:
        btc_yield = btc_yield_result["btc_yield"]
        sc = score_btc_yield(btc_yield)
        note = " (config)" if btc_yield_result["source"] == "config" else ""
        indicators.append({
            "name": "BTC Yield",
            "value_str": f"{btc_yield:.1f}%{note}",
            "score": sc,
            "error": False,
        })
    else:
        errors.append("BTC Yield")
        indicators.append({"name": "BTC Yield", "value_str": "N/A", "score": 0, "error": True})

    # 3. vs MA200
    if market_data:
        sc = score_ma200(market_data["mstr_price"], market_data["ma200"])
        pct = (market_data["mstr_price"] - market_data["ma200"]) / market_data["ma200"] * 100
        indicators.append({
            "name": "vs MA200",
            "value_str": f"{pct:+.1f}%",
            "score": sc,
            "error": False,
        })
    else:
        errors.append("yfinance(MA200)")
        indicators.append({"name": "vs MA200", "value_str": "N/A", "score": 0, "error": True})

    # 4. MSTR/BTC 상대강도
    if market_data:
        sc = score_rs_30d(market_data["mstr_30d"], market_data["btc_30d"])
        diff = market_data["mstr_30d"] - market_data["btc_30d"]
        indicators.append({
            "name": "MSTR/BTC RS",
            "value_str": f"{diff:+.1f}%",
            "score": sc,
            "error": False,
        })
    else:
        errors.append("yfinance(RS)")
        indicators.append({"name": "MSTR/BTC RS", "value_str": "N/A", "score": 0, "error": True})

    # 5. MSTR 펀딩레이트
    if funding_rate is not None:
        sc = score_funding_rate(funding_rate)
        indicators.append({
            "name": "MSTR 펀딩",
            "value_str": f"{funding_rate*100:.4f}%/8h",
            "score": sc,
            "error": False,
        })
    else:
        errors.append("Binance(펀딩)")
        indicators.append({"name": "MSTR 펀딩", "value_str": "N/A", "score": 0, "error": True})

    scores = [ind["score"] for ind in indicators]
    total, signal = compute_score(scores)

    return indicators, total, signal, errors
