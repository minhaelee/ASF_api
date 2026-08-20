"""ASF T3 — 전국 시군구 코드 정규화. 지도/등급 계산이 시군을 가리킬 때 쓰는 유일한 조인 키.

배경 (계획 수립 중 실측으로 확인, 최초 가정이었던 "legaldong 앞 5자리 = 경계파일 code"는 틀렸다):
    - 경계 GeoJSON(`data/boundaries/skorea-municipalities-2018-geo.json`, 통계청 SGIS,
      공공누리 제1유형)의 `code`는 법정동코드(행정안전부, 10자리, 경기=41)가 아니라
      SGIS 행정구역코드(경기=31, 강원=32 ...)다. 서로 다른 코드 체계라 legaldong으로는
      조인할 수 없다.
    - 시군명만으로는 전국 단위에서 충돌한다 — 실측 확인된 예: 중구(6), 강서구(2), 서구(5),
      동구(6), 남구(5), 북구(4), **고성군(2, 강원 32400 / 경남 38340)**.
      asf_master_v1.csv의 82건 안에는 고성군이 강원특별자치도 1곳만 나오지만, 지도는
      전국 ~250개 시군을 다루므로 이 모듈은 처음부터 시도+시군 조합으로 조인한다.

    시도 2자리 코드 표는 같은 저장소의 `skorea-provinces-2018-geo.json`(17개 시도)에서
    실측 추출한 값이다(하드코딩이지만 통계청 공공데이터 원문 확인 후 옮긴 것 — 가상 데이터 아님).
"""

import json
import sys

from app.config import BOUNDARY_PATH

# 2018년 시도명 -> SGIS 2자리 코드. skorea-provinces-2018-geo.json에서 실측 확인.
PROVINCE_CODE_2018 = {
    "서울특별시": "11",
    "부산광역시": "21",
    "대구광역시": "22",
    "인천광역시": "23",
    "광주광역시": "24",
    "대전광역시": "25",
    "울산광역시": "26",
    "세종특별자치시": "29",
    "경기도": "31",
    "강원도": "32",
    "충청북도": "33",
    "충청남도": "34",
    "전라북도": "35",
    "전라남도": "36",
    "경상북도": "37",
    "경상남도": "38",
    "제주특별자치도": "39",
}

# 2018년 이후 개칭된 시도명 -> 위 표의 2018년 명칭. (강원 2023-06-11, 전북 2024-01-18 개칭)
# 시군구 경계 자체는 개칭과 무관하므로, 새 이름이 들어와도 옛 이름으로 되돌려 코드를 찾는다.
# asf_master_v1.csv에 충남/경북/경기/강원 같은 축약 표기가 실제로 섞여 있어(실측 확인),
# 축약형도 같은 표로 흡수한다.
PROVINCE_RENAME_TO_2018 = {
    "강원특별자치도": "강원도",
    "전북특별자치도": "전라북도",
    "서울": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "광주": "광주광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전라북도",
    "전남": "전라남도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
    # farms_geocoded.csv 원본에 있는 오타(실측 확인, T1 산출물 그대로 옮겨져 있음).
    "경상냠도": "경상남도",
}

# 2018년 이후 시군 자체가 다른 시도로 편입된 경우. 경계파일은 2018년 기준이라
# 옛 소속(시도)으로 남아있으므로, 현재 주소의 시도로는 못 찾고 옛 시도로 찾아야 한다.
# 군위군: 2023-07-01 경상북도 -> 대구광역시 편입.
SIGUN_PROVINCE_OVERRIDE = {
    ("대구광역시", "군위군"): "경상북도",
}


def _load_boundary_features() -> list[dict]:
    with open(BOUNDARY_PATH, encoding="utf-8") as f:
        gj = json.load(f)
    return gj["features"]


_FEATURES = _load_boundary_features()
_BY_SIDO_CODE_AND_NAME: dict[tuple[str, str], str] = {}
_CODE_TO_NAME: dict[str, str] = {}
for _f in _FEATURES:
    _p = _f["properties"]
    _code = _p["code"]
    _name = _p["name"]
    _BY_SIDO_CODE_AND_NAME[(_code[:2], _name)] = _code
    _CODE_TO_NAME[_code] = _name


