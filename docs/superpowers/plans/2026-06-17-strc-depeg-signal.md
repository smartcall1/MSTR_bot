# STRC 디페그 시그널 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MSTR 시그널 봇에 STRC(Strategy 우선주) 디페그를 6번째 지표로 추가하고, 심각 디페그 시 다른 지표 점수와 무관하게 최종 시그널을 STRONG SHORT로 강제하는 리스크 오버라이드를 구현한다.

**Architecture:** `signals.py`에 STRC 가격 수집(`fetch_yfinance_data`에 통합)과 점수/심각도 판정 함수를 추가하고, `compute_score()`에 캡 로직을, `compute_all_indicators()`에 6번째 지표 조립을 추가한다. `bot.py`는 새 반환값(`strc_severe`)을 받아 메시지에 경고 줄을 추가한다.

**Tech Stack:** Python, yfinance, pytest, unittest.mock

## Global Constraints

- 점수 함수는 None 입력 시 0 반환 (기존 5개 지표와 동일한 폴백 패턴, signals.py 기존 함수들 참조)
- 할인율 5% 초과(STRC 가격 < $95) → 점수 -1, 그 외 0 (편측 — 프리미엄/패리티는 0)
- 할인율 10% 초과(STRC 가격 < $90) → `is_strc_severe_depeg()` True (심각 디페그)
- 심각 디페그 시 시그널을 **STRONG SHORT로 강제**: `STRONG LONG(2) > LONG BIAS(1) > WATCH/NEUTRAL(0) > CAUTION(-1) > STRONG SHORT(-2)` 순서에서 이미 STRONG SHORT가 아니면 모두 STRONG SHORT로 클램프 (다른 지표의 LONG 신호가 STRC 디페그와 동일 원인의 다른 증상일 수 있어 독립적이지 않다고 보고 약한 캡 대신 명확한 SHORT 결론 채택)
- 캡 적용으로 `total`(원래 합산 점수)과 `signal`(STRONG SHORT)이 모순돼 보일 수 있으므로, 메시지에 원점수를 함께 표시해 투명하게 처리
- `SIGNAL_LABELS`에 `-6: "STRONG SHORT"` 추가 필요 (총점 범위 +5 / -6으로 비대칭 확장)
- 기존 5개 지표 동작과 기존 테스트 20개는 모두 그대로 통과해야 함 (하위 호환)
- STRC 가격 조회는 `fetch_yfinance_data()`에 통합. 빈 히스토리면 `strc_price: None`으로 두고 함수 전체를 실패시키지 않음 (MSTR/BTC 데이터는 그대로 살림)

---

### Task 1: STRC 가격 수집을 `fetch_yfinance_data()`에 통합

**Files:**
- Modify: `signals.py:73-114` (`fetch_yfinance_data` 함수)
- Test: `tests/test_scraper.py` 아님 — STRC는 `signals.py`에 있으므로 `tests/test_signals.py`에 추가

**Interfaces:**
- Consumes: 없음 (yfinance 직접 호출)
- Produces: `fetch_yfinance_data()` 반환 dict에 `"strc_price": float | None` 키 추가. 이후 Task 3에서 `compute_all_indicators()`가 `market_data.get("strc_price")`로 사용.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_signals.py` 맨 아래에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `python -m pytest tests/test_signals.py -k strc_price -v`
Expected: FAIL — `KeyError: 'strc_price'` (현재 `fetch_yfinance_data`가 이 키를 반환하지 않음)

- [ ] **Step 3: `fetch_yfinance_data()`에 STRC 수집 추가**

`signals.py`의 `fetch_yfinance_data()` 함수를 다음과 같이 수정 (atr14 계산 다음, return 문 앞에 추가):

```python
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
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

Run: `python -m pytest tests/test_signals.py -k strc_price -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 전체 signals 테스트 통과 확인 (회귀 없음)**

Run: `python -m pytest tests/test_signals.py -v`
Expected: 22 passed (기존 20개 + 신규 2개)

- [ ] **Step 6: 커밋**

```bash
git add signals.py tests/test_signals.py
git commit -m "feat: fetch_yfinance_data에 STRC 가격 수집 추가"
```

---

### Task 2: `score_strc_depeg()` / `is_strc_severe_depeg()` 점수 함수

**Files:**
- Modify: `signals.py` (기존 `score_*` 함수들 근처, `score_funding_rate` 다음 줄에 추가)
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: Task 1에서 만든 `market_data["strc_price"]`
- Produces: `score_strc_depeg(strc_price) -> int` (-1 또는 0), `is_strc_severe_depeg(strc_price) -> bool`. Task 4에서 `compute_all_indicators()`가 둘 다 호출.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_signals.py` import 줄을 다음으로 교체:

```python
from signals import (
    score_mnav, score_btc_yield,
    score_ma200, score_rs_30d, score_funding_rate,
    score_strc_depeg, is_strc_severe_depeg,
    compute_score, SIGNAL_LABELS,
)
```

그 아래 테스트 추가:

