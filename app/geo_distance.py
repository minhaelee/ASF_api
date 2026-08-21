"""ASF T3 — 거리 계산 공용 함수. 저장소에 이전까지 haversine이 전혀 없었다
(geocode_farms.py::in_korea는 bbox 체크일 뿐 거리 계산이 아님).

point_to_polygon_distance_km: T2 v3(작업지시서 4.2)가 등급을 "시군 경계까지 최단거리"
기준으로 확정하면서 추가됐다. 시군을 중심점 하나로 뭉뚱그리면(v2 방식) 크고 긴 시군의
경계 근처 발생을 놓칠 수 있어, 사용자가 폴리곤 경계 기준 방식을 선택했다.

shapely의 `.distance()`는 위경도를 평면 좌표로 취급해 "어느 지점이 가장 가까운가"를
찾는 데만 쓰고, 실제 km 거리는 그 지점과 haversine으로 다시 잰다 — shapely 거리값을
그대로 km로 오인하지 않도록 함수를 두 단계로 나눴다.
"""

import math

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def point_to_shapely_polygon_distance_km(lat: float, lon: float, poly: BaseGeometry) -> float:
    """이미 shapely로 파싱된 폴리곤을 받는 버전. app/grade.py처럼 같은 폴리곤을 반복
    호출하는 곳(전국 250개 시군 순회)은 매번 shape(geometry)로 재파싱하지 않도록
    이 함수를 직접 쓰고, 파싱 결과를 호출부에서 캐시한다."""
    pt = Point(lon, lat)

    if poly.contains(pt) or poly.intersects(pt):
        return 0.0

    nearest_on_poly, _ = nearest_points(poly, pt)
    return haversine_km(lat, lon, nearest_on_poly.y, nearest_on_poly.x)


def point_to_polygon_distance_km(lat: float, lon: float, geometry: dict) -> float:
    """geometry: GeoJSON Polygon/MultiPolygon dict(좌표 순서 [lon, lat], GeoJSON 표준).
    한 번만 부르고 말 때 쓰는 간단한 버전 — 매번 shape(geometry)로 새로 파싱한다.
    반복 호출할 곳은 point_to_shapely_polygon_distance_km으로 파싱을 캐시할 것."""
    return point_to_shapely_polygon_distance_km(lat, lon, shape(geometry))


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    seoul = (37.5665, 126.9780)
    busan = (35.1796, 129.0756)
    print(f"서울-부산: {haversine_km(*seoul, *busan):.1f} km (기대값 ~325km)")
