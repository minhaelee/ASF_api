"""ASF T3 — LangGraph 3노드: 문서 구조화 추출 -> 등급 판정 -> 브리핑 생성.

Node2는 이제(T2, v3) 진짜 grade(sigun_code, as_of)를 부른다 — 좌표는 grade.py가
발생 마스터 지오코딩 결과에서 직접 읽으므로 extracted_cases를 등급 계산에 넘기지
않는다. extracted_cases는 여전히 Node3 이전 단계 상태로 남아있지만(어떤 시군에 발생
이력이 있는지 등, mapping.py/main.py의 "농장 데이터 미확보" 판정에 쓰임), grade() 호출
자체는 이제 as_of와 sigun_code 2개만 받는다.

**속도 개선(2026-08-21 이월 건)**: 실측 결과 `/sigun/{code}`가 8초 가까이 걸렸는데,
원인은 시군 하나만 조회하는데도 매번 (1) 안 쓰는 전국 브리핑을 새로 생성하고 (2) 그 다음
시군 브리핑을 또 생성해 OpenAI를 두 번 부르는 구조였다. 두 가지로 고친다:
1. node1+node2만 도는 별도 컴파일 그래프(COMPILED_GRAPH_GRADES_ONLY)를 추가 —
   `/sigun/{code}`는 이걸 써서 Node3(전국 브리핑)를 아예 안 돈다. 노드 함수 자체는
   그대로 재사용하므로 등급/추출 로직이 두 곳에 흩어지지 않는다.
2. Node3(전국 브리핑)는 as_of가 같으면 결과가 같다(grade()가 순수 함수라 grades도
   as_of의 함수) — as_of 기준 인메모리 캐시를 추가해 같은 날짜를 반복 조회해도
   OpenAI를 다시 부르지 않는다.
"""

from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from app.briefing import generate_briefing
from app.extraction import extract_cases
from app.geo_normalize import all_sgg_codes
from app.grade import GRADE_METHOD_NOTE, grade


class PipelineState(TypedDict, total=False):
    as_of: str
    extracted_cases: list[dict]
    extraction_meta: dict
    grades: dict[str, dict]
    grade_meta: dict
    briefing: dict


def node1_extract(state: PipelineState) -> dict:
    cases, meta = extract_cases()
    return {"extracted_cases": cases, "extraction_meta": meta}


def node2_grade(state: PipelineState) -> dict:
    as_of = state["as_of"]

    codes = all_sgg_codes()
    grades = {code: grade(code, as_of) for code in codes}

    return {
        "grades": grades,
        "grade_meta": {
            "is_stub": False,
            "note": GRADE_METHOD_NOTE,
            "county_count": len(codes),
        },
    }


_NATIONAL_BRIEFING_CACHE: dict[str, dict] = {}


def node3_brief(state: PipelineState) -> dict:
    as_of = state["as_of"]
    cached = _NATIONAL_BRIEFING_CACHE.get(as_of)
    if cached is not None:
        return {"briefing": cached}

    briefing = generate_briefing(as_of, state["grades"])
    _NATIONAL_BRIEFING_CACHE[as_of] = briefing
    return {"briefing": briefing}


def build_graph(include_briefing: bool = True):
    g = StateGraph(PipelineState)
    g.add_node("extract", node1_extract)
    g.add_node("grade", node2_grade)
    g.add_edge(START, "extract")
    g.add_edge("extract", "grade")

    if include_briefing:
        g.add_node("brief", node3_brief)
        g.add_edge("grade", "brief")
        g.add_edge("brief", END)
    else:
        g.add_edge("grade", END)

    return g.compile()


COMPILED_GRAPH = build_graph(include_briefing=True)
COMPILED_GRAPH_GRADES_ONLY = build_graph(include_briefing=False)
