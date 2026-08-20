"""ASF T3 v2 — 시군 상세 패널 ②(등급 근거)용: "가장 가까운 최근 발생 + 거리 + 경과일".

grade_stub(자기 시군 발생 유무만 봄, 거리 계산 없음)과도, farm_order(개별 농장 좌표가
기준점)와도 다른 세 번째 계산이다 — 시군 폴리곤의 대략적 중심(geo_normalize.rough_centroid)
에서 최근 발생까지의 거리를 잰다. 이 값은 farm_order의 1위 농장 거리와 정확히 일치하지
않을 수 있다(기준점이 다르므로) — 버그 아님, 호출부(app/main.py)가 이 사실을 note로
같이 내려보낸다.

RADIUS_KM(10km)을 넘으면 None을 돌려준다 — 전국에서 가장 가까운 케이스를 무조건
보여주면(반경 제한 없이) 200km 밖 사례도 "가장 가까운 최근 발생"으로 표시돼 오독을
부른다(실측으로 발견: 화천군에서 192km 떨어진 홍성군 사례가 나온 적 있음). farm_order가
쓰는 것과 같은 반경 기준을 맞춰, "근거로 보여줄 만큼 가깝다"는 뜻을 유지한다.
"""

import pandas as pd

from app.config import MASTER_GEOCODED_PATH
from app.constants import RADIUS_KM, RECENT_WINDOW_DAYS
from app.date_utils import parse_yyyymmdd
from app.geo_distance import haversine_km
from app.geo_normalize import centroid_for_code


def nearest_recent_case(sigun_code: str, as_of: str) -> dict | None:
    centroid = centroid_for_code(sigun_code)
    if centroid is None:
        return None
    lat, lon = centroid

    df = pd.read_csv(MASTER_GEOCODED_PATH, encoding="utf-8-sig")
    as_of_date = parse_yyyymmdd(as_of)
    days_ago = df["case_date"].apply(lambda d: (as_of_date - parse_yyyymmdd(d)).days)
    recent = df[(days_ago >= 0) & (days_ago <= RECENT_WINDOW_DAYS)]
    if recent.empty:
        return None

    best = None
    for _, case in recent.iterrows():
        d = haversine_km(lat, lon, case["위도"], case["경도"])
        if best is None or d < best[0]:
            best = (d, case)

    dist, case = best
    if dist > RADIUS_KM:
        return None

    days_since = (as_of_date - parse_yyyymmdd(case["case_date"])).days
    return {
        "case_date": str(int(case["case_date"])),
        "address": case["address"],
        "distance_km": round(dist, 2),
        "days_since": days_since,
    }


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    from app.geo_normalize import code_to_name

    code = "38370"
    as_of = "20260330"
    print(code_to_name(code), nearest_recent_case(code, as_of))
