"""ASF T2 v3 — 전국 시군별 일반돼지 사육규모 통계(작업지시서 2.6). **리플레이 분모 전용,
등급 계산에는 절대 넣지 않는다** (3장, 4.2 — 밀도를 등급 인자로도 쓰고 분모로도 쓰면
순환 논증이 된다).

원본은 cp949 인코딩, 광역시(부산/대구/인천/광주/대전/울산/세종)는 시도=시군으로 통합
표기돼 있다. 우리 발생 마스터의 강화군/북구/군위군/사하구/울주군은 각각 인천/대구/대구/
부산/울산으로 매핑해야 조인된다(작업지시서 2.6 표 그대로).

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
from app.geo_normalize import parse_address_prefix
from app.master_loader import load_master_deduped

METRO_SIGUN_MAP = {
    "강화군": "인천",
    "북구": "대구",
    "군위군": "대구",
    "사하구": "부산",
    "울주군": "울산",
}


def _stats_key(sigun_raw: str) -> str:
    return METRO_SIGUN_MAP.get(sigun_raw, sigun_raw)


def _load_lookup() -> dict[tuple[str, int], int]:
    df = pd.read_csv(LIVESTOCK_STATS_PATH, encoding="cp949")
    lookup = {}
    for _, row in df.iterrows():
        lookup[(row["시군"], int(row["년도"]))] = int(row["전체두수"])
    return lookup


_LOOKUP = _load_lookup()


def livestock_count(sigun_raw: str, year: int) -> int | None:
    """sigun_raw: 발생 마스터/Node1이 쓰는 시군명(예: "강화군", "파주시").
    반환: 그 시군의 그 연도 전체두수. 통계에 없으면 None(추정치로 채우지 않는다)."""
    key = _stats_key(sigun_raw)
    return _LOOKUP.get((key, year))


def outbreak_sigun_set() -> set[str]:
    df = load_master_deduped(verbose=False)
    sigun_set = set()
    for addr in df["address"]:
        _, sigun, _ = parse_address_prefix(addr)
        sigun_set.add(sigun)
    return sigun_set


def verify_coverage(verbose: bool = True) -> None:
    """발생 시군 37개가 통계와 최소 한 해라도 연결되는지 확인. 완전 실패 시 sys.exit."""
    sigun_set = outbreak_sigun_set()

    fully_unresolved = []
    partial_gaps = {}
    years = range(2018, 2027)

    for sigun in sorted(sigun_set):
        key = _stats_key(sigun)
        present = [y for y in years if (key, y) in _LOOKUP]
        if not present:
            fully_unresolved.append(sigun)
        else:
            missing = [y for y in years if y not in present]
            if missing:
                partial_gaps[sigun] = missing

    if fully_unresolved:
        sys.exit(
            f"[livestock_stats] 조인 실패 — 통계와 전혀 연결 안 되는 발생 시군: {fully_unresolved}. "
            "매핑 테이블(METRO_SIGUN_MAP)을 확인할 것."
        )

    if verbose:
        print(f"[livestock_stats] 발생 시군 {len(sigun_set)}개 전부 통계와 연결 확인(최소 1개 연도).")
        if partial_gaps:
            print(f"[livestock_stats] 부분 결측 {len(partial_gaps)}개 시군(추정치로 채우지 않음, 해당 연도는 분모 계산에서 제외):")
            for sigun, missing in partial_gaps.items():
                print(f"  - {sigun}: {missing}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    verify_coverage()
    print()
    print("파주시 2026:", livestock_count("파주시", 2026))
    print("강화군(→인천) 2021:", livestock_count("강화군", 2021))
    print("파주시 2020(결측 예상):", livestock_count("파주시", 2020))
