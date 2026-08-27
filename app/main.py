"""ASF T3 v2 — FastAPI. 그래프/시군/농장 관련 로직은 전부 app/pipeline.py::run_pipeline()
경유 — LangGraph invoke가 코드베이스에 이 한 곳에만 있다는 것을 엔드포인트 레벨에서도
보장하기 위함. v2의 좌우 2단 대시보드(static/index.html)가 쓰는 /boundaries, /farms,
/outbreaks, /sigun/{code}가 이번에 추가됐다. 기존 /map(folium)은 대조용으로 당분간 유지.
"""

import sys

# Windows에서 uvicorn을 그냥 실행하면 콘솔 인코딩이 cp949라, 로그에 유니코드 특수문자
# (예: em dash "—")가 하나만 섞여도 print()가 UnicodeEncodeError를 던진다. 2026-08-24
# 실측으로 이게 app/master_refresh.py의 실패 로그 출력 중 발생해 FastAPI 시작 자체가
# 죽는 걸 확인했다(4.7 "API 실패해도 서비스는 정상 동작" 원칙 위반) — 모듈 임포트
# 시점에 한 번 재설정해 모든 print()가 안전하게 동작하도록 만든다.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

import math
from datetime import date, datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.biosecurity_checks import get_checklist, set_checklist
from app.briefing import generate_county_briefing, build_risk_list
from app.config import BOUNDARY_PATH, MASTER_GEOCODED_PATH, FARMS_PATH, MAFRA_REFRESH_INTERVAL_HOURS
from app.constants import DEFAULT_FARM_ORDER_LIMIT, WARNING_RADIUS_KM
from app.farm_order import farm_order
from app.field_response import build_field_response_cached
from app.geo_normalize import display_name, farm_coverage_codes
from app.mapping import build_map
from app.master_refresh import refresh_master
from app.pipeline import run_pipeline, run_pipeline_grades_only

app = FastAPI(title="ASF 점검 우선순위 도구 — T3 v2")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _default_as_of() -> str:
    return date.today().strftime("%Y%m%d")


# ASF v4 4.7 — 갱신 계층 상태. 판정 계층(grade())과는 절대 섞이지 않는다 — grade()는
# 여전히 CSV만 읽는 순수 함수이고, 이 상태는 오직 "언제 마지막으로 mafra API를
# 확인했는지"만 기록해 화면 상단에 보여주는 용도다.
_LAST_REFRESH: dict = {"checked_at": None, "added": 0, "error": "아직 갱신 시도 전"}


def _maybe_refresh(force: bool = False) -> None:
    global _LAST_REFRESH
    if not force and _LAST_REFRESH["checked_at"] is not None:
        elapsed_hours = (
            datetime.now(timezone.utc) - datetime.fromisoformat(_LAST_REFRESH["checked_at"])
        ).total_seconds() / 3600
        if elapsed_hours < MAFRA_REFRESH_INTERVAL_HOURS:
            return
    _LAST_REFRESH = refresh_master()


@app.on_event("startup")
def _startup_refresh():
    _maybe_refresh(force=True)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """v2 좌우 2단 대시보드(static/index.html) — 이번 세션 신규 기본 화면.
    /map(folium)은 개발 중 대조용으로 당분간 유지."""
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/refresh_status")
def refresh_status():
    """화면 상단 "마지막 갱신: {시각}" 표시용(4.7). 갱신 자체를 트리거하지 않고
    마지막 상태만 읽는다 — 트리거는 /pipeline/run, /sigun/{code} 호출 시 일어난다."""
    return _LAST_REFRESH


@app.get("/pipeline/run")
def pipeline_run(as_of: str | None = None):
    _maybe_refresh()
    as_of = as_of or _default_as_of()
    state = run_pipeline(as_of)

    # 이름을 키로 쓰면 전국에 이름이 겹치는 7개 시군(고성군 등)이 서로 덮어써 유실된다 —
    # 코드가 유일한 키이므로 코드로 키를 두고 이름은 값 안에 넣는다.
    grades_out = {
        code: {
            "name": display_name(code),
            "grade": g["grade"],
            "is_stub": g["is_stub"],
            "days_since_last": g["days_since_last"],
            "nearest_distance_km": g["nearest_distance_km"],
        }
        for code, g in state["grades"].items()
    }

    # 발생 이력은 있지만 farms_geocoded.csv에 없는 시군 — 대시보드가 "농장 데이터 미확보"
    # 라벨을 어디에 그릴지 결정하는 데 쓴다. 시군 해석 로직(geo_normalize)을 JS로
    # 중복 구현하지 않으려고 서버에서 계산해 내려준다.
    history_codes = {c["sgg_code"] for c in state["extracted_cases"] if c["sgg_code"] is not None}
    no_farm_data_codes = sorted(history_codes - farm_coverage_codes())

    return {
        "as_of": as_of,
        "grades": grades_out,
        "risk_list": build_risk_list(as_of, state["grades"]),
        "no_farm_data_codes": no_farm_data_codes,
        "extraction": state["extraction_meta"],
        "grade_meta": state["grade_meta"],
        "briefing": state["briefing"],
        "meta": {
            "pipeline_is_stub": state["grade_meta"]["is_stub"],
            "disclaimer": state["grade_meta"]["note"],
        },
    }


