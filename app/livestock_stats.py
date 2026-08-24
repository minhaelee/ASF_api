"""ASF T2 v3 — 전국 시군별 일반돼지 사육규모 통계(작업지시서 2.6). **리플레이 분모 전용,
등급 계산에는 절대 넣지 않는다** (3장, 4.2 — 밀도를 등급 인자로도 쓰고 분모로도 쓰면
순환 논증이 된다).

원본은 cp949 인코딩, 광역시(부산/대구/인천/광주/대전/울산/세종)는 시도=시군으로 통합
표기돼 있다. 우리 발생 마스터의 강화군/북구/군위군/사하구/울주군은 각각 인천/대구/대구/
부산/울산으로 매핑해야 조인된다(작업지시서 2.6 표 그대로).

**시군구 코드로 조인한다 (이름 조인 아님)** — 처음 구현(2026-08-21)은 (시군명, 연도)로
바로 키를 만들었는데, 전국에 시군명이 겹치는 곳(고성군: 강원 32400 / 경남 38340,
`app/geo_normalize.py` docstring이 이미 실측 확인해 둔 목록)이 있어 하나가 다른 하나를
덮어쓰는 버그가 있었다(2026-08-24 실측으로 발견 — 고성군 2026년 값이 강원 12,900두인데
경남 83,130두로 조회됨). geo_normalize.resolve_sgg_code가 이미 이 충돌을 (시도,시군)으로
해소하므로, 통계 CSV의 각 행도 같은 함수로 코드를 구해 코드 기준으로 조회한다(등급/농장
로직 전체가 이미 코드를 유일 키로 쓰는 것과 동일한 원칙).

광역시 통합 행(시도=시군, 예: "인천","인천")은 실제 시군구 코드가 없는 집계 행이라
resolve_sgg_code로는 못 찾는다 — 이 7개(부산/대구/인천/광주/대전/울산/세종)만 이름
그대로 별도 테이블에 남겨두고, 흡수된 5개 시군(강화군 등)의 코드에서 그 이름으로
매핑해 찾는다.

조인 검증: 발생 시군 37개가 전부 통계와 "한 해라도" 연결되는지 확인 — 완전히 안 되는
시군이 남으면 경고 출력 후 중단한다(2.6 "분모가 비어 있는 시군을 조용히 건너뛰면
발생률이 왜곡된다").

**실측으로 발견한 별개 이슈 — 부분 결측 5건**: 김포시(2020,2021 없음), 파주시(2020,2021
없음), 연천군(2020 없음), 인제군(2022 없음), 양구군(2023~2026 없음). 이건 "조인 실패"가
아니라(그 시군 자체는 다른 연도엔 있음) 통계 원본 자체의 결측이다. 없는 값을 앞뒤 연도로
채우거나 추정하지 않는다(가상 데이터 금지, 원칙 2) — `livestock_count()`가 None을 돌려주면
호출부(리플레이 스크립트)가 그 시군-연도는 분모 계산에서 제외하고 결측 사실을 표에 함께
보고한다.
"""

import sys

import pandas as pd

from app.config import LIVESTOCK_STATS_PATH
from app.geo_normalize import all_sgg_codes, code_to_name, resolve_address, resolve_sgg_code

# 흡수된 시군 코드 -> 통계 CSV의 광역시 통합 행 이름. 통계 CSV 자체가 이 5개 시군을
# 광역시 하나로 묶어뒀으므로(작업지시서 2.6), 코드 기준 조회에서도 이 매핑이 필요하다.
_METRO_ABSORBED_CODE_TO_STATS_NAME = {
    resolve_sgg_code("인천광역시", "강화군"): "인천",
    resolve_sgg_code("대구광역시", "북구"): "대구",
    resolve_sgg_code("대구광역시", "군위군"): "대구",
    resolve_sgg_code("부산광역시", "사하구"): "부산",
    resolve_sgg_code("울산광역시", "울주군"): "울산",
}


