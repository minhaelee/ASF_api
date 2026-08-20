"""ASF T3 — Node1: 발생 마스터 주소를 LLM 구조화 추출로 {시도,시군,읍면동,리}로 분해.

작업지시서 6장 T3: "노드1 문서 구조화 추출". LLM은 여기서 주소 문자열을 구조화된
필드로 바꾸는 역할만 한다 — case_date/infected 같은 사실 필드는 LLM에 보내지 않고
파이썬에서 원본 행과 위치로 재부착한다(숫자·날짜를 LLM이 건드릴 여지를 원천 차단).

LLM은 좌표를 만들지 않는다. 좌표는 scripts/geocode_outbreaks.py(카카오)에서만 나온다 —
주소 파싱과 좌표 생성을 같은 호출에 섞으면 환각 위험이 생긴다.

캐시: 82개 주소 목록의 해시가 같으면 OpenAI를 다시 부르지 않는다(.cache/, gitignore
대상 — 재생성 가능한 파생물이지 검증된 데이터가 아니다). 해시가 다르면(마스터 데이터가
바뀌면) 자동 무효화된다.

Node1 출력의 (시도,시군)이 app/geo_normalize.py로 못 찾는 경우는 조용히 버리지 않고
extraction_meta["unresolved"]에 남겨 콘솔/응답에 노출한다.
"""

import hashlib
import json
import os
import sys

from openai import OpenAI
from pydantic import BaseModel

from app.config import EXTRACTION_CACHE_PATH, OPENAI_API_KEY, OPENAI_EXTRACTION_MODEL
from app.geo_normalize import resolve_sgg_code
from app.master_loader import load_master_deduped

IS_STUB = False  # Node1 자체는 스텁이 아니다 — 실제로 LLM을 호출하는 최종 로직


class _ExtractedAddress(BaseModel):
    raw_address: str
    sido: str
    sigun: str
    eupmyeondong: str
    ri: str = ""


class _ExtractionResult(BaseModel):
    cases: list[_ExtractedAddress]


def _address_list_hash(addresses: list[str]) -> str:
    joined = "\n".join(addresses)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _load_cache(expect_hash: str) -> list[dict] | None:
    if not os.path.exists(EXTRACTION_CACHE_PATH):
        return None
    try:
        with open(EXTRACTION_CACHE_PATH, encoding="utf-8") as f:
            cached = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if cached.get("hash") != expect_hash:
        return None
    return cached.get("extracted")


def _save_cache(hash_: str, extracted: list[dict]) -> None:
    os.makedirs(os.path.dirname(EXTRACTION_CACHE_PATH), exist_ok=True)
    with open(EXTRACTION_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"hash": hash_, "extracted": extracted}, f, ensure_ascii=False, indent=2)


def _call_openai(addresses: list[str]) -> list[dict]:
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    numbered = "\n".join(f"{i+1}. {a}" for i, a in enumerate(addresses))
    instructions = (
        "다음은 한국 행정구역 주소 목록이다. 각 주소를 시도/시군구/읍면동/리로 분해하라.\n"
        "- raw_address는 입력 주소 문자열을 토씨 하나 틀리지 않고 그대로 돌려줄 것.\n"
        "- 입력 개수와 순서를 그대로 유지해 cases 배열을 채울 것(누락·병합·재정렬 금지).\n"
        "- 시도는 정식명칭으로 정규화하지 말고 입력 표기를 그대로 유지할 것"
        "(예: '경기도'는 '경기도'로, '충남'은 '충남'으로).\n"
        "- 리가 주소에 없으면 빈 문자열로 둘 것."
    )

    resp = client.responses.parse(
        model=OPENAI_EXTRACTION_MODEL,
        instructions=instructions,
        input=numbered,
        text_format=_ExtractionResult,
    )
    parsed: _ExtractionResult = resp.output_parsed
    return [c.model_dump() for c in parsed.cases]


def extract_cases() -> tuple[list[dict], dict]:
    """반환: (extracted_cases, extraction_meta).

    extracted_cases 각 항목: case_date, address, infected, source, legaldong(원본) +
    sido, sigun, eupmyeondong, ri, sgg_code(LLM+geo_normalize 결과).
    """
    df = load_master_deduped(verbose=True)
    addresses = df["address"].tolist()
    hash_ = _address_list_hash(addresses)

    cached = _load_cache(hash_)
    if cached is not None:
        parsed_by_addr = {c["raw_address"]: c for c in cached}
        source = "cache"
        print(f"[extraction] 캐시 사용 ({EXTRACTION_CACHE_PATH}, 해시 일치)")
    else:
        print(f"[extraction] OpenAI 구조화 추출 호출 ({OPENAI_EXTRACTION_MODEL}, {len(addresses)}건 배치 1회)")
        extracted = _call_openai(addresses)

        if len(extracted) != len(addresses):
            sys.exit(
                f"[extraction] 치명적 불일치: 입력 {len(addresses)}건, LLM 출력 {len(extracted)}건. "
                "Node2가 정렬을 신뢰할 수 없어 중단한다."
            )

        parsed_by_addr = {c["raw_address"]: c for c in extracted}
        missing = [a for a in addresses if a not in parsed_by_addr]
        if missing:
            sys.exit(f"[extraction] 치명적 불일치: LLM이 원본 주소를 그대로 돌려주지 않음: {missing[:3]} ...")

        _save_cache(hash_, extracted)
        source = "llm"

    unresolved = []
    cases = []
    for _, row in df.iterrows():
        parsed = parsed_by_addr[row["address"]]
        sgg_code = resolve_sgg_code(parsed["sido"], parsed["sigun"])
        if sgg_code is None:
            unresolved.append({"address": row["address"], "sido": parsed["sido"], "sigun": parsed["sigun"]})

        cases.append({
            "case_date": row["case_date"],
            "address": row["address"],
            "infected": row["infected"],
            "source": row["source"],
            "legaldong": row["legaldong"],
            "sido": parsed["sido"],
            "sigun": parsed["sigun"],
            "eupmyeondong": parsed["eupmyeondong"],
            "ri": parsed["ri"],
            "sgg_code": sgg_code,
        })

    meta = {
        "is_stub": IS_STUB,
        "source": source,
        "model": OPENAI_EXTRACTION_MODEL,
        "count": len(cases),
        "unresolved": unresolved,
    }

    if unresolved:
        print(f"[extraction] 시군 매칭 실패 {len(unresolved)}건 (등급 계산에서 제외됨):")
        for u in unresolved:
            print(f"  - {u['address']} -> sido={u['sido']!r} sigun={u['sigun']!r}")

    return cases, meta


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cases, meta = extract_cases()
    print()
    print(f"추출 {meta['count']}건, source={meta['source']}, unresolved={len(meta['unresolved'])}")
    print(cases[0])
