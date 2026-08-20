"""ASF T3 v2 — 정부 규정값 공용 상수. farm_order / nearest_case가 공유한다.

grade_stub.py의 SIM_THRESHOLD_DAYS(21)는 값이 우연히 같지만 별개 규칙(자기 시군
최근성 2단계 vs 반경 10km 최근 발생)이라 지금은 이 상수를 가져다 쓰지 않는다 —
T2가 진짜 grade()로 교체될 때 통합 여부를 판단한다.
"""

RADIUS_KM = 10  # 법정 방역대 반경 (작업지시서 4.2/4.5)
RECENT_WINDOW_DAYS = 21  # 이동제한 기간 3주 (작업지시서 4.2/4.5)
DEFAULT_FARM_ORDER_LIMIT = 20  # 작업지시서 4.5 "표시 개수는 사용자가 조절한다. 기본 20곳"
