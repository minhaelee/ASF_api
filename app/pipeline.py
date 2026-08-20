"""ASF T3 — 파이프라인 단일 진입점. FastAPI의 두 엔드포인트(/pipeline/run, /map)가
이 함수 하나만 호출한다 — LangGraph invoke가 코드베이스에 이 한 곳에만 있다.
"""

from app.graph import COMPILED_GRAPH, PipelineState


def run_pipeline(as_of: str) -> PipelineState:
    return COMPILED_GRAPH.invoke({"as_of": as_of})
