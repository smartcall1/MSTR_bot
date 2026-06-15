import re
import requests
from bs4 import BeautifulSoup

URL = "https://bitcointreasuries.net/public-companies/strategy"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Mobile Safari/537.36"
    )
}


def _extract_float(text):
    """'0.72×', '0.002407' 같은 문자열에서 float 추출"""
    cleaned = re.sub(r"[^\d.]", "", text.strip())
    return float(cleaned) if cleaned else None


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
    except Exception:
        pass

    override = config.get("mnav_override")
    if override is not None:
        return {
            "mnav_diluted": float(override),
            "btc_per_share_diluted": None,
            "source": "config",
        }

    return None