@app.get("/map", response_class=HTMLResponse)
def map_view(as_of: str | None = None):
    as_of = as_of or _default_as_of()
    state = run_pipeline(as_of)
    m = build_map(state)
    return m.get_root().render()


@app.get("/boundaries")
def boundaries():
    """전국 시군구 경계 GeoJSON 원본 그대로. as_of와 무관한 정적 파일이라 브라우저가
    캐시할 수 있다 — folium 버전(/map)은 매 요청마다 18MB를 페이지에 인라인 재삽입했는데,
    이 엔드포인트는 그 비효율을 없앤다."""
    return FileResponse(BOUNDARY_PATH, media_type="application/json")


FARM_JITTER_RADIUS_DEG = 0.0004  # 위도 기준 약 40m — 표시 전용, 판정 계층은 이 값을 절대 안 씀


@app.get("/farms")
def farms():
    """농장 점 전체(2026-08-26(7차) 국가 인허가 데이터 교체 후 5,736건, 표시 전용) — 클라이언트 Leaflet이 직접 그린다.

    한 주소에 복수 법인이 등록돼 좌표가 완전히 동일한 농장이 166그룹(648행) 있다(T1).
    지도에서 클러스터를 클릭해도 실제 좌표 차이가 없어 spiderfy(중앙에서 방사형으로
    흩어지는 표시)로만 분리되는데, 사용자 피드백으로 대신 원형으로 살짝 흩어 보이게
    한다 — 이 오프셋은 여기(표시용 엔드포인트)에서만 적용하고, 판정 계층(app/farm_order.py
    등)은 이 엔드포인트를 거치지 않고 FARMS_PATH 원본을 직접 읽으므로 등급/거리 계산에는
    전혀 영향이 없다.
    """
    df = pd.read_csv(FARMS_PATH, encoding="utf-8-sig").dropna(subset=["위도", "경도"])
    group_idx = df.groupby(["위도", "경도"]).cumcount()
    group_size = df.groupby(["위도", "경도"])["위도"].transform("size")

    out = []
    for (idx, row), i, n in zip(df.iterrows(), group_idx, group_size):
        lat, lon = float(row["위도"]), float(row["경도"])
        if n > 1:
            angle = 2 * math.pi * i / n
            lat += FARM_JITTER_RADIUS_DEG * math.sin(angle)
            lon += FARM_JITTER_RADIUS_DEG * math.cos(angle) / math.cos(math.radians(lat))
        out.append({
            # app/farm_order.py의 farm_id와 같은 값(둘 다 FARMS_PATH를 같은 방식으로
            # 읽고 dropna(위도,경도)만 거친 원본 행 인덱스라 서로 어긋나지 않는다) —
            # 지도에서 농장 점을 클릭했을 때 그 농장의 방역시설 체크리스트를 바로
            # 열 수 있게 한다(2026-08-26 피드백).
            "farm_id": int(idx),
            "farm_name": row["농장명"] if pd.notna(row["농장명"]) else None,
            "address": row["주소"],
            "sigun": row["시군"],
            "축종": row["축종"] if pd.notna(row["축종"]) else "돼지",
            "livestock_count": None if pd.isna(row["사육두수"]) else float(row["사육두수"]),
            "lat": lat,
            "lon": lon,
        })
    return out


@app.get("/outbreaks")
def outbreaks():
    """발생 지점 전체(82건, 표시 전용 — 10km 원용) — 등급 판정에는 쓰이지 않는다."""
    df = pd.read_csv(MASTER_GEOCODED_PATH, encoding="utf-8-sig")
    return [
        {
            "case_date": str(int(row["case_date"])),
            "address": row["address"],
            "lat": row["위도"],
            "lon": row["경도"],
        }
        for _, row in df.iterrows()
    ]


_COUNTY_BRIEFING_CACHE: dict[tuple[str, str], dict] = {}


