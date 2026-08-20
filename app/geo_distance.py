"""ASF T3 v2 — 대권거리(haversine). 저장소에 이전까지 없었다(geocode_farms.py::in_korea는
bbox 체크일 뿐 거리 계산이 아님). farm_order/nearest_case가 공유한다.
"""

import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    seoul = (37.5665, 126.9780)
    busan = (35.1796, 129.0756)
    print(f"서울-부산: {haversine_km(*seoul, *busan):.1f} km (기대값 ~325km)")