def _load_lookups() -> tuple[dict[tuple[str, int], int], dict[tuple[str, int], int]]:
    """반환: (코드 기준 조회, 광역시 통합행 이름 기준 조회) 두 딕셔너리."""
    df = pd.read_csv(LIVESTOCK_STATS_PATH, encoding="cp949")
    by_code: dict[tuple[str, int], int] = {}
    by_metro_name: dict[tuple[str, int], int] = {}
    for _, row in df.iterrows():
        year = int(row["년도"])
        head = int(row["전체두수"])
        sido, sigun = row["시도"], row["시군"]
        if sido == sigun:  # 광역시 통합 행(예: 시도="인천", 시군="인천")
            by_metro_name[(sigun, year)] = head
            continue
        code = resolve_sgg_code(sido, sigun)
        if code is not None:
            by_code[(code, year)] = head
        # code가 None인 행(경계파일에 없는 표기 차이 등)은 무시 — verify_coverage가
        # 발생 시군 37개 전부에 대해 최종 조회 가능 여부를 별도로 검증한다.
    return by_code, by_metro_name


_LOOKUP_BY_CODE, _LOOKUP_BY_METRO_NAME = _load_lookups()


def livestock_count(sigun_code: str, year: int) -> int | None:
    """sigun_code: 시군구 코드(app.geo_normalize 기준, 예: 파주시 "31200").
    반환: 그 시군의 그 연도 전체두수. 통계에 없으면 None(추정치로 채우지 않는다)."""
    direct = _LOOKUP_BY_CODE.get((sigun_code, year))
    if direct is not None:
        return direct
    metro_name = _METRO_ABSORBED_CODE_TO_STATS_NAME.get(sigun_code)
    if metro_name is not None:
        return _LOOKUP_BY_METRO_NAME.get((metro_name, year))
    return None


def outbreak_sigun_codes() -> set[str]:
    """발생 마스터(asf_master_v1_geocoded.csv 아님, 원본 주소 문자열)의 37개 시군을
    코드로 반환. resolve_address를 써서 고성군류 충돌도 정확히 구분한다."""
    from app.master_loader import load_master_deduped

    df = load_master_deduped(verbose=False)
    codes = set()
    for addr in df["address"]:
        code = resolve_address(addr)
        if code is None:
            sys.exit(f"[livestock_stats] 발생 마스터 주소 코드 해석 실패: {addr!r}")
        codes.add(code)
    return codes


def verify_coverage(verbose: bool = True) -> None:
    """발생 시군 37개가 통계와 최소 한 해라도 연결되는지 확인. 완전 실패 시 sys.exit."""
    codes = outbreak_sigun_codes()

    fully_unresolved = []
    partial_gaps = {}
    years = range(2018, 2027)

    for code in sorted(codes):
        present = [y for y in years if livestock_count(code, y) is not None]
        name = code_to_name(code)
        if not present:
            fully_unresolved.append(name)
        else:
            missing = [y for y in years if y not in present]
            if missing:
                partial_gaps[name] = missing

    if fully_unresolved:
        sys.exit(
            f"[livestock_stats] 조인 실패 — 통계와 전혀 연결 안 되는 발생 시군: {fully_unresolved}. "
            "매핑 테이블(_METRO_ABSORBED_CODE_TO_STATS_NAME)을 확인할 것."
        )

    if verbose:
        print(f"[livestock_stats] 발생 시군 {len(codes)}개 전부 통계와 연결 확인(최소 1개 연도).")
        if partial_gaps:
            print(f"[livestock_stats] 부분 결측 {len(partial_gaps)}개 시군(추정치로 채우지 않음, 해당 연도는 분모 계산에서 제외):")
            for sigun, missing in partial_gaps.items():
                print(f"  - {sigun}: {missing}")


def never_farming_codes() -> list[str]:
    """어느 해에도 통계가 없는 시군구 코드(서울 자치구 등 원래 양돈이 없는 지역).
    replay_validate.py의 제외 사유 안내에 쓰인다."""
    return [
        code for code in all_sgg_codes()
        if all(livestock_count(code, y) is None for y in range(2018, 2027))
    ]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    verify_coverage()
    print()
    gangwon_gs = resolve_sgg_code("강원도", "고성군")
    gyeongnam_gs = resolve_sgg_code("경상남도", "고성군")
    print(f"고성군(강원, {gangwon_gs}) 2026:", livestock_count(gangwon_gs, 2026))
    print(f"고성군(경남, {gyeongnam_gs}) 2026:", livestock_count(gyeongnam_gs, 2026))
    paju = resolve_sgg_code("경기도", "파주시")
    print("파주시 2026:", livestock_count(paju, 2026))
    print("파주시 2020(결측 예상):", livestock_count(paju, 2020))
    ganghwa = resolve_sgg_code("인천광역시", "강화군")
    print("강화군(→인천 통합행) 2021:", livestock_count(ganghwa, 2021))