def _build_nearest_case_basis(grade_info: dict) -> tuple[dict | None, dict | None]:
    """등급 판정에 쓰인 것과 같은 계산(app.grade)에서 그대로 뽑아온다 — 예전엔 시군
    중심점 기준으로 따로 계산해서 등급 근거와 농장 목록 거리가 안 맞을 수 있었는데,
    이제 grade()가 이미 폴리곤 경계 기준 최단거리를 계산해두므로 그걸 재사용한다.
    WARNING_RADIUS_KM(20km)보다 멀면 "근거로 보여줄 만큼 가깝지 않다"고 보고 숨긴다
    (평시 시군도 항상 "가장 가까운" 케이스는 있으므로, 컷오프 없이 그대로 노출하면
    수백 km 밖 사례가 "근거"처럼 보이는 오독이 생긴다).

    반환: (nc, nearest_case_basis) — nc는 note 없는 원본(브리핑/뉴스 프롬프트 입력용),
    nearest_case_basis는 note가 붙은 API 응답용. 둘 다 근거가 없으면 (None, None)."""
    if grade_info["nearest_distance_km"] is None or grade_info["nearest_distance_km"] > WARNING_RADIUS_KM:
        return None, None
    nc = {
        "case_date": grade_info["nearest_case"]["case_date"],
        "address": grade_info["nearest_case"]["address"],
        "distance_km": grade_info["nearest_distance_km"],
        "days_since": grade_info["days_since_last"],
    }
    nearest_case_basis = {
        **nc,
        "note": "이 거리는 시군 경계선까지의 거리입니다. 개별 농장은 경계선보다 안쪽에 있으니, 아래 농장 목록의 실제 거리는 이 값보다 조금 더 멀 수 있습니다.",
    }
    return nc, nearest_case_basis


@app.get("/sigun/{code}")
def sigun_detail(code: str, as_of: str | None = None, limit: int = DEFAULT_FARM_ORDER_LIMIT):
    _maybe_refresh()
    name = display_name(code)
    if name is None:
        raise HTTPException(status_code=404, detail=f"알 수 없는 시군구 코드: {code}")

    as_of = as_of or _default_as_of()
    # 시군 하나만 조회하는데 전국 브리핑(Node3)까지 매번 새로 만들 이유가 없다 —
    # 실측 결과 이게 /sigun/{code} 응답시간의 절반 가까이를 차지했다. grades-only
    # 그래프(node1+node2)만 돌려 등급 계산에 필요한 것만 얻는다.
    state = run_pipeline_grades_only(as_of)
    grade_info = state["grades"][code]

    nc, nearest_case_basis = _build_nearest_case_basis(grade_info)

    has_farms = code in farm_coverage_codes()
    farm_status = "ok" if has_farms else "no_farm_data"
    farms_list = farm_order(code, as_of, limit=limit) if has_farms else []

    # 등급이 as_of만의 순수 함수라, 같은 (code, as_of)는 항상 같은 브리핑 근거를 낸다 —
    # limit은 브리핑 문장에 안 들어가므로 캐시 키에서 뺀다.
    cache_key = (code, as_of)
    briefing = _COUNTY_BRIEFING_CACHE.get(cache_key)
    if briefing is None:
        briefing = generate_county_briefing(name, grade_info, nc)
        _COUNTY_BRIEFING_CACHE[cache_key] = briefing

    return {
        "code": code,
        "name": name,
        "as_of": as_of,
        "grade": grade_info,
        "nearest_case_basis": nearest_case_basis,
        "farm_status": farm_status,
        "farms": farms_list,
        "briefing": briefing,
    }


@app.get("/sigun/{code}/field_response")
def sigun_field_response(code: str, as_of: str | None = None):
    """시군 클릭 시 자동 생성되는 현장 대응 체크리스트(2026-08-26 2차 피드백) —
    정책 매뉴얼 RAG 검색 + 시군 단위 뉴스 검색을 종합한다(app/field_response.py).
    평시 시군은 조치할 게 없으므로 즉시 {"applicable": False}를 반환하고 LLM을
    아예 안 부른다. /sigun/{code}와 독립적으로 프론트에서 병렬 호출된다."""
    _maybe_refresh()
    name = display_name(code)
    if name is None:
        raise HTTPException(status_code=404, detail=f"알 수 없는 시군구 코드: {code}")

    as_of = as_of or _default_as_of()
    state = run_pipeline_grades_only(as_of)
    grade_info = state["grades"][code]
    nc, _ = _build_nearest_case_basis(grade_info)

    return build_field_response_cached(code, as_of, name, grade_info, nc)


class BiosecurityUpdate(BaseModel):
    checked_keys: list[str]


@app.get("/farms/{farm_id}/biosecurity")
def farm_biosecurity(farm_id: int):
    """농장별 방역시설 체크리스트 조회(2026-08-26 6차 피드백). farm_id는
    app/farm_order.py가 매기는 원본 CSV 행 인덱스 — 담당자가 현장에서 직접 확인한
    값을 저장·조회만 한다(app/biosecurity_checks.py 모듈독스트링 참고, AI가 상태를
    판정하지 않는다는 원칙을 여기서도 지킨다)."""
    return get_checklist(farm_id)


@app.put("/farms/{farm_id}/biosecurity")
def farm_biosecurity_update(farm_id: int, body: BiosecurityUpdate):
    """담당자가 화면에서 체크한 현재 상태 전체로 덮어쓴다(멱등적)."""
    return set_checklist(farm_id, body.checked_keys)
