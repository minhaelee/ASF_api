"""ASF v4 4.7 — 갱신 계층. mafra API를 호출해 신규 발생만 마스터 CSV에 추가한다.

**계층 분리 원칙(4.7, 절대 지킬 것)**: 이 모듈은 판정 계층(app/grade.py 등)과 절대
섞이지 않는다. `grade()`는 CSV만 읽는 순수 함수로 남고, 이 모듈이 CSV를 갱신하는 흐름은
app/main.py의 요청 처리 경로에서만 트리거된다 — grade() 안에서 refresh_master()를
부르면 판정 경로가 네트워크에 의존하게 돼 리플레이가 재현 불가능해지고 4.4 검증 자체가
무효화된다.

**엔드포인트 (작업지시서 4.7에서 실측 확인)**:
    http://211.237.50.150:7080/openapi/{키}/xml/Grid_20151204000000000316_1/{시작}/{끝}
- 한글 필터(LKNTS_NM) 서버 사이드 불가 — 전체를 받아 클라이언트(여기)에서 질병명으로 거른다.
- 999행/호출 제한 — 페이지네이션 필요(시작/끝 인덱스를 페이지 크기만큼 밀어가며 반복 호출).
- 비SSL(http, 포트 7080). Claude Code 실행 환경에서는 이 호출이 차단될 수 있어(4.7),
  호출부는 여기서 구현하되 실제 동작 검증은 사용자 로컬 환경에서 수행한다.
- 이 API 자체가 2026년 27건 중 7건이 누락돼 있다(보령·당진·김천·홍성 + 3건) — 갱신을
  붙여도 완전한 실시간 반영은 아니다. T4 한계 항목(docs/T4_한계.md 5번)에 이미 반영됨.

**응답 구조·필드명 (2026-08-24 실제 키로 1회 호출해 실측 확인)**:
```
<Grid_20151204000000000316_1>
  <totalCnt>46084</totalCnt><startRow>1</startRow><endRow>5</endRow>
  <result><message>정상 처리되었습니다.</message><code>INFO-000</code></result>
  <row>
    <ROW_NUM>1</ROW_NUM>
    <ICTSD_OCCRRNC_NO>00000230</ICTSD_OCCRRNC_NO>   (발생 고유번호)
    <LKNTS_NM>돼지오제스키병</LKNTS_NM>              (질병명 — 작업지시서 4.7에 실측 언급된 필드)
    <FARM_NM>정지창</FARM_NM>                        (농장명)
    <FARM_LOCPLC_LEGALDONG_CODE>4146125029</...>     (법정동코드 10자리 — master CSV의 legaldong)
    <FARM_LOCPLC>경기도 용인시 처인구 포곡읍 신원리</...>  (주소 — master CSV의 address)
    <OCCRRNC_DE>20030530</OCCRRNC_DE>                (발생일 — master CSV의 case_date)
    <LVSTCKSPC_CODE>413000</...><LVSTCKSPC_NM>돼지</...>
    <OCCRRNC_LVSTCKCNT>1</OCCRRNC_LVSTCKCNT>         (감염두수 — master CSV의 infected)
    <DGNSS_ENGN_CODE>...</...><DGNSS_ENGN_NM>...</...>
    <CESSATION_DE>20040403</CESSATION_DE>
  </row>
  ...
</Grid_20151204000000000316_1>
```
전체 46,084건(전 축종·전 질병, 2003년분까지 있음) 중 질병명이 "아프리카돼지열병"인
행만 클라이언트에서 거른다(서버 사이드 한글 필터 불가 — 2026-08-24 재확인: 쿼리스트링에
LKNTS_NM을 붙이면 ERROR-500이 바로 남).

**자동 갱신은 전체가 아니라 최근 MAFRA_RECENT_WINDOW_ROWS행만 받는다(2026-08-24
변경)**: 행 번호 1이 2003년 자료이고 행 번호가 클수록 최신이므로("등록 순서로 쌓인다"는
전제, 실측 확인), 우리가 실제로 필요한 "마지막 확인 이후 새로 등록된 행"만 보려면
전체(47페이지)를 받을 필요가 없다. 요청 수를 줄이면 아래 서버 불안정에 걸릴 확률도
같이 준다 — 실측 도중 페이지가 많을수록(요청을 많이 할수록) 중간에 빈 페이지가 나오는
사례를 반복 관찰했다. 전체 재확인이 필요한 일회성 감사용으로 `_fetch_all_rows()`는
남겨뒀다(`python -m app.master_refresh --full`).
"""

import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pandas as pd
import requests

from app.config import (
    MAFRA_API_BASE,
    MAFRA_API_KEY,
    MAFRA_GRID_ID,
    MAFRA_PAGE_SIZE,
    MAFRA_RECENT_WINDOW_ROWS,
    MASTER_PATH,
)

DISEASE_FIELD = "LKNTS_NM"  # 질병명 — 작업지시서 4.7에서 유일하게 실측 확인된 필드명
DISEASE_VALUE = "아프리카돼지열병"

