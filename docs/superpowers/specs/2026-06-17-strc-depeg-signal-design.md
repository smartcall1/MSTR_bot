# STRC 디페그 시그널 추가 설계

## 배경
Strategy의 변동금리 영구 우선주 STRC($100 par)가 다시 디페그 진행 중 (직전 저점 $90.38, 현재 ~$95.2). Strategy는 100달러 페깅을 위해 배당률을 7~8차례 인상하고 월 1회→2회로 지급 빈도를 늘렸음에도 페깅 실패 상태. STRC 디페그 심화는 Strategy의 우선주 배당 지급 능력에 대한 시장의 신용 스트레스 신호이며, 이는 가장 후순위인 MSTR 보통주에 직접적 악재로 연결됨. 기존 5개 지표(mNAV, BTC Yield, vs MA200, MSTR/BTC RS, MSTR 펀딩레이트)에 STRC 디페그를 6번째 지표로 추가.

## 핵심 설계 결정
- STRC 디페그는 다른 5개 지표와 성격이 다름: 연속 스펙트럼(밸류에이션/모멘텀)이 아니라 "정상 vs 신용 스트레스" 이진적 리스크 이벤트. 프리미엄이 붙어도 호재가 아니므로 점수는 0/-1만 가능(편측).
- 가중치는 백테스트 데이터가 없어 임의의 숫자로 정당화하지 않음. 대신 "가산 점수 + 심각 시 리스크 오버라이드(캡)" 구조로 반영 — 신용 스트레스가 다른 지표의 긍정 신호를 상쇄/제한하는 본연의 성격을 구조적으로 표현.

## 데이터 수집
- `fetch_yfinance_data()` (signals.py)에서 `STRC` 티커 종가를 함께 수집. 별도 함수 불필요, 기존 yfinance 세션에 통합.
- STRC 배당 지급일 전후 ex-div 효과로 가격이 ~1% 출렁일 수 있음 — 5%/10% 임계값이 이 노이즈보다 충분히 크므로 별도 보정 없음.
- 실패 시 기존 패턴과 동일하게 `market_data`가 None이면 STRC 지표도 N/A 처리.

## 점수 함수 (signals.py)
```python
def score_strc_depeg(strc_price):
    """STRC 디페그 점수. None이면 0(WATCH). 할인율 5% 초과(<$95)면 -1, 그 외 0."""
    if strc_price is None:
        return 0
    discount_pct = (100 - strc_price) / 100 * 100
    if discount_pct > 5:
        return -1
    return 0


def is_strc_severe_depeg(strc_price):
    """할인율 10% 초과(<$90)면 심각 디페그로 판정 — 리스크 오버라이드 트리거."""
    if strc_price is None:
        return False
    return (100 - strc_price) / 100 * 100 > 10
```

## 리스크 오버라이드 (캡)
심각 디페그(`is_strc_severe_depeg() == True`) 시, 다른 지표 합산 결과가 아무리 좋아도 최종 시그널을 **STRONG SHORT로 강제**. (1차 설계는 CAUTION 캡이었으나, 사용자 피드백으로 변경: mNAV 등 다른 지표의 LONG 신호가 STRC 디페그와 같은 근본 원인(세일러 자금 경색)의 다른 증상일 수 있어 독립적이지 않으므로, 약한 "주의" 수준이 아니라 명확한 SHORT 결론을 내야 함.)

심각도 순서: `STRONG LONG(2) > LONG BIAS(1) > WATCH/NEUTRAL(0) > CAUTION(-1) > STRONG SHORT(-2)`

`compute_score()`에 `strc_severe_depeg: bool = False` 파라미터 추가. 클램프 로직:
```python
SIGNAL_SEVERITY = {
    "STRONG LONG": 2, "LONG BIAS": 1, "WATCH / NEUTRAL": 0,
    "CAUTION": -1, "STRONG SHORT": -2,
}

def compute_score(indicator_scores, strc_severe_depeg=False):
    total = sum(indicator_scores)
    signal = SIGNAL_LABELS.get(total, "WATCH / NEUTRAL")
    if strc_severe_depeg and SIGNAL_SEVERITY[signal] > SIGNAL_SEVERITY["STRONG SHORT"]:
        signal = "STRONG SHORT"
    return total, signal
```

**점수-라벨 표시 불일치 처리**: 캡이 적용되면 `total`(원래 합산 점수, 예: +4)과 `signal`(STRONG SHORT)이 모순되게 보일 수 있음. 메시지에 `total`은 원래 값 그대로 표시하고, 캡이 적용된 경우 별도 줄에 `(원점수 {total:+d}, STRC 심각 디페그로 STRONG SHORT 강제)` 주석을 덧붙여 투명하게 표시.

## 총점 범위 변경
- 기존 ±5(5개 지표) → +5 / -6 (STRC는 음수만 가능한 비대칭 6번째 지표)
- `SIGNAL_LABELS`에 `-6: "STRONG SHORT"` 추가

## compute_all_indicators() 통합
- 인자에 `market_data`에서 STRC 가격 추출 (`market_data.get("strc_price")`) 추가 사용
- 6번째 indicator dict 추가: `{"name": "STRC 디페그", "value_str": f"${strc_price:.2f} ({discount:+.1f}%)", "score": sc, "error": ...}`
- `is_strc_severe_depeg()` 결과를 반환값에 추가하여 `bot.py`의 `compute_score()` 호출에 전달

## 메시지 표시 (bot.py)
- 기존 지표 라인 목록에 STRC 디페그 자동 추가 (5번째 지표와 동일한 포맷)
- 심각 디페그 시 메시지 하단에 별도 경고 줄 추가: `⚠️ STRC 심각 디페그 — 신용 스트레스로 STRONG SHORT 강제 (원점수 {total:+d})`

## 테스트
- `test_signals.py`에 `score_strc_depeg`, `is_strc_severe_depeg` 단위 테스트 추가 (LONG 케이스 없음 — 0/-1만)
- `compute_score()` 캡 동작 테스트: STRONG LONG 합산 + severe_depeg=True → CAUTION으로 강제됨 확인
- 기존 5지표 테스트는 무영향 (하위 호환 — `strc_severe_depeg` 기본값 False)

## 범위 외
- STRC 외 다른 우선주(STRK, STRF, STRD) 디페그는 포함하지 않음 — 사용자가 STRC만 언급했고, 추가 시 별도 요청 시 확장
- ex-div 보정, 변동금리 변경 추적 등 정교화는 향후 데이터 누적 후 별도 작업
