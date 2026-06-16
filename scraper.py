import re
import logging
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

URL = "https://bitcointreasuries.net/public-companies/strategy"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Mobile Safari/537.36"
    )
}

PRESS_URL = "https://www.strategy.com/press"
DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
BTC_YIELD_RE = re.compile(r"BTC Yield of ([\d.]+)%\s*YTD", re.IGNORECASE)


def _extract_float(text):
    """'0.72×', '0.002407' 같은 문자열에서 첫 번째 숫자 추출"""
    match = re.search(r"\d+\.?\d*", text.strip())
    return float(match.group()) if match else None


def parse_mnav_page(html):
    """
    HTML에서 mNAV(Basic), BTC/Share(Basic/Diluted) 파싱.
    성공 시 dict 반환, 실패 시 None.
    """
    soup = BeautifulSoup(html, "html.parser")

    targets = {
        "mnav_basic": ["mnav (basic)", "mnav(basic)", "mnav - basic"],
        "btc_per_share_basic": ["btc / share (basic)", "btc/share (basic)", "btc per share (basic)"],
        "btc_per_share_diluted": ["btc / share (diluted)", "btc/share (diluted)", "btc per share (diluted)"],
    }

    result = {}
    for key, labels in targets.items():
        for elem in soup.find_all(string=True):
            if any(lbl in elem.lower() for lbl in labels):
                parent = elem.parent
                next_elem = parent.find_next_sibling()
                if next_elem:
                    val = _extract_float(next_elem.get_text())
                    if val:
                        result[key] = val
                        break

    if len(result) < 3:
        return None
    return result


def compute_mnav_diluted(data):
    """
    data: parse_mnav_page() 반환값
    returns: diluted mNAV (float)
    """
    ratio = data["btc_per_share_basic"] / data["btc_per_share_diluted"]
    return data["mnav_basic"] * ratio


def fetch_mnav(config):
    """
    bitcointreasuries.net 스크래핑 시도.
    실패 시 config["mnav_override"] 폴백.
    반환: {"mnav_diluted": float, "btc_per_share_diluted": float|None, "source": str}
          또는 None (완전 실패)
    """
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = parse_mnav_page(resp.text)
        if data:
            return {
                "mnav_diluted": compute_mnav_diluted(data),
                "btc_per_share_diluted": data["btc_per_share_diluted"],
                "source": "scrape",
            }
    except Exception as e:
        log.warning("bitcointreasuries 스크래핑 실패: %s", e)

    override = config.get("mnav_override")
    if override is not None:
        return {
            "mnav_diluted": float(override),
            "btc_per_share_diluted": None,
            "source": "config",
        }

    return None


def fetch_btc_yield(config):
    """
    strategy.com 보도자료 목록(최신순)에서 가장 최근 "BTC Yield of X% YTD" 문구를 스크래핑.
    실패 또는 미발견 시 config["btc_yield"] 폴백.
    반환: {"btc_yield": float, "source": str} 또는 None (완전 실패)
    """
    try:
        resp = requests.get(PRESS_URL, headers=DESKTOP_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"^/press/")):
            match = BTC_YIELD_RE.search(a.get_text())
            if match:
                return {"btc_yield": float(match.group(1)), "source": "scrape"}
    except Exception as e:
        log.warning("strategy.com BTC Yield 스크래핑 실패: %s", e)

    override = config.get("btc_yield")
    if override is not None:
        return {"btc_yield": float(override), "source": "config"}

    return None
