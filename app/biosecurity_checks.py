"""ASF v3 — 농장별 방역시설 체크리스트(2026-08-26(6차) 피드백).

이 항목이 실제로 갖춰졌는지는 이 프로젝트의 어떤 데이터에도 없다(farms_geocoded.csv엔
농장명·주소·사육두수·좌표뿐 — 시설 설치 여부나 현장 점검 이력은 없음, KAHIS 등 정부
내부 시스템 접근 권한도 없음). 그래서 AI가 상태를 "판정"하지 않는다 — 담당자가 현장
방문 후 직접 체크한 값을 그대로 저장·표시만 하는 기록장이다(app/grade.py의 "AI는 판정
하지 않는다" 원칙을 여기서는 "이 앱은 현장 상태를 추정하지 않는다"로 확장 적용).

체크리스트 항목은 지어낸 게 아니라 실제 법령 조문에서 그대로 가져왔다:
  - 가축전염병 예방법 제17조제1항: 분무용 소독장비, 신발소독조, 울타리, 방조망
  - 방역실시요령 제7조제2항(중점방역관리지구 강화 기준): 전실, 출입차량 세척시설,
    고압분무기
  - 방역실시요령 제7조제4항: 소독실시 및 출입 기록부 작성·보존
시행규칙(농림축산식품부령)에 위임된 더 세부적인 규격·수량 기준은 이 프로젝트가 가진
문서에 없어 포함하지 않았다 — 있는 근거만큼만 체크리스트로 만든다.
"""

import psycopg2

from app.config import PGDATABASE, PGHOST, PGPASSWORD, PGPORT, PGUSER

FARM_BIOSECURITY_ITEMS = [
    {"key": "sprayer", "label": "분무용 소독장비", "basis": "가축전염병 예방법 제17조제1항"},
    {"key": "shoe_bath", "label": "신발소독조", "basis": "가축전염병 예방법 제17조제1항"},
    {"key": "fence", "label": "울타리", "basis": "가축전염병 예방법 제17조제1항"},
    {"key": "bird_net", "label": "방조망", "basis": "가축전염병 예방법 제17조제1항"},
    {"key": "anteroom", "label": "전실(방역복 탈착 공간)", "basis": "방역실시요령 제7조제2항"},
    {"key": "vehicle_wash", "label": "출입차량 세척시설", "basis": "방역실시요령 제7조제2항"},
    {"key": "high_pressure_sprayer", "label": "차량 바퀴·흙받이 소독용 고압분무기", "basis": "방역실시요령 제7조제2항"},
    {"key": "entry_log", "label": "소독실시 및 출입 기록부 작성·보존", "basis": "방역실시요령 제7조제4항"},
]
_VALID_KEYS = {item["key"] for item in FARM_BIOSECURITY_ITEMS}


def _connect():
    return psycopg2.connect(
        host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD
    )


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS farm_biosecurity_checks (
                farm_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (farm_id, item_key)
            );
            """
        )
    conn.commit()


# 매 요청마다 스키마를 확인하면 불필요한 왕복이 생기므로, 이 모듈이 처음 임포트될 때
# (앱 기동 시) 한 번만 만든다 — scripts/ingest_policy_pdf.py와 달리 이건 매번 서버가
# 뜰 때 자동으로 보장돼야 하는 런타임 스키마라 여기 둔다.
_conn = _connect()
_ensure_schema(_conn)
_conn.close()


def get_checklist(farm_id: int) -> dict:
    """반환: {"farm_id", "items": [{"key","label","basis","checked"}],
    "checked_count", "total_count"}"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT item_key FROM farm_biosecurity_checks WHERE farm_id = %s", (farm_id,)
            )
            checked_keys = {r[0] for r in cur.fetchall()}
    finally:
        conn.close()

    items = [{**item, "checked": item["key"] in checked_keys} for item in FARM_BIOSECURITY_ITEMS]
    return {
        "farm_id": farm_id,
        "items": items,
        "checked_count": len(checked_keys),
        "total_count": len(FARM_BIOSECURITY_ITEMS),
    }


def set_checklist(farm_id: int, checked_keys: list[str]) -> dict:
    """담당자가 화면에서 체크한 현재 상태 전체를 받아 그대로 덮어쓴다(멱등적 upsert) —
    이전 상태와 diff를 계산하지 않고 항상 "지금 체크된 것"만 남긴다."""
    checked_keys = [k for k in checked_keys if k in _VALID_KEYS]

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM farm_biosecurity_checks WHERE farm_id = %s", (farm_id,))
            if checked_keys:
                cur.executemany(
                    "INSERT INTO farm_biosecurity_checks (farm_id, item_key) VALUES (%s, %s)",
                    [(farm_id, k) for k in checked_keys],
                )
        conn.commit()
    finally:
        conn.close()

    return get_checklist(farm_id)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    test_farm_id = 999999
    print("초기 상태:", get_checklist(test_farm_id))
    print("체크 저장:", set_checklist(test_farm_id, ["sprayer", "fence", "entry_log"]))
    print("재조회:", get_checklist(test_farm_id))
    print("전체 해제:", set_checklist(test_farm_id, []))
