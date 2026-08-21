"""ASF T3 — Node3: 등급 판정 결과로 주간 브리핑 문장 생성.

작업지시서 원칙 3: LLM은 등급 판정에 절대 관여하지 않는다. 이 모듈은 Node2가 이미 계산한
grades를 문장으로 요약할 뿐, 등급 자체를 다시 계산하거나 뒤집지 않는다.

등급 판정 방식 설명(GRADE_METHOD_NOTE)은 LLM 문장에 맡기지 않는다 — briefing() 반환값의
disclaimer는 별도 필드라서, LLM이 문장을 다듬다가 빠뜨려도 API/지도 응답에는 항상 남는다.
"""

import sys

from openai import OpenAI

from app.config import OPENAI_API_KEY, OPENAI_BRIEFING_MODEL
from app.grade import GRADE_METHOD_NOTE
from app.geo_normalize import code_to_name


def _summarize_grades(grades: dict[str, dict]) -> str:
    by_grade = {"심각": [], "주의": [], "평시": []}
    for code, g in grades.items():
        by_grade[g["grade"]].append(code_to_name(code) or code)

    lines = [f"{g}: {len(names)}개 시군 ({', '.join(names) if names else '-'})" for g, names in by_grade.items()]
    return "\n".join(lines)


def generate_briefing(as_of: str, grades: dict[str, dict]) -> dict:
    """반환: {"text": str, "is_stub_pipeline": False, "disclaimer": GRADE_METHOD_NOTE}"""
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    summary = _summarize_grades(grades)
    n_sim = sum(1 for g in grades.values() if g["grade"] == "심각")
    n_juju = sum(1 for g in grades.values() if g["grade"] == "주의")

    client = OpenAI(api_key=OPENAI_API_KEY)
    instructions = (
        "너는 ASF(아프리카돼지열병) 방역 담당 공무원을 위한 주간 브리핑 문장을 쓴다. "
        "아래 등급 집계 결과만 근거로 3~5문장의 한국어 브리핑을 작성하라. "
        "등급을 다시 판단하거나 새로운 수치를 추정하지 말고, 주어진 집계만 요약·설명하라. "
        "심각/주의 등급 시군이 있으면 우선 점검 대상으로 언급하라."
    )
    input_text = f"기준일(as_of): {as_of}\n\n등급 집계:\n{summary}"

    resp = client.responses.create(
        model=OPENAI_BRIEFING_MODEL,
        instructions=instructions,
        input=input_text,
    )

    return {
        "text": resp.output_text,
        "as_of": as_of,
        "counts": {"심각": n_sim, "주의": n_juju},
        "is_stub_pipeline": False,
        "disclaimer": GRADE_METHOD_NOTE,
    }


def generate_county_briefing(sigun_name: str, grade_info: dict, nearest_case_info: dict | None) -> dict:
    """시군 상세 패널 ①(선택 상태)용 1~3문장 브리핑. 반환 모양은 generate_briefing과 동일
    ({"text", "disclaimer"})."""
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    # nearest_case_info는 호출부(app/main.py)가 WARNING_RADIUS_KM(20km) 안일 때만 넘긴다.
    # None이면 "가까운 발생 없음"이라는 뜻이므로, grade_info['days_since_last'](수백 km
    # 밖 케이스의 경과일일 수 있음)를 여기서 같이 넘기면 "근거는 없다면서 경과일은 있다"는
    # 모순된 입력이 돼 LLM이 혼란스러운 문장을 쓴다 — 실측으로 확인된 문제라, 경과일도
    # nearest_case_info가 있을 때만 프롬프트에 넣는다.
    if nearest_case_info is None:
        nearest_line = "최근 3주 내 시군 경계 20km 이내 발생 없음"
    else:
        nearest_line = (
            f"가장 가까운 최근 발생: {nearest_case_info['address']} "
            f"({nearest_case_info['distance_km']}km, {nearest_case_info['days_since']}일 전)"
        )

    client = OpenAI(api_key=OPENAI_API_KEY)
    instructions = (
        "너는 ASF(아프리카돼지열병) 방역 담당 공무원을 위한 시군 단위 브리핑 문장을 쓴다. "
        "주어진 정보만 문장으로 서술할 것. 목록에 없는 시군을 언급하거나 순서를 바꾸지 말 것. "
        "1~3문장의 한국어로 작성하라."
    )
    input_text = f"시군: {sigun_name}\n등급: {grade_info['grade']}\n{nearest_line}"

    resp = client.responses.create(
        model=OPENAI_BRIEFING_MODEL,
        instructions=instructions,
        input=input_text,
    )

    return {"text": resp.output_text, "disclaimer": GRADE_METHOD_NOTE}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from app.geo_normalize import all_sgg_codes
    from app.grade import grade

    as_of = "20260815"
    grades = {code: grade(code, as_of) for code in all_sgg_codes()}
    result = generate_briefing(as_of, grades)
    print(result["text"])
    print()
    print("disclaimer:", result["disclaimer"])
