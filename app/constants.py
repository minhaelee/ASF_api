"""ASF T2/T3 v3 — 정부 규정값 공용 상수. grade / farm_order / nearest_case가 공유한다."""

RADIUS_KM = 10  # 심각 등급 경계 = 법정 방역대 반경 (작업지시서 4.2/4.5)
WARNING_RADIUS_KM = 20  # 주의 등급 경계 (작업지시서 v3 4.2, 10~20km)
RECENT_WINDOW_DAYS = 21  # 이동제한 기간 3주 (작업지시서 4.2/4.5)
DEFAULT_FARM_ORDER_LIMIT = 20  # 작업지시서 4.5 "표시 개수는 사용자가 조절한다. 기본 20곳"
