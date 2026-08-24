"""ASF T3 — 파이프라인 진입점. FastAPI 엔드포인트는 여기 두 함수만 호출한다 — LangGraph
invoke가 코드베이스에서 이 두 곳에만 있다(각각 정확히 어떤 그래프를 도는지 명확하도록
분리했다. app/graph.py의 두 컴파일 그래프 참고).

run_pipeline: 전국 브리핑까지 포함(node1+node2+node3). /pipeline/run, /map이 쓴다.
run_pipeline_grades_only: 등급까지만(node1+node2, Node3 생략). /sigun/{code}가 쓴다 —
    시군 하나 조회하는데 안 쓰는 전국 브리핑을 매번 새로 생성하던 낭비를 없앴다
    (실측: /sigun/{code} 응답시간에서 절반 가까이가 이 불필요한 호출이었다).
"""

from app.graph import COMPILED_GRAPH, COMPILED_GRAPH_GRADES_ONLY, PipelineState


def run_pipeline(as_of: str) -> PipelineState:
    return COMPILED_GRAPH.invoke({"as_of": as_of})


def run_pipeline_grades_only(as_of: str) -> PipelineState:
    return COMPILED_GRAPH_GRADES_ONLY.invoke({"as_of": as_of})
