"""ASF T3 — LangGraph 3노드: 문서 구조화 추출 -> 등급 판정(임시 함수) -> 브리핑 생성.

state 흐름: Node1이 만든 extracted_cases를 Node2가 그대로 받아 전국 시군마다
grade_stub.grade(sigun_code, as_of, extracted_cases)를 부른다(반경 로직이 있는 진짜
T2 함수로 바뀌어도 호출부는 그대로 — grade_stub.py 안쪽만 바뀌는 구조).
"""

from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from app.briefing import generate_briefing
from app.extraction import extract_cases
from app.geo_normalize import all_sgg_codes
from app.grade_stub import grade


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
    cases = state["extracted_cases"]

    codes = all_sgg_codes()
    grades = {code: grade(code, as_of, cases) for code in codes}

    return {
        "grades": grades,
        "grade_meta": {
            "is_stub": True,
            "note": next(iter(grades.values()))["note"] if grades else "",
            "county_count": len(codes),
        },
    }


def node3_brief(state: PipelineState) -> dict:
    briefing = generate_briefing(state["as_of"], state["grades"])
    return {"briefing": briefing}


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("extract", node1_extract)
    g.add_node("grade", node2_grade)
    g.add_node("brief", node3_brief)

    g.add_edge(START, "extract")
    g.add_edge("extract", "grade")
    g.add_edge("grade", "brief")
    g.add_edge("brief", END)

    return g.compile()


COMPILED_GRAPH = build_graph()
