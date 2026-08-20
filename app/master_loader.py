"""ASF T3 — 발생 마스터 CSV를 파이프라인 전용으로 로드하는 단일 함수.

작업지시서 2.1: index 37/38(20230925, 강원특별자치도 화천군 하남면 원천리, mafra_api)은
중복 확인된 1건이며, 원본 파일을 고치지 않고 로드 직후 파이프라인 안에서 제거해 82건으로
맞춘다. 제거 사실은 콘솔에 출력한다.

주의: 두 행의 case_date/address/source/legaldong은 완전히 같지만 infected(감염두수)는
1과 4로 다르다. 어느 쪽이 맞는 수치인지 원본에서 확정할 수 없어, 파일에 먼저 나오는 행
(infected=1)을 남기고 나머지를 버린다 — 이 선택은 등급 판정(발생 여부/날짜만 사용)에는
영향이 없지만, 감염두수 수치를 그대로 인용할 일이 있다면 이 불일치를 먼저 확인할 것.

이 함수는 app/extraction.py(Node1)와 scripts/geocode_outbreaks.py 양쪽이 공유해서 쓴다.
"""

import sys

import pandas as pd

from app.config import MASTER_PATH

DUP_SUBSET = ["case_date", "address", "source"]


def load_master_deduped(verbose: bool = True) -> pd.DataFrame:
    df = pd.read_csv(MASTER_PATH, encoding="utf-8-sig", dtype=str)

    dup_mask = df.duplicated(subset=DUP_SUBSET, keep="first")
    if dup_mask.any() and verbose:
        dropped = df[dup_mask]
        kept_first = df[df.duplicated(subset=DUP_SUBSET, keep=False) & ~dup_mask]
        print(f"[master_loader] 중복 {dup_mask.sum()}건 제거 (파이프라인 로드 시점, 원본 파일은 그대로):")
        for i in dropped.index:
            row = dropped.loc[i]
            print(f"  - idx={i} {row['case_date']} {row['address']} infected={row['infected']}  (제거)")
        for i in kept_first.index:
            row = kept_first.loc[i]
            print(f"  - idx={i} {row['case_date']} {row['address']} infected={row['infected']}  (유지)")
        if not dropped["infected"].equals(kept_first["infected"].reset_index(drop=True)):
            pass  # infected 값이 서로 다를 수 있음 — 위 출력에서 육안 확인

    out = df[~dup_mask].reset_index(drop=True)

    if verbose:
        print(f"[master_loader] 발생 마스터 로드: {len(df)}행 → 중복 제거 후 {len(out)}행")

    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = load_master_deduped()
    print(result["case_date"].str[:4].value_counts().sort_index())