# 2026-08-24 실제 키로 1회 호출해 확인한 필드명(모듈 docstring 응답 예시 참고).
FIELD_MAP = {
    "case_date": "OCCRRNC_DE",
    "address": "FARM_LOCPLC",
    "infected": "OCCRRNC_LVSTCKCNT",
    "legaldong": "FARM_LOCPLC_LEGALDONG_CODE",
}

class MasterRefreshError(Exception):
    pass


def _fetch_page(start: int, end: int) -> tuple[list[dict], int | None]:
    url = f"{MAFRA_API_BASE}/{MAFRA_API_KEY}/xml/{MAFRA_GRID_ID}/{start}/{end}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    total_el = root.find("totalCnt")
    total_cnt = int(total_el.text) if total_el is not None and total_el.text else None
    rows = [
        {child.tag: (child.text or "").strip() for child in row_el}
        for row_el in root.findall("row")
    ]
    return rows, total_cnt


_MAX_PAGE_RETRIES = 3
_RETRY_BASE_DELAY_SEC = 2.0
_INTER_PAGE_DELAY_SEC = 0.3


def _fetch_range(start: int, end_total: int) -> list[dict]:
    """[start, end_total] 구간을 999행씩 나눠 받는다.

    각 페이지마다 요청한 만큼(end-start+1) 정확히 받았는지 확인한다 — 실측으로 확인된
    서버 불안정성(2026-08-24, 페이지가 간헐적으로 짧거나 통째로 0행을 반환) 때문에
    "짧은 페이지 = 데이터 끝"이라고 믿으면 안 된다. 여기서는 [start, end_total] 범위가
    호출부에서 미리 고정돼 있으므로(전체든 최근 N행이든), 매 페이지 "정확히 이만큼
    요청했다"는 게 명확해 재시도 조건이 단순하다. 재시도 후에도 못 채우면 예외를 던져
    refresh_master()가 "갱신 실패"로 처리하게 한다(조용히 데이터가 빠진 채 "신규 0건"
    으로 오보하는 것보다 안전).
    """
    rows: list[dict] = []
    cursor = start
    while cursor <= end_total:
        end = min(cursor + MAFRA_PAGE_SIZE - 1, end_total)
        want = end - cursor + 1
        page: list[dict] = []
        for attempt in range(_MAX_PAGE_RETRIES):
            page, _ = _fetch_page(cursor, end)
            if len(page) >= want:
                break
            time.sleep(_RETRY_BASE_DELAY_SEC * (attempt + 1))
        else:
            raise MasterRefreshError(
                f"페이지({cursor}-{end}) 응답이 {_MAX_PAGE_RETRIES}회 재시도에도 불안정함 "
                f"(이번 수신 {len(page)}행, 요청 {want}행)"
            )
        rows.extend(page[:want])
        cursor = end + 1
        if cursor <= end_total:
            time.sleep(_INTER_PAGE_DELAY_SEC)
    return rows


def _fetch_total_count() -> int:
    """totalCnt만 필요한 가벼운 확인 호출(1행) — 이것도 실측으로 간헐적 실패가 확인돼
    (2026-08-24) 다른 페이지 호출과 동일하게 재시도한다."""
    for attempt in range(_MAX_PAGE_RETRIES):
        _, total_cnt = _fetch_page(1, 1)
        if total_cnt is not None:
            return total_cnt
        time.sleep(_RETRY_BASE_DELAY_SEC * (attempt + 1))
    raise MasterRefreshError(
        f"totalCnt를 {_MAX_PAGE_RETRIES}회 재시도에도 읽을 수 없음 — 서버 응답 형식이 예상과 다름"
    )


def _fetch_all_rows() -> list[dict]:
    """전체 데이터셋(현재 ~46,084건, ~47회 호출, 수십 초)을 처음부터 끝까지 받는다.
    자동 갱신(refresh_master)은 이걸 쓰지 않고 _fetch_recent_rows를 쓴다 — 요청 수를
    줄여 서버 간헐적 불안정에 덜 걸리게 하기 위함. 전체 재검증이 필요한 일회성 감사용."""
    total_cnt = _fetch_total_count()
    return _fetch_range(1, total_cnt)


def _fetch_recent_rows(window: int) -> list[dict]:
    """가장 최근 등록된 window행만 받는다 — 자동 갱신(refresh_master)의 기본 경로.

    이 API는 행 번호(1~totalCnt) 범위로만 조회 가능한데, 실측 결과 1번 행이 2003년
    자료라 행 번호가 클수록 최신이다(등록 순서로 쌓여있는 것으로 보임). 우리가 실제로
    필요한 건 "마지막 확인 이후 새로 등록된 행"뿐이므로 전체를 매번 받을 필요가 없다.
    dedup은 case_date+address 키로 하므로(4.7), window가 넉넉해 일부 겹쳐 받아도 무해하다.
    """
    total_cnt = _fetch_total_count()
    start = max(1, total_cnt - window + 1)
    return _fetch_range(start, total_cnt)


