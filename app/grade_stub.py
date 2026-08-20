"""ASF T3 — 임시 등급 함수. **T2가 아직 없어서 목요일 파이프라인을 끝까지 돌리기 위한 대역**이다.

작업지시서 4.2의 진짜 규칙(인근 시군 10km 반경, 3주, 3단계)은 아직 여기 없다.
이 함수는 "자기 시군 자체 발생 이력만" 본다 — 인근 시군 반경 계산은 전혀 하지 않는다.
그 반경 로직은 T2(금·토)가 만들 실제 grade()가 담당한다.

로직: as_of 기준으로 같은 시군의 발생 중 가장 최근 것과의 날짜 차이만 본다.
    21일 이내 발생 있음 -> 심각
    90일 이내 발생 있음 -> 주의
    그 외(또는 발생 이력 없음)          -> 평시

순수 함수 — 전역 상태나 현재 시각을 참조하지 않는다(작업지시서 4.4, 미래 정보 유출 방지).
그래서 as_of보다 미래인 case는 여기서 걸러낸다(cases에 어떤 시점 데이터가 섞여 들어오든
안전하도록).

이 모듈은 openai/requests 등 네트워크 관련 import가 전혀 없다 — 등급 판정에 LLM이
관여하지 않는다는 원칙(작업지시서 원칙 3)을 코드 구조로도 보장하기 위함이다.
"""

from datetime import date, timedelta

IS_STUB = True
STUB_NOTE = "임시 등급 함수 — 자기 시군 최근성만 반영, 반경 10km 로직 없음. T2 완성 후 교체 예정."

SIM_THRESHOLD_DAYS = 21
JUJUI_THRESHOLD_DAYS = 90


def _parse_yyyymmdd(s: str) -> date:
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def grade(sigun_code: str, as_of: str, cases: list[dict]) -> dict:
    """sigun_code: geo_normalize의 5자리 시군구 코드. as_of: "YYYYMMDD".
    cases: [{"sgg_code": ..., "case_date": "YYYYMMDD", ...}, ...] — Node1 산출물.

    반환: {"grade": "평시"|"주의"|"심각", "is_stub": True, "note": STUB_NOTE,
           "matched_cases": [...], "days_since_last": int|None}
    """
    as_of_date = _parse_yyyymmdd(as_of)

    relevant = [
        c for c in cases
        if c.get("sgg_code") == sigun_code and _parse_yyyymmdd(c["case_date"]) <= as_of_date
    ]

    if not relevant:
        return {
            "grade": "평시",
            "is_stub": IS_STUB,
            "note": STUB_NOTE,
            "matched_cases": [],
            "days_since_last": None,
        }

    latest = max(relevant, key=lambda c: c["case_date"])
    days_since = (as_of_date - _parse_yyyymmdd(latest["case_date"])).days

    if days_since <= SIM_THRESHOLD_DAYS:
        g = "심각"
    elif days_since <= JUJUI_THRESHOLD_DAYS:
        g = "주의"
    else:
        g = "평시"

    return {
        "grade": g,
        "is_stub": IS_STUB,
        "note": STUB_NOTE,
        "matched_cases": relevant,
        "days_since_last": days_since,
    }