def resolve_sgg_code(sido_raw: str, sigun_raw: str) -> str | None:
    """(시도, 시군) 문자열을 경계파일의 5자리 SGIS 코드로 변환. 못 찾으면 None."""
    sido = sido_raw.strip()
    sido = PROVINCE_RENAME_TO_2018.get(sido, sido)
    sigun = sigun_raw.strip()

    override_sido = SIGUN_PROVINCE_OVERRIDE.get((sido, sigun))
    if override_sido is not None:
        sido = override_sido

    prov_code = PROVINCE_CODE_2018.get(sido)
    if prov_code is None:
        return None
    return _BY_SIDO_CODE_AND_NAME.get((prov_code, sigun))


_SIGUN_NAME_TO_CODES: dict[str, list[str]] = {}
for _code, _name in _CODE_TO_NAME.items():
    _SIGUN_NAME_TO_CODES.setdefault(_name, []).append(_code)


def resolve_sigun_loose(sigun_raw: str) -> str | None:
    """시도 정보 없이 시군명만으로 찾는다. 표시 전용 용도로만 쓸 것.

    전국에 이름이 겹치는 시군(고성군 등 7개)은 시도를 모르면 원리적으로 특정할 수
    없으므로 여기서는 None을 돌려준다 — 임의로 하나를 골라 지도에 잘못 찍는 것보다,
    "매칭 실패"로 명시해 호출부가 처리하게 한다.
    """
    codes = _SIGUN_NAME_TO_CODES.get(sigun_raw.strip())
    if codes and len(codes) == 1:
        return codes[0]
    return None


def resolve_address(address: str) -> str | None:
    """전체 주소 문자열 -> 시군구 코드. 여러 전략을 순서대로 시도한다.

    1. (시도, 시군) 2토큰 직결 조인
    2. 고양시/용인시/창원시 등 구가 있는 대도시 — 경계파일 name은 "고양시일산서구"처럼
       공백 없이 붙어 있어, 3번째 토큰이 "구"로 끝나면 2+3번째 토큰을 붙여 재시도
    3. 시도 토큰이 없거나 못 찾은 경우 — 1번째 토큰을 시군명으로 보고 전국에서
       유일하게 매칭되면 사용 (표시 전용 데이터인 farms_geocoded.csv의 "합천군 초계면 택리"류
       — 시도 없이 시작하는 행 — 를 위한 구제 경로)
    """
    sido, sigun, rest = parse_address_prefix(address)

    code = resolve_sgg_code(sido, sigun)
    if code is not None:
        return code

    rest_tokens = rest.split(maxsplit=1)
    if rest_tokens and rest_tokens[0].endswith("구"):
        merged = sigun + rest_tokens[0]
        code = resolve_sgg_code(sido, merged)
        if code is not None:
            return code

    return resolve_sigun_loose(sido)


def all_sgg_codes() -> list[str]:
    """전국 시군구 코드 전체(~250개). Node2가 등급을 매길 대상 목록."""
    return list(_CODE_TO_NAME.keys())


def code_to_name(code: str) -> str | None:
    return _CODE_TO_NAME.get(code)


def parse_address_prefix(address: str) -> tuple[str, str, str]:
    """"경기도 파주시 연다산동" -> ("경기도", "파주시", "연다산동").

    한국 주소 표기는 항상 시도가 1번째, 시군구가 2번째 토큰이라는 규칙에 의존하는
    단순 분리자다. LLM 없이도 쓸 수 있어 farms_geocoded.csv의 주소 컬럼(시도 정보가
    없는 시군 컬럼을 보완하는 용도) 처리와, Node1 LLM 출력 검증용 대조 양쪽에 쓰인다.
    """
    parts = address.strip().split(maxsplit=2)
    if len(parts) < 2:
        return address.strip(), "", ""
    sido, sigun = parts[0], parts[1]
    rest = parts[2] if len(parts) > 2 else ""
    return sido, sigun, rest


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"전국 시군구 {len(all_sgg_codes())}개 로드")
    print("고성군 충돌 검증:", resolve_sgg_code("강원특별자치도", "고성군"), resolve_sgg_code("경상남도", "고성군"))
    print("파주시:", resolve_sgg_code("경기도", "파주시"))