```python
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
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `python -m pytest tests/test_signals.py -k strc_depeg -v`
Expected: FAIL — `ImportError: cannot import name 'score_strc_depeg'`

- [ ] **Step 3: 함수 구현**

`signals.py`의 `score_funding_rate` 함수 (line 57-64) 바로 다음에 추가:

```python
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
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

Run: `python -m pytest tests/test_signals.py -k strc_depeg -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add signals.py tests/test_signals.py
git commit -m "feat: STRC 디페그 점수/심각도 판정 함수 추가"
```

---

### Task 3: `compute_score()` 리스크 오버라이드(캡) + `SIGNAL_LABELS` 확장

**Files:**
- Modify: `signals.py:8-14` (`SIGNAL_LABELS`), `signals.py:67-70` (`compute_score`)
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: Task 2의 `is_strc_severe_depeg()` 결과 (bool)
- Produces: `compute_score(indicator_scores, strc_severe_depeg=False) -> (total: int, signal: str)`. 기존 호출부(`compute_all_indicators`, 향후 Task 4)는 두 번째 인자를 생략하면 기존과 동일하게 동작.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_signals.py`에 추가:

```python
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
    total, signal = compute_score([-1, -1, 0, 0, 0, -1], strc_severe_depeg=True)
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
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `python -m pytest tests/test_signals.py -k "minus_six or severe_depeg or not_severe" -v`
Expected: FAIL — `test_compute_score_total_minus_six_is_strong_short`는 `signal == "WATCH / NEUTRAL"` 반환(SIGNAL_LABELS에 -6 없어 기본값), `severe_depeg` 테스트는 `TypeError: compute_score() got an unexpected keyword argument 'strc_severe_depeg'`

- [ ] **Step 3: `SIGNAL_LABELS`와 `compute_score()` 수정**

`signals.py` 상단 `SIGNAL_LABELS` (line 8-14)를 다음으로 교체:

```python
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
```

`compute_score()` (line 67-70)를 다음으로 교체:

```python
def compute_score(indicator_scores, strc_severe_depeg=False):
    total = sum(indicator_scores)
    signal = SIGNAL_LABELS.get(total, "WATCH / NEUTRAL")
    if strc_severe_depeg and SIGNAL_SEVERITY[signal] > SIGNAL_SEVERITY["STRONG SHORT"]:
        signal = "STRONG SHORT"
    return total, signal
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

Run: `python -m pytest tests/test_signals.py -v`
Expected: 모두 PASS (Task 1, 2의 테스트 포함 누적)

- [ ] **Step 5: 커밋**

```bash
git add signals.py tests/test_signals.py
git commit -m "feat: STRC 심각 디페그 시 시그널 STRONG SHORT로 강제"
```

---

### Task 4: `compute_all_indicators()`에 STRC 6번째 지표 통합

**Files:**
- Modify: `signals.py:143-224` (`compute_all_indicators`)
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: Task 1의 `market_data["strc_price"]`, Task 2의 `score_strc_depeg`/`is_strc_severe_depeg`, Task 3의 `compute_score(scores, strc_severe_depeg)`
- Produces: `compute_all_indicators(...) -> (indicators: list, total: int, signal: str, errors: list, strc_severe: bool)` — **반환값이 4개에서 5개로 변경됨**. Task 5(`bot.py`)가 5개 튜플을 언패킹.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_signals.py`에 추가 (`compute_all_indicators`를 import 줄에 추가):

```python
from signals import (
    score_mnav, score_btc_yield,
    score_ma200, score_rs_30d, score_funding_rate,
    score_strc_depeg, is_strc_severe_depeg,
    compute_score, compute_all_indicators, SIGNAL_LABELS,
)

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
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `python -m pytest tests/test_signals.py -k compute_all_indicators -v`
Expected: FAIL — `ValueError: not enough values to unpack (expected 5, got 4)`

- [ ] **Step 3: `compute_all_indicators()` 수정**

`signals.py`의 `compute_all_indicators()` 함수 (line 143-224)에서, 5번째 지표(MSTR 펀딩) 블록 (line 208-219) 바로 다음, `scores = [...]` 줄 (line 221) 이전에 추가:

```python
    # 6. STRC 디페그 (Strategy 우선주 신용 스트레스 — 편측 리스크 지표)
    strc_price = market_data.get("strc_price") if market_data else None
    if strc_price is not None:
        sc = score_strc_depeg(strc_price)
        deviation_pct = (strc_price - 100) / 100 * 100
        indicators.append({
            "name": "STRC 디페그",
            "value_str": f"${strc_price:.2f} ({deviation_pct:+.1f}% vs par)",
            "score": sc,
            "error": False,
        })
        strc_severe = is_strc_severe_depeg(strc_price)
    else:
        errors.append("yfinance(STRC)")
        indicators.append({"name": "STRC 디페그", "value_str": "N/A", "score": 0, "error": True})
        strc_severe = False
```

그리고 함수 마지막 부분 (line 221-224)을 다음으로 교체:

```python
    scores = [ind["score"] for ind in indicators]
    total, signal = compute_score(scores, strc_severe)

    return indicators, total, signal, errors, strc_severe
