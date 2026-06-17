import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

from scraper import fetch_mnav, fetch_btc_yield
from signals import fetch_yfinance_data, fetch_mstr_funding_rate, compute_all_indicators
from targets import compute_nav_per_share, compute_targets, compute_funding_cost

load_dotenv()

KST = timezone(timedelta(hours=9))
INTERVAL_SEC = 4 * 3600
CONFIG_PATH = "config.json"
STATE_PATH = "state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("mstr_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

SCORE_EMOJI = {1: "🟢", 0: "🟡", -1: "🔴"}
SIGNAL_EMOJI = {
    "STRONG LONG": "🚀",
    "LONG BIAS": "🟢",
    "WATCH / NEUTRAL": "🟡",
    "CAUTION": "🟠",
    "STRONG SHORT": "🔴",
}
SIGNAL_DIRECTION = {
    "STRONG LONG": "long",
    "LONG BIAS": "long",
    "WATCH / NEUTRAL": "watch",
    "CAUTION": "short",
    "STRONG SHORT": "short",
}


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_signal": None, "last_score": None, "last_daily_report_date": None}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_send_alert(signal, score, state):
    """(발송 여부, 일일요약 여부) 반환"""
    last_signal = state.get("last_signal")
    last_date = state.get("last_daily_report_date")
    kst_now = datetime.now(KST)
    today = kst_now.strftime("%Y-%m-%d")

    if signal != last_signal:
        return True, False
    if abs(score) >= 4:
        return True, False
    if kst_now.hour >= 9 and last_date != today:
        return True, True
    return False, False


def format_message(indicators, total, signal, targets_result, funding_rate, mstr_price, is_daily, prev_signal, errors, strc_severe):
    kst_now = datetime.now(KST)
    ts = kst_now.strftime("%Y-%m-%d %H:%M KST")
    sig_emoji = SIGNAL_EMOJI.get(signal, "🟡")

    lines = []
    prefix = "☀️ [일일 요약] " if is_daily else ""
    lines.append(f"{prefix}{sig_emoji} MSTR Signal: {signal}  (Score: {total:+d}/5)")
    lines.append("")

    lines.append("📊 자동 지표:")
    for ind in indicators:
        emoji = "❌" if ind["error"] else SCORE_EMOJI[ind["score"]]
        direction = "" if ind["error"] else {1: "LONG", 0: "WATCH", -1: "SHORT"}[ind["score"]]
        err_note = " (스크래핑 실패)" if ind["error"] else ""
        lines.append(f"  {ind['name']:<18} {ind['value_str']:<12} → {emoji} {direction}{err_note}")

    if targets_result and mstr_price:
        lines.append("")
        direction_str = SIGNAL_DIRECTION.get(signal, "watch")
        arrow = "📈 롱" if direction_str == "long" else "📉 숏"
        lines.append(f"💰 펍덱 진입 가이드 (현재가 ${mstr_price:.2f}):")
        lines.append(f"  {arrow} 기준:")
        tp1_p = targets_result["tp1_price"]
        tp2_p = targets_result["tp2_price"]
        sl_p = targets_result["sl_price"]
        tp1_pct = targets_result["tp1_pct"]
        tp2_pct = targets_result["tp2_pct"]
        sl_pct = targets_result["sl_pct"]
        lines.append(f"    SL:  ${sl_p:.2f}  ({sl_pct:+.1f}%)  [2×ATR14]")
        lines.append(f"    TP1: ${tp1_p:.2f}  ({tp1_pct:+.1f}%)  [mNAV 1.5×]")
        lines.append(f"    TP2: ${tp2_p:.2f}  ({tp2_pct:+.1f}%)  [mNAV 2.0×]")

        if funding_rate is not None:
            daily = compute_funding_cost(funding_rate, 100)
            direction_note = "지출" if direction_str == "long" and funding_rate > 0 else "수취"
            lines.append("")
            lines.append(f"  💸 MSTR 펀딩: {funding_rate*100:.4f}%/8h")
            lines.append(f"     $100당 하루 약 ${abs(daily):.4f} {direction_note}")

    lines.append("")
    lines.append(f"🕐 {ts}")

    if prev_signal and prev_signal != signal:
        lines.append(f"⚠️ 시그널 변경: {prev_signal} → {signal}")

    if errors:
        lines.append(f"❌ 데이터 실패: {', '.join(errors)}")

    if strc_severe:
        lines.append(f"⚠️ STRC 심각 디페그 — 신용 스트레스로 STRONG SHORT 강제 (원점수 {total:+d})")

    return "\n".join(lines)


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    resp.raise_for_status()


def run_cycle(token, chat_id):
    config = load_config()
    state = load_state()

    log.info("데이터 수집 시작")

    mnav_result = fetch_mnav(config)
    market_data = fetch_yfinance_data()
    funding_rate = fetch_mstr_funding_rate()
    btc_yield_result = fetch_btc_yield(config)

    indicators, total, signal, errors, strc_severe = compute_all_indicators(
        mnav_result, market_data, funding_rate, btc_yield_result, config
    )

    if errors:
        log.warning("데이터 실패: %s", errors)

    targets_result = None
    mstr_price = market_data["mstr_price"] if market_data else None
    direction = SIGNAL_DIRECTION.get(signal, "watch")

    if direction != "watch" and market_data:
        btc_per_share_diluted = mnav_result.get("btc_per_share_diluted") if mnav_result else None
        mnav_diluted = mnav_result.get("mnav_diluted") if mnav_result else None
        nav = compute_nav_per_share(
            btc_price=market_data["btc_price"],
            btc_per_share_diluted=btc_per_share_diluted,
            mnav_diluted=mnav_diluted,
            mstr_price=mstr_price,
        )
        if nav:
            targets_result = compute_targets(direction, mstr_price, nav, market_data["atr14"])

    prev_signal = state.get("last_signal")
    send, is_daily = should_send_alert(signal, total, state)

    if send:
        message = format_message(
            indicators, total, signal, targets_result,
            funding_rate, mstr_price, is_daily, prev_signal, errors, strc_severe
        )
        try:
            send_telegram(token, chat_id, message)
            log.info("알림 발송: %s (Score: %+d)", signal, total)
        except Exception as e:
            log.error("텔레그램 발송 실패: %s", e)

        kst_now = datetime.now(KST)
        kst_today = kst_now.strftime("%Y-%m-%d")
        daily_done = is_daily or kst_now.hour >= 9
        new_state = {
            "last_signal": signal,
            "last_score": total,
            "last_daily_report_date": kst_today if daily_done else state.get("last_daily_report_date"),
        }
        save_state(new_state)
    else:
        log.info("알림 없음: %s (Score: %+d) — 변화 없음", signal, total)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        log.error(".env 파일에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 설정하시오.")
        return

    log.info("MSTR 시그널 봇 시작")

    while True:
        try:
            run_cycle(token, chat_id)
        except Exception as e:
            log.error("사이클 오류: %s", e)
        log.info("%d시간 후 재실행", INTERVAL_SEC // 3600)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
