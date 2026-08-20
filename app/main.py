"""ASF T3 — FastAPI. 입력은 as_of 하나뿐이라 GET+쿼리파라미터로 받는다.

두 엔드포인트 모두 app/pipeline.py::run_pipeline() 하나만 호출한다 — LangGraph invoke가
코드베이스에 이 한 곳에만 있다는 것을 엔드포인트 레벨에서도 보장하기 위함.
"""

from datetime import date

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.geo_normalize import code_to_name
from app.mapping import build_map
from app.pipeline import run_pipeline

app = FastAPI(title="ASF 점검 우선순위 도구 — T3 뼈대")


def _default_as_of() -> str:
    return date.today().strftime("%Y%m%d")


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
        }
        for code, g in state["grades"].items()
    }

    return {
        "as_of": as_of,
        "grades": grades_out,
        "extraction": state["extraction_meta"],
        "grade_meta": state["grade_meta"],
        "briefing": state["briefing"],
        "meta": {
            "pipeline_is_stub": True,
            "disclaimer": state["grade_meta"]["note"],
        },
    }


@app.get("/map", response_class=HTMLResponse)
def map_view(as_of: str | None = None):
    as_of = as_of or _default_as_of()
    state = run_pipeline(as_of)
    m = build_map(state)
    return m.get_root().render()
