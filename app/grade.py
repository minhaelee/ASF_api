"""ASF T2 — 진짜 등급 함수 (작업지시서 v3 4.2). `app/grade_stub.py`를 대체한다.

**인자는 거리와 시간, 둘뿐이다.**
    as_of 기준 최근 3주(RECENT_WINDOW_DAYS) 이내 발생 중, 시군 경계(폴리곤)까지의
    최단거리(app.geo_distance.point_to_shapely_polygon_distance_km)가:
        10km 이내(RADIUS_KM)          -> 심각 (법정 방역대)
        10km~20km(WARNING_RADIUS_KM)  -> 주의
        그 외(20km 초과, 또는 3주 경과) -> 평시

사육밀도·재발이력 등 다른 인자는 절대 넣지 않는다 — 넣으면 상시 고위험 시군이 발생 없는
주에도 항상 평시가 아니게 돼, 리플레이 지표 B(같은 시군 안 시점 간 비교)의 비교 대상인
'평시' 주 자체가 사라진다(4.2 "등급 인자에 넣지 않는 것" 참조).

좌표는 인자로 받지 않고 MASTER_GEOCODED_PATH(발생 마스터 지오코딩 결과)에서 직접
읽는다 — farm_order.py/nearest_case.py와 같은 패턴. Node1(extraction)의 산출물은
좌표가 없으므로(LLM이 좌표를 만들지 않는다는 설계) 여기서 쓰지 않는다. 그래서
작업지시서 원문 그대로 `grade(sigun_code, as_of)` 2인자다.

순수 함수 — 전역 상태·현재 시각 참조 없음(4.4, 미래 정보 유출 방지). 시군 폴리곤은
모듈 로드 시 한 번만 준비해둔다(매 호출마다 같은 GeoJSON을 다시 파싱하지 않도록).
"""

import functools

import pandas as pd
from shapely.geometry import shape

from app.config import MASTER_GEOCODED_PATH
from app.constants import RADIUS_KM, RECENT_WINDOW_DAYS, WARNING_RADIUS_KM
from app.date_utils import parse_yyyymmdd
from app.geo_distance import point_to_shapely_polygon_distance_km
from app.geo_normalize import all_sgg_codes, geometry_for_code

IS_STUB = False
GRADE_METHOD_NOTE = (
    f"등급을 매기는 기준: 최근 3주 안에 발생한 사례 중 이 시군 경계선에서 가장 가까운 "
    f"거리를 봅니다. {RADIUS_KM}km 이내면 심각, {RADIUS_KM}~{WARNING_RADIUS_KM}km면 주의, "
    f"그보다 멀거나(또는 3주가 지났으면) 평시로 표시합니다."
)

# 시군 250개 폴리곤을 모듈 로드 시 한 번만 shapely로 파싱해둔다 — grade()가 시군마다
# 반복 호출되므로(Node2가 전국을 순회), 매 호출마다 같은 GeoJSON을 다시 파싱하지 않는다.
_SHAPELY_POLYGONS = {code: shape(geometry_for_code(code)) for code in all_sgg_codes()}


@functools.lru_cache(maxsize=64)
def _recent_cases(as_of: str) -> pd.DataFrame:
    """as_of별로 캐시한다 — Node2가 같은 as_of로 250번(시군마다) 부르므로, 82행짜리
    CSV라도 250번 다시 읽고 필터링하는 건 불필요한 반복이다. 반환 DataFrame은
    호출부에서 읽기만 하고 수정하지 않는다."""
    df = pd.read_csv(MASTER_GEOCODED_PATH, encoding="utf-8-sig")
    as_of_date = parse_yyyymmdd(as_of)
    days_ago = df["case_date"].apply(lambda d: (as_of_date - parse_yyyymmdd(d)).days)
    return df[(days_ago >= 0) & (days_ago <= RECENT_WINDOW_DAYS)]


def grade(sigun_code: str, as_of: str) -> dict:
    """반환: {"grade": "평시"|"주의"|"심각", "is_stub": False,
              "nearest_distance_km": float|None, "nearest_case": dict|None,
              "days_since_last": int|None}"""
    poly = _SHAPELY_POLYGONS.get(sigun_code)
    if poly is None:
        raise ValueError(f"알 수 없는 시군구 코드: {sigun_code}")

    recent = _recent_cases(as_of)
    as_of_date = parse_yyyymmdd(as_of)

    if recent.empty:
        return {
            "grade": "평시",
            "is_stub": IS_STUB,
            "nearest_distance_km": None,
            "nearest_case": None,
            "days_since_last": None,
        }

    best_dist, best_case = None, None
    for _, case in recent.iterrows():
        d = point_to_shapely_polygon_distance_km(case["위도"], case["경도"], poly)
        if best_dist is None or d < best_dist:
            best_dist, best_case = d, case

    if best_dist <= RADIUS_KM:
        g = "심각"
    elif best_dist <= WARNING_RADIUS_KM:
        g = "주의"
    else:
        g = "평시"

    days_since = (as_of_date - parse_yyyymmdd(best_case["case_date"])).days

    return {
        "grade": g,
        "is_stub": IS_STUB,
        "nearest_distance_km": round(best_dist, 2),
        "nearest_case": {
            "case_date": str(int(best_case["case_date"])),
            "address": best_case["address"],
        },
        "days_since_last": days_since,
    }


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    from app.geo_normalize import code_to_name

    # 파주시(31200) — 8건으로 가장 많이 발생한 큰 시군. 경계 근처 케이스로 심각/주의
    # 갈림이 중심점 방식과 달라지는지 확인하는 스팟체크.
    for code in ["31200", "32370"]:  # 파주시, 화천군
        for as_of in ["20260330", "20180101"]:
            g = grade(code, as_of)
            print(f"{code_to_name(code)} as_of={as_of}: {g['grade']} "
                  f"(최단거리 {g['nearest_distance_km']}km, {g['days_since_last']}일 전)")
