def compute_nav_per_share(btc_price, btc_per_share_diluted, mnav_diluted, mstr_price):
    """
    희석 주당 BTC NAV 계산.
    btc_per_share_diluted 우선 사용, 없으면 mstr_price / mnav_diluted 폴백.
    """
    if btc_per_share_diluted is not None and btc_price is not None:
        return btc_price * btc_per_share_diluted
    if mnav_diluted and mnav_diluted > 0 and mstr_price:
        return mstr_price / mnav_diluted
    return None


def compute_targets(signal_direction, mstr_price, nav_per_share, atr14):
    """
    signal_direction: "long" | "short" | "watch"
    mNAV 기준 목표가가 시그널 방향과 어긋나면(예: mNAV는 저평가인데 다른 지표
    때문에 숏 시그널) NAV 자체가 신뢰할 수 없는 상황이므로 ATR 기준으로 대체.
    Returns dict with tp1_price, tp2_price, sl_price, tp1_pct, tp2_pct, sl_pct,
    tp1_label, tp2_label. signal_direction == "watch"이면 None.
    """
    if signal_direction == "watch" or nav_per_share is None:
        return None
    if not mstr_price or mstr_price <= 0:
        return None

    if signal_direction == "long":
        tp1 = nav_per_share * 1.5
        tp2 = nav_per_share * 2.0
        sl = mstr_price - (2 * atr14)
        if tp1 <= mstr_price:
            # mNAV가 시그널 방향과 어긋남 — ATR 기준으로 대체
            tp1 = mstr_price + (2 * atr14)
            tp2 = mstr_price + (4 * atr14)
            tp1_label, tp2_label = "ATR 2×", "ATR 4×"
        else:
            tp1_label, tp2_label = "mNAV 1.5×", "mNAV 2.0×"
    else:  # short
        tp1 = nav_per_share * 1.2
        tp2 = nav_per_share * 0.9
        sl = mstr_price + (2 * atr14)
        if tp1 >= mstr_price:
            # mNAV가 시그널 방향과 어긋남 — ATR 기준으로 대체
            tp1 = mstr_price - (2 * atr14)
            tp2 = mstr_price - (4 * atr14)
            tp1_label, tp2_label = "ATR 2×", "ATR 4×"
        else:
            tp1_label, tp2_label = "mNAV 1.2×", "mNAV 0.9×"

    return {
        "tp1_price": tp1,
        "tp1_pct": (tp1 / mstr_price - 1) * 100,
        "tp1_label": tp1_label,
        "tp2_price": tp2,
        "tp2_pct": (tp2 / mstr_price - 1) * 100,
        "tp2_label": tp2_label,
        "sl_price": sl,
        "sl_pct": (sl / mstr_price - 1) * 100,
    }


def compute_funding_cost(rate_8h, position_usd=100):
    """하루 펀딩 비용 (position_usd 기준, 8h × 3회)"""
    return rate_8h * 3 * position_usd
