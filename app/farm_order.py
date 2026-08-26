"""ASF T3 v2 — 농장 점검 순서 (작업지시서 4.5). 스텁이 아니라 최종 함수다: 규칙 자체가
이미 확정 상태이고, 필요한 좌표(발생지점/농장)가 이미 다 있어 임시 버전을 둘 이유가 없다.

대상: as_of 기준 최근 3주(RECENT_WINDOW_DAYS) 내 발생지로부터 10km(RADIUS_KM) 이내 농장,
      단 해당 농장이 sigun_code 소속인 것만(발생 케이스 자체는 시군 제한 없음 — 4.2가
      신호를 "인근 시군의 최근 발생"으로 정의하므로 국경 인접 농장이 이웃 시군 발생과
      더 가까울 수 있다).
정렬: 거리(1km 버킷) 오름차순 -> 버킷 내 사육두수 내림차순. 가중합 점수 아님(4.5).
      사육두수 결측(2026-08-26(7차) 국가 인허가 데이터로 전체 교체 이후 전 농장 100%
      결측 — 이 데이터엔 사육두수 컬럼 자체가 없음, 위치 커버리지를 우선한 트레이드오프
      로 사용자가 명시적으로 선택)은 0이 아니라 버킷 내 최하위로 보낸다 — "확인된 소규모"와
      "모름"을 구분하기 위함이었으나, 지금은 사실상 전부 이 경로를 타 거리 단독 정렬과
      동일하게 동작한다.
반환 딕셔너리에 "등급" 필드를 두지 않는다 — 시군 층의 용어가 농장 층으로 새는 것을 막는다.
"축종" 필드는 있다(2026-08-26(7차) 추가) — 도축장도 ASF 전파 경로로 지목돼 데이터에
같이 포함되면서, 화면이 농장과 도축장을 구분해 보여줄 수 있게 한다.
"""

import math

import pandas as pd

from app.config import FARMS_PATH, MASTER_GEOCODED_PATH
from app.constants import DEFAULT_FARM_ORDER_LIMIT, RADIUS_KM, RECENT_WINDOW_DAYS
from app.date_utils import parse_yyyymmdd
from app.geo_distance import haversine_km
from app.geo_normalize import resolve_address


def _recent_cases(as_of: str) -> pd.DataFrame:
    df = pd.read_csv(MASTER_GEOCODED_PATH, encoding="utf-8-sig")
    as_of_date = parse_yyyymmdd(as_of)
    days_ago = df["case_date"].apply(lambda d: (as_of_date - parse_yyyymmdd(d)).days)
    return df[(days_ago >= 0) & (days_ago <= RECENT_WINDOW_DAYS)]


def farm_order(sigun_code: str, as_of: str, limit: int = DEFAULT_FARM_ORDER_LIMIT) -> list[dict]:
    recent = _recent_cases(as_of)
    if recent.empty:
        return []

    farms = pd.read_csv(FARMS_PATH, encoding="utf-8-sig").dropna(subset=["위도", "경도"])
    candidates = farms[farms["주소"].apply(lambda a: resolve_address(str(a)) == sigun_code)]

    results = []
    for idx, farm in candidates.iterrows():
        best_dist, best_case = None, None
        for _, case in recent.iterrows():
            d = haversine_km(farm["위도"], farm["경도"], case["위도"], case["경도"])
            if best_dist is None or d < best_dist:
                best_dist, best_case = d, case

        if best_dist is None or best_dist > RADIUS_KM:
            continue

        headcount = farm["사육두수"]
        results.append({
            # FARMS_PATH는 이 프로젝트에서 수정되지 않는 정적 참조 파일이라(발생 마스터
            # CSV와 달리 갱신 계층이 안 건드림), pandas가 매번 부여하는 원본 행 인덱스가
            # 요청마다 안정적이다 — app/biosecurity_checks.py가 이 값을 농장의 영구
            # 식별자로 그대로 쓴다.
            "farm_id": int(idx),
            "farm_name": farm["농장명"] if pd.notna(farm["농장명"]) else None,
            # 2026-08-26(7차) — farms_geocoded.csv에 도축장도 섞여 들어오면서(ASF 전파
            # 경로로 지목되는 시설이라 포함) 화면이 농장과 구분해 보여줄 수 있게 넘긴다.
            "축종": farm["축종"] if pd.notna(farm["축종"]) else "돼지",
            "address": farm["주소"],
            "사육두수": None if pd.isna(headcount) else float(headcount),
            "distance_km": round(best_dist, 2),
            "nearest_case_date": str(int(best_case["case_date"])),
            "nearest_case_address": best_case["address"],
        })

    def sort_key(r):
        bucket = math.floor(r["distance_km"])
        headcount = r["사육두수"]
        neg_headcount = -headcount if headcount is not None else math.inf
        return (bucket, neg_headcount)

    results.sort(key=sort_key)
    return results[:limit]


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    from app.geo_normalize import code_to_name

    code = "38370"  # 산청군, 2026년 사료 매개 사례 인근
    as_of = "20260330"
    out = farm_order(code, as_of)
    print(f"{code_to_name(code)} ({code}) as_of={as_of}: {len(out)}건")
    for r in out[:5]:
        print(" ", r)
