"""ASF v3 — 시군 클릭 시 자동 생성되는 현장 대응 체크리스트(2026-08-26 2차 피드백).

app/policy_rag.py(정책 매뉴얼 RAG 검색)와 app/news.py(시군 단위 뉴스 검색)를 조합해,
"이 시군 상황에서 현장 담당자가 뭘 확인·조치해야 하는가"를 한 번에 만들어낸다. 사용자가
질문을 입력하는 Q&A가 아니라 시군 등급(심각/주의)에 대응하는 고정 질의로 RAG 검색을
돌리고, 그 결과를 이 시군 컨텍스트에 맞춰 우선순위 체크리스트로 합성한다.

평시 시군은 조치할 게 없으므로 LLM/DB 호출 자체를 안 한다(app/news.py가 risk_list가
비면 web_search를 안 부르던 것과 동일한 이유 — 비용/레이턴시 절감, 대부분의 클릭이
평시 시군에서 일어남).

정책 체크리스트와 뉴스 요약은 서로 독립적인 검색이라 ThreadPoolExecutor로 동시에
실행한다 — 직렬로 하면 임베딩+DB 검색+LLM 호출(체크리스트) 그리고 web_search+LLM
호출(뉴스)이 합쳐져 20~30초까지 걸릴 수 있는데, 병렬화하면 더 느린 쪽 하나의 시간으로
줄어든다. 둘 중 하나가 실패해도(네트워크 오류 등) 다른 하나는 그대로 반환한다 —
app/main.py 기존 주석의 "API 실패해도 서비스는 정상 동작"(4.7) 원칙과 동일한 기조로,
이 기능 전체를 500으로 죽이지 않는다.
"""

import sys
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

from app.config import FIELD_RESPONSE_DISCLAIMER, OPENAI_API_KEY, OPENAI_BRIEFING_MODEL
from app.news import generate_county_news_briefing
from app.policy_rag import retrieve_chunks

# 등급별 고정 검색 질의(LLM 미사용, 순수 텍스트 상수) — 심각/주의는 방역실시요령·SOP에
# 항상 대응 절차가 있으므로, Q&A 때 쓰던 "질문이 문서 범위 밖인가" 거리 임계값 판정이
# 필요 없다.
POLICY_QUERY_BY_GRADE = {
    "심각": "10km 방역대 내 살처분 대상 농장 현장 조치, 이동제한, 통제초소 운영, 소독, 역학조사 절차",
    "주의": "예찰지역·보호지역 예찰 강화, 이동제한, 임상검사 절차",
}

POLICY_TOP_K = 8

_FIELD_RESPONSE_CACHE: dict[tuple[str, str], dict] = {}


def _generate_checklist(client: OpenAI, name: str, grade_info: dict, nearest_case_basis: dict | None) -> dict:
    """반환: {"checklist_text", "checklist_sources"}"""
    query = POLICY_QUERY_BY_GRADE[grade_info["grade"]]
    chunks = retrieve_chunks(client, query, top_k=POLICY_TOP_K)

    context = "\n\n---\n\n".join(
        f"[출처: {c['source_file']}"
        f"{' ' + c['article_no'] if c['article_no'] else ''} {c['title']}]\n{c['content']}"
        for c in chunks
    )
    if nearest_case_basis is None:
        case_line = "최근 3주 내 시군 경계 20km 이내 발생 없음"
    else:
        case_line = (
            f"가장 가까운 최근 발생: {nearest_case_basis['address']} "
            f"({nearest_case_basis['distance_km']}km, {nearest_case_basis['days_since']}일 전)"
        )

    instructions = (
        "너는 ASF(아프리카돼지열병) 방역 담당 공무원에게 이 시군에서 지금 확인·조치해야 "
        "할 사항을 제시하는 도우미다. 아래 제공된 방역실시요령/SOP 조문·섹션 내용만 근거로 "
        "삼아라 — 여기 없는 내용을 추정하거나 지어내지 마라. 이 시군의 등급과 최근 발생 "
        "상황에 맞춰 우선순위가 높은 조치부터 순서대로 작성하라. 출력은 반드시 한 줄에 "
        "조치 하나씩, 각 줄은 '- '로 시작하고 문장 끝에 괄호로 근거를 표시하는 형식만 "
        "지켜라. 예: '- 통제초소를 설치하고 출입 차량을 소독하십시오. (근거: SOP 통제초소 "
        "운영)'. 5~8개 항목으로 작성하고, 그 외 다른 형식(번호, 굵게 등)은 쓰지 마라."
    )
    input_text = f"시군: {name}\n등급: {grade_info['grade']}\n{case_line}\n\n검색된 조문/섹션:\n{context}"

    resp = client.responses.create(
        model=OPENAI_BRIEFING_MODEL,
        instructions=instructions,
        input=input_text,
    )

    sources = []
    seen = set()
    for c in chunks:
        key = (c["source_file"], c["article_no"], c["title"])
        if key not in seen:
            seen.add(key)
            sources.append({"source_file": c["source_file"], "article_no": c["article_no"], "title": c["title"]})

    return {"checklist_text": resp.output_text, "checklist_sources": sources}


def _generate_news(name: str, grade_info: dict, nearest_case_basis: dict | None) -> dict:
    """반환: {"news_text", "news_citations"}"""
    result = generate_county_news_briefing(name, grade_info, nearest_case_basis)
    return {"news_text": result["text"], "news_citations": result["citations"]}


def build_field_response(name: str, grade_info: dict, nearest_case_basis: dict | None) -> dict:
    if grade_info["grade"] == "평시":
        return {"applicable": False}

    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    result = {
        "applicable": True,
        "checklist_text": "",
        "checklist_sources": [],
        "checklist_available": False,
        "news_text": "",
        "news_citations": [],
        "news_available": False,
        "disclaimer": FIELD_RESPONSE_DISCLAIMER,
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        checklist_future = pool.submit(_generate_checklist, client, name, grade_info, nearest_case_basis)
        news_future = pool.submit(_generate_news, name, grade_info, nearest_case_basis)

        try:
            result.update(checklist_future.result())
            result["checklist_available"] = True
        except Exception as e:
            result["checklist_text"] = "체크리스트를 지금 불러오지 못했습니다."
            print(f"[field_response] checklist 생성 실패: {e}", file=sys.stderr)

        try:
            result.update(news_future.result())
            result["news_available"] = True
        except Exception as e:
            result["news_text"] = "뉴스를 지금 불러오지 못했습니다."
            print(f"[field_response] news 생성 실패: {e}", file=sys.stderr)

    return result


def build_field_response_cached(code: str, as_of: str, name: str, grade_info: dict, nearest_case_basis: dict | None) -> dict:
    cache_key = (code, as_of)
    cached = _FIELD_RESPONSE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result = build_field_response(name, grade_info, nearest_case_basis)
    _FIELD_RESPONSE_CACHE[cache_key] = result
    return result


if __name__ == "__main__":
    import time

    sys.stdout.reconfigure(encoding="utf-8")

    grade_info = {"grade": "심각"}
    nearest_case_basis = {"address": "경남 산청군", "distance_km": 0.0, "days_since": 4}

    t0 = time.time()
    result = build_field_response("경남 산청군", grade_info, nearest_case_basis)
    elapsed = time.time() - t0

    print(f"elapsed: {elapsed:.1f}s")
    print(f"checklist_available={result['checklist_available']}")
    print(result["checklist_text"])
    print("sources:", result["checklist_sources"])
    print()
    print(f"news_available={result['news_available']}")
    print(result["news_text"])
    print("citations:", result["news_citations"])
