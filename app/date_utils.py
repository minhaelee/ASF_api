"""ASF T3 — YYYYMMDD 파싱 공용 함수. grade_stub/farm_order/nearest_case가 각자 들고 있던
버전을 통합했다. `str(int(s))`를 거치는 이유: MASTER_GEOCODED_PATH를 pandas로 읽으면
case_date가 int64로 들어와 int/str 어느 쪽이 오든 안전하게 처리해야 하기 때문.
"""

from datetime import date


def parse_yyyymmdd(s) -> date:
    s = str(int(s))
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
