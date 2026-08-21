"""ASF T3 v2 — FastAPI. 그래프/시군/농장 관련 로직은 전부 app/pipeline.py::run_pipeline()
경유 — LangGraph invoke가 코드베이스에 이 한 곳에만 있다는 것을 엔드포인트 레벨에서도
보장하기 위함. v2의 좌우 2단 대시보드(static/index.html)가 쓰는 /boundaries, /farms,
/outbreaks, /sigun/{code}가 이번에 추가됐다. 기존 /map(folium)은 대조용으로 당분간 유지.
"""

from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.briefing import generate_county_briefing
from app.config import BOUNDARY_PATH, MASTER_GEOCODED_PATH, FARMS_PATH
from app.constants import DEFAULT_FARM_ORDER_LIMIT, WARNING_RADIUS_KM
from app.farm_order import farm_order
from app.geo_normalize import code_to_name, farm_coverage_codes
from app.mapping import build_map
from app.pipeline import run_pipeline

app = FastAPI(title="ASF 점검 우선순위 도구 — T3 v2")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _default_as_of() -> str:
    return date.today().strftime("%Y%m%d")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """v2 좌우 2단 대시보드(static/index.html) — 이번 세션 신규 기본 화면.
    /map(folium)은 개발 중 대조용으로 당분간 유지."""
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/pipeline/run")
def pipeline_run(as_of: str | None = None):
    as_of = as_of or _default_as_of()
    state = run_pipeline(as_of)

    # 이름을 키로 쓰면 전국에 이름이 겹치는 7개 시군(고성군 등)이 서로 덮어써 유실된다 —
    # 코드가 유일한 키이므로 코드로 키를 두고 이름은 값 안에 넣는다.
    grades_out = {
        code: {
            "name": code_to_name(code),
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


@app.get("/farms")
def farms():
    """농장 점 전체(2,285건, 표시 전용) — 클라이언트 Leaflet이 직접 그린다."""
    df = pd.read_csv(FARMS_PATH, encoding="utf-8-sig").dropna(subset=["위도", "경도"])
    return [
        {
            "farm_name": row["농장명"] if pd.notna(row["농장명"]) else None,
            "address": row["주소"],
            "sigun": row["시군"],
            "livestock_count": None if pd.isna(row["사육두수"]) else float(row["사육두수"]),
            "lat": row["위도"],
            "lon": row["경도"],
        }
        for _, row in df.iterrows()
    ]


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


@app.get("/sigun/{code}")
def sigun_detail(code: str, as_of: str | None = None, limit: int = DEFAULT_FARM_ORDER_LIMIT):
    name = code_to_name(code)
    if name is None:
        raise HTTPException(status_code=404, detail=f"알 수 없는 시군구 코드: {code}")

    as_of = as_of or _default_as_of()
    state = run_pipeline(as_of)
    grade_info = state["grades"][code]

    # 등급 판정에 쓰인 것과 같은 계산(app.grade)에서 그대로 뽑아온다 — 예전엔 시군
    # 중심점 기준으로 따로 계산해서 등급 근거와 농장 목록 거리가 안 맞을 수 있었는데,
    # 이제 grade()가 이미 폴리곤 경계 기준 최단거리를 계산해두므로 그걸 재사용한다.
    # WARNING_RADIUS_KM(20km)보다 멀면 "근거로 보여줄 만큼 가깝지 않다"고 보고 숨긴다
    # (평시 시군도 항상 "가장 가까운" 케이스는 있으므로, 컷오프 없이 그대로 노출하면
    # 수백 km 밖 사례가 "근거"처럼 보이는 오독이 생긴다).
    nc = None
    nearest_case_basis = None
    if grade_info["nearest_distance_km"] is not None and grade_info["nearest_distance_km"] <= WARNING_RADIUS_KM:
        nc = {
            "case_date": grade_info["nearest_case"]["case_date"],
            "address": grade_info["nearest_case"]["address"],
            "distance_km": grade_info["nearest_distance_km"],
            "days_since": grade_info["days_since_last"],
        }
        nearest_case_basis = {
            **nc,
            "note": "시군 경계 기준 거리 — 개별 농장은 시군 안쪽에 있으므로 농장 목록의 거리는 이 값 이상이다",
        }

    has_farms = code in farm_coverage_codes()
    farm_status = "ok" if has_farms else "no_farm_data"
    farms_list = farm_order(code, as_of, limit=limit) if has_farms else []

    briefing = generate_county_briefing(name, grade_info, nc)

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
