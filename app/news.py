"""ASF v3 — 뉴스 기능(2026-08-26 피드백). OpenAI Responses API 내장 web_search 툴을
쓴다 — 새 API 키/새 서비스 계정 불필요, 기존 OPENAI_API_KEY 그대로 재사용.

전국 단위만 지원한다(시군별 개별 뉴스는 범위 밖 — app/policy_rag.py처럼 이 프로젝트
전체가 "판정/표시 계층 분리" 원칙을 지키므로, 이 모듈도 grade()/build_risk_list()가
이미 계산한 risk_list를 입력으로만 받을 뿐 등급을 다시 계산하지 않는다.

risk_list가 비어 있으면(전국 평시) OpenAI를 아예 호출하지 않는다 — web_search 호출은
이 프로젝트에서 가장 느리고(수 초~십수 초) 비용이 드는 호출이라, 검색할 위험 지역
자체가 없을 때 부르는 건 낭비다.
"""

import sys

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_BRIEFING_MODEL

NEWS_DISCLAIMER = (
    "뉴스 검색은 실제 웹 검색 결과에 기반하며, 오래되었거나 소규모인 발생은 보도가 "
    "거의 없을 수 있습니다. 이 요약은 참고용이며 정식 발생현황 공고를 대체하지 않습니다."
)

NO_RISK_TEXT = "현재 심각·주의 등급 시군이 없어 검색할 위험 지역이 없습니다."

_NEWS_CACHE: dict[str, dict] = {}


def build_news_query_context(as_of: str, risk_list: list[dict]) -> str:
    """순수 함수, LLM 미사용 — risk_list 상위 항목으로 검색 프롬프트용 텍스트를 만든다."""
    lines = [f"기준일(as_of): {as_of}", "", "현재 심각/주의 등급 시군:"]
    for r in risk_list:
        lines.append(
            f"- {r['name']} ({r['grade']}, 최근 발생 {r['recent_case_count']}건, "
            f"발생지에서 {r['nearest_distance_km']}km, {r['days_since_last']}일 전)"
        )
    return "\n".join(lines)


def _extract_citations(response) -> list[dict]:
    citations = []
    seen_urls = set()
    for item in response.output:
        if getattr(item, "type", None) != "message":
            continue
        for content in item.content:
            for annotation in getattr(content, "annotations", []) or []:
                url = getattr(annotation, "url", None)
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    citations.append({"url": url, "title": getattr(annotation, "title", None) or url})
    return citations


def generate_news_briefing(as_of: str, risk_list: list[dict]) -> dict:
    """반환: {"as_of", "text", "citations": [{"url","title"}],
              "has_risk_counties": bool, "disclaimer": NEWS_DISCLAIMER}"""
    if not risk_list:
        return {
            "as_of": as_of,
            "text": NO_RISK_TEXT,
            "citations": [],
            "has_risk_counties": False,
            "disclaimer": NEWS_DISCLAIMER,
        }

    cached = _NEWS_CACHE.get(as_of)
    if cached is not None:
        return cached

    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    client = OpenAI(api_key=OPENAI_API_KEY)
    context = build_news_query_context(as_of, risk_list)

    instructions = (
        "너는 ASF(아프리카돼지열병) 방역 담당 공무원을 위해 최근 관련 뉴스를 요약한다. "
        "web_search로 실제로 찾은 내용만 근거로 삼아라 — 검색 결과에 없는 사실을 추정하거나 "
        "지어내지 마라. 각 항목은 반드시 실제 출처와 함께 제시하라. 오래되었거나 소규모인 "
        "발생은 언론 보도가 거의 없을 수 있다 — 그런 경우 관련 보도를 찾지 못했다고 명시하고 "
        "없는 뉴스를 지어내지 마라. 기준일(as_of) 이후에 나온 것으로 보이는(미래 시점) 결과는 "
        "인용하지 마라. 3~5문장의 간결한 한국어로, 마크다운 문법 없이 순수 텍스트로 작성하라."
    )

    resp = client.responses.create(
        model=OPENAI_BRIEFING_MODEL,
        instructions=instructions,
        input=context,
        tools=[{"type": "web_search"}],
        include=["web_search_call.action.sources"],
    )

    result = {
        "as_of": as_of,
        "text": resp.output_text,
        "citations": _extract_citations(resp),
        "has_risk_counties": True,
        "disclaimer": NEWS_DISCLAIMER,
    }
    _NEWS_CACHE[as_of] = result
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from app.grade import grade
    from app.geo_normalize import all_sgg_codes
    from app.briefing import build_risk_list

    as_of = "20260320"
    grades = {code: grade(code, as_of) for code in all_sgg_codes()}
    risk_list = build_risk_list(as_of, grades)
    print(f"risk_list count: {len(risk_list)}")
    result = generate_news_briefing(as_of, risk_list)
    print(result["text"])
    print()
    print("citations:", result["citations"])