```

- [ ] **Step 4: 테스트 실행하여 통과 확인**

Run: `python -m pytest tests/test_signals.py -v`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add signals.py tests/test_signals.py
git commit -m "feat: compute_all_indicators에 STRC 디페그 6번째 지표 통합"
```

---

### Task 5: `bot.py` 메시지에 STRC 경고 줄 추가 + 호출부 업데이트

**Files:**
- Modify: `bot.py:82-131` (`format_message`), `bot.py:144-202` (`run_cycle`)

**Interfaces:**
- Consumes: Task 4의 `compute_all_indicators(...) -> (indicators, total, signal, errors, strc_severe)` 5-튜플
- Produces: 없음 (최종 출력단)

- [ ] **Step 1: `run_cycle()`의 언패킹과 `format_message` 호출 수정**

`bot.py` line 155-157:

```python
    indicators, total, signal, errors = compute_all_indicators(
        mnav_result, market_data, funding_rate, btc_yield_result, config
    )
```

다음으로 교체:

```python
    indicators, total, signal, errors, strc_severe = compute_all_indicators(
        mnav_result, market_data, funding_rate, btc_yield_result, config
    )
```

line 182-185:

```python
        message = format_message(
            indicators, total, signal, targets_result,
            funding_rate, mstr_price, is_daily, prev_signal, errors
        )
```

다음으로 교체:

```python
        message = format_message(
            indicators, total, signal, targets_result,
            funding_rate, mstr_price, is_daily, prev_signal, errors, strc_severe
        )
```

- [ ] **Step 2: `format_message()` 시그니처와 경고 줄 추가**

`bot.py` line 82:

```python
def format_message(indicators, total, signal, targets_result, funding_rate, mstr_price, is_daily, prev_signal, errors):
```

다음으로 교체:

```python
def format_message(indicators, total, signal, targets_result, funding_rate, mstr_price, is_daily, prev_signal, errors, strc_severe):
```

line 128-129 (`if errors:` 블록) 바로 다음에 추가:

```python
    if errors:
        lines.append(f"❌ 데이터 실패: {', '.join(errors)}")

    if strc_severe:
        lines.append(f"⚠️ STRC 심각 디페그 — 신용 스트레스로 STRONG SHORT 강제 (원점수 {total:+d})")

    return "\n".join(lines)
```

- [ ] **Step 3: 수동 통합 확인 (단위 테스트 없는 출력단이므로 스모크 테스트로 검증)**

Run:
```bash
python -c "
from signals import compute_all_indicators
from bot import format_message

market_data = {
    'mstr_price': 250.0, 'btc_price': 95000.0, 'ma200': 240.0,
    'mstr_30d': 5.0, 'btc_30d': 5.0, 'atr14': 8.0, 'strc_price': 89.0,
}
indicators, total, signal, errors, strc_severe = compute_all_indicators(
    mnav_result={'mnav_diluted': 0.9, 'btc_per_share_diluted': 1.0},
    market_data=market_data, funding_rate=0.00005,
    btc_yield_result={'btc_yield': 20.0, 'source': 'scrape'}, config={},
)
msg = format_message(indicators, total, signal, None, None, market_data['mstr_price'], False, None, errors, strc_severe)
print(msg)
assert 'STRC 심각 디페그' in msg
assert signal == 'STRONG SHORT'
print('OK')
"
```
Expected: 메시지 본문에 `STRC 디페그` 지표 줄과 `⚠️ STRC 심각 디페그 ... STRONG SHORT 강제` 경고 줄이 출력되고 마지막에 `OK` 출력

- [ ] **Step 4: 전체 테스트 스위트 회귀 확인**

Run: `python -m pytest tests/ -v`
Expected: 모두 PASS, 실패 0건

- [ ] **Step 5: 커밋**

```bash
git add bot.py
git commit -m "feat: 메시지에 STRC 디페그 지표 및 심각 경고 줄 표시"
```

---

## Self-Review Notes

- **스펙 커버리지**: 데이터 수집(Task 1), 점수 함수(Task 2), 리스크 오버라이드/SIGNAL_LABELS 확장(Task 3), compute_all_indicators 통합(Task 4), 메시지 표시(Task 5) — 설계 문서의 모든 섹션 반영. 범위 외로 명시한 STRK/STRF/STRD, ex-div 보정은 포함하지 않음.
- **타입 일관성**: `compute_all_indicators`가 4-튜플 → 5-튜플로 바뀌는 변경이 Task 4와 Task 5에 걸쳐 일관되게 적용됨 (`strc_severe` 이름 통일). `compute_score(indicator_scores, strc_severe_depeg=False)` 키워드명이 Task 3, 4에서 동일.
- **하위 호환**: `compute_score()` 두 번째 인자는 기본값 `False`이므로 기존 호출부(없다면)에는 영향 없음. 기존 20개 테스트는 6-요소 리스트를 이미 사용 중이라 무수정 통과.