def _validate_field_map(sample_row: dict) -> None:
    if DISEASE_FIELD not in sample_row:
        raise MasterRefreshError(
            f"질병명 필드({DISEASE_FIELD})가 실제 응답에 없음. "
            f"이 API 응답의 실제 필드명: {sorted(sample_row.keys())}"
        )
    missing = [k for k in ("case_date", "address") if not FIELD_MAP.get(k)]
    if missing:
        raise MasterRefreshError(
            f"FIELD_MAP 미확정: {missing}. app/master_refresh.py의 FIELD_MAP을 아래 실제 "
            f"필드명으로 채운 뒤 다시 시도할 것 — 이 API 응답의 실제 필드명: {sorted(sample_row.keys())}"
        )
    unmatched = [k for k, v in FIELD_MAP.items() if v and v not in sample_row]
    if unmatched:
        raise MasterRefreshError(
            f"FIELD_MAP에 채워둔 필드명이 실제 응답과 불일치: {unmatched}. "
            f"이 API 응답의 실제 필드명: {sorted(sample_row.keys())}"
        )


def _to_case_rows(raw_rows: list[dict]) -> list[dict]:
    """ASF만 걸러 master CSV 스키마에 맞춘 dict로 변환. source는 이 API 유래임을
    표시하기 위해 항상 'mafra_api'로 채운다(2.1 표의 기존 표기와 일치)."""
    out = []
    for row in raw_rows:
        if DISEASE_VALUE not in row.get(DISEASE_FIELD, ""):
            continue
        case_date = row.get(FIELD_MAP["case_date"], "").strip()
        address = row.get(FIELD_MAP["address"], "").strip()
        if not case_date or not address:
            continue
        infected = row.get(FIELD_MAP.get("infected") or "", "").strip()
        legaldong = row.get(FIELD_MAP.get("legaldong") or "", "").strip()
        out.append({
            "case_date": case_date,
            "address": address,
            "legaldong": legaldong,
            "infected": infected,
            "published_on": "",
            "cha": "",
            "source": "mafra_api",
        })
    return out


def _merge_into_master(new_cases: list[dict]) -> int:
    """master CSV에 신규 발생만 추가한다(기존 행은 절대 덮어쓰지 않음).
    중복 판정 키: case_date + address(4.7). 반환: 실제로 추가된 건수."""
    if not new_cases:
        return 0

    existing = pd.read_csv(MASTER_PATH, encoding="utf-8-sig", dtype=str)
    existing_keys = set(zip(existing["case_date"], existing["address"]))

    to_add = [c for c in new_cases if (c["case_date"], c["address"]) not in existing_keys]
    if not to_add:
        return 0

    add_df = pd.DataFrame(to_add).reindex(columns=existing.columns.tolist(), fill_value="")
    combined = pd.concat([existing, add_df], ignore_index=True)
    combined.to_csv(MASTER_PATH, index=False, encoding="utf-8-sig")
    return len(to_add)


def refresh_master() -> dict:
    """mafra API를 호출해 신규 ASF 발생만 마스터 CSV에 추가한다.

    **예외를 던지지 않는다** — 무엇이 실패하든 기존 CSV로 서비스가 정상 동작해야 한다(4.7
    "API 실패 시 기존 CSV로 정상 동작"). 호출부(app/main.py)는 이 반환값만 보고
    "마지막 갱신" 상태를 화면에 표시한다.

    반환: {"checked_at": ISO시각, "added": int, "error": str|None}
    """
    checked_at = datetime.now(timezone.utc).isoformat()

    if not MAFRA_API_KEY:
        msg = "MAFRA_API_KEY 없음 — 갱신 건너뜀, 기존 CSV로 계속 동작"
        print(f"[master_refresh] {msg}")
        return {"checked_at": checked_at, "added": 0, "error": msg}

    try:
        raw_rows = _fetch_recent_rows(MAFRA_RECENT_WINDOW_ROWS)
    except Exception as e:
        msg = f"mafra API 호출 실패: {type(e).__name__}: {e}"
        print(f"[master_refresh] {msg}")
        return {"checked_at": checked_at, "added": 0, "error": msg}

    if not raw_rows:
        msg = "mafra API 응답 0건"
        print(f"[master_refresh] {msg}")
        return {"checked_at": checked_at, "added": 0, "error": msg}

    try:
        _validate_field_map(raw_rows[0])
    except MasterRefreshError as e:
        print(f"[master_refresh] {e}")
        return {"checked_at": checked_at, "added": 0, "error": str(e)}

    new_cases = _to_case_rows(raw_rows)
    try:
        added = _merge_into_master(new_cases)
    except Exception as e:
        msg = f"마스터 CSV 병합 실패: {type(e).__name__}: {e}"
        print(f"[master_refresh] {msg}")
        return {"checked_at": checked_at, "added": 0, "error": msg}

    print(f"[master_refresh] 신규 {added}건 추가 (조회 {len(raw_rows)}건 중 ASF {len(new_cases)}건)")
    return {"checked_at": checked_at, "added": added, "error": None}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--full" in sys.argv:
        rows = _fetch_all_rows()
        asf = _to_case_rows(rows)
        print(f"전체 {len(rows)}건 중 ASF {len(asf)}건 (일회성 감사 — CSV에 반영 안 함)")
    else:
        print(refresh_master())
