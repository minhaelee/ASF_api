"""ASF v3 — 뉴스 기능. OpenAI Responses API 내장 web_search 툴을 쓴다 — 새 API 키/새
서비스 계정 불필요, 기존 OPENAI_API_KEY 그대로 재사용.

2026-08-26(2차) 피드백으로 용도가 바뀌었다: 처음엔 전국 risk_list 전체를 한 번에
요약하는 국가 단위 기능이었는데, "시군을 클릭하면 그 시군에 대한 뉴스가 자동으로
나와야 한다"는 정정에 따라 시군 1곳 단위로 좁혔다(app/field_response.py가 이 모듈과
app/policy_rag.py를 같이 호출해 시군별 현장 대응 체크리스트를 만든다).

이 모듈 자체는 등급을 계산하지 않는다 — grade()/build_risk_list()가 이미 계산한
grade_info를 입력으로만 받는다("판정/표시 계층 분리" 원칙, app/policy_rag.py와 동일).
"""

import sys

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_BRIEFING_MODEL

NEWS_DISCLAIMER = (
    "뉴스 검색은 실제 웹 검색 결과에 기반하며, 오래되었거나 소규모인 발생은 보도가 "
    "거의 없을 수 있습니다. 이 요약은 참고용이며 정식 발생현황 공고를 대체하지 않습니다."
)


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


def generate_county_news_briefing(name: str, grade_info: dict, nearest_case_basis: dict | None) -> dict:
    """시군 하나에 대한 뉴스 요약. 반환: {"text", "citations": [{"url","title"}],
    "disclaimer": NEWS_DISCLAIMER}"""
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    if nearest_case_basis is None:
        case_line = "최근 3주 내 시군 경계 20km 이내 발생 없음"
    else:
        case_line = (
            f"가장 가까운 최근 발생: {nearest_case_basis['address']} "
            f"({nearest_case_basis['distance_km']}km, {nearest_case_basis['days_since']}일 전)"
        )
    context = f"시군: {name}\n등급: {grade_info['grade']}\n{case_line}"

    instructions = (
        "너는 ASF(아프리카돼지열병) 방역 담당 공무원을 위해 특정 시군과 관련된 최근 뉴스를 "
        "자동으로 요약해 화면에 띄우는 시스템이다. 이 글은 사용자가 직접 입력한 질문에 "
        "대한 답변이 아니라 시군 클릭 시 자동 생성되는 상황 보고문이다 — '사용자께서 "
        "제시하신/요청하신', '말씀하신' 같은 표현이나 '제가 찾은/검색해본 결과' 같은 "
        "1인칭 표현을 절대 쓰지 말고, 객관적인 보고 문장으로만 서술하라(예: '~라는 보도가"
        "확인됩니다', '~에 대한 보도는 확인되지 않았습니다'). web_search로 실제로 찾은 "
        "내용만 근거로 삼아라 — 검색 결과에 없는 사실을 추정하거나 지어내지 마라. 각 항목은 "
        "반드시 실제 출처와 함께 제시하라. 오래되었거나 소규모인 발생은 언론 보도가 거의 "
        "없을 수 있다 — 그런 경우 관련 보도를 찾지 못했다고 명시하고 없는 뉴스를 지어내지 "
        "마라. 미래 시점으로 보이는 결과는 인용하지 마라. 정중한 존댓말(합니다체)로, 2~4문장의 "
        "간결한 한국어로, 마크다운 문법 없이 순수 텍스트로 작성하라."
    )

    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.responses.create(
        model=OPENAI_BRIEFING_MODEL,
        instructions=instructions,
        input=context,
        tools=[{"type": "web_search"}],
        include=["web_search_call.action.sources"],
    )

    return {
        "text": resp.output_text,
        "citations": _extract_citations(resp),
        "disclaimer": NEWS_DISCLAIMER,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    # 발생 마스터 CSV의 실제 케이스(78차=산청군 20260316)와 맞아떨어지는 날짜로 확인한다.
    grade_info = {"grade": "심각"}
    nearest_case_basis = {"address": "경남 산청군", "distance_km": 0.0, "days_since": 4}
    result = generate_county_news_briefing("경남 산청군", grade_info, nearest_case_basis)
    print(result["text"])
    print()
    print("citations:", result["citations"])
