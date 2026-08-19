"""ASF T1 — 나머지 시군(영덕군/영천시/경주시 제외) 지오코딩 실패 87건 재검토.

8/19 리뷰 승인 범위: "텍스트만 고치면 되는 것만" 재시도. 이천시류(주소 형식은 멀쩡한데
카카오 DB에 그 지번이 없는 경우)는 그대로 둔다 — 근거 없이 값을 만들지 않는다는 원칙 유지.

정제 규칙 (전부 원본에 있던 부가 설명/구분자를 제거하는 것이지, 새 값을 만들지 않음):
1. "외N필(지)?(...)" 부가 필지 설명 제거 (영덕군과 동일 패턴)
2. 쉼표/마침표로 나열된 복수 지번 중 첫 번째만 사용
3. "산 32" -> "산32" (카카오 지번 표기 관례 — 산림 지번은 붙여 써야 검색됨)
4. 양산시 1건 원본 오타 "경상냠도" -> "경상남도" (단순 오탈자 교정, 위치 추정 아님)

입력   data/farms_merged.csv, data/farms_geocoded.csv
출력   data/farms_geocoded.csv (성공분 추가)
"""

import re
import sys
import time

import pandas as pd

sys.path.insert(0, "scripts")
from geocode_farms import KEY, _call, in_korea  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = "data"
UNIFIED_COLS = ["시군", "농장명", "축종", "주소", "사육두수", "위도", "경도", "기준일자", "출처파일"]
SKIP_SIGUN = ["영덕군", "영천시", "경주시"]  # 이미 처리했거나(영덕군/영천시) 처리 방침 확정(경주시=드롭)


def clean(addr: str) -> str:
    addr = re.sub(r"\s*외\s*\d*필지?(?:\s*\([^)]*\))?", "", addr)
    addr = re.sub(r"^(.*?\d+(?:-\d+)?)[\s,.]+\d+.*$", r"\1", addr)
    addr = re.sub(r"산\s+(\d)", r"산\1", addr)
    addr = addr.replace("경상냠도", "경상남도")
    return addr.strip()


def find_missing(merged: pd.DataFrame, geo: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["시군", "농장명", "축종", "주소", "사육두수", "기준일자", "출처파일"]

    def make_key(df):
        return df[key_cols].apply(lambda row: "|".join(str(v) for v in row), axis=1)

    m = merged.copy()
    m["_k"] = make_key(m)
    m_dedup = m.drop_duplicates(subset="_k", keep="first")
    g = geo.copy()
    g["_k"] = make_key(g)
    missing = m_dedup[~m_dedup["_k"].isin(set(g["_k"]))].copy()
    return missing[~missing["시군"].isin(SKIP_SIGUN)]


def main():
    if not KEY:
        sys.exit("KAKAO_KEY 환경변수가 없습니다.")

    merged = pd.read_csv(f"{DATA_DIR}/farms_merged.csv", encoding="utf-8-sig")
    geo = pd.read_csv(f"{DATA_DIR}/farms_geocoded.csv", encoding="utf-8-sig")

    missing = find_missing(merged, geo)
    print(f"검토 대상: {len(missing)}건 (영덕군/영천시/경주시 제외)")

    candidates = []
    for _, row in missing.iterrows():
        cleaned = clean(row["_geo_addr"])
        if cleaned != row["_geo_addr"]:
            candidates.append((row, cleaned))

    print(f"정제로 바뀐 주소(재시도 대상): {len(candidates)}건, 나머지 {len(missing) - len(candidates)}건은 원본 그대로 실패 상태 유지(카카오 DB 미보유로 추정, 리뷰 완료)")

    recovered = []
    for row, cleaned in candidates:
        lat, lon, why = _call("address", cleaned)
        mark = "."
        if lat is not None and in_korea(lat, lon):
            r = row[UNIFIED_COLS].to_dict()
            r["위도"], r["경도"] = round(lat, 6), round(lon, 6)
            recovered.append(r)
        else:
            mark = "x"
        print(f"  {mark} {row['시군']}  {row['_geo_addr']}  ->  {cleaned}")
        time.sleep(0.15)

    print(f"\n복구: {len(recovered)}/{len(candidates)}건")

    result = pd.concat([geo, pd.DataFrame(recovered, columns=UNIFIED_COLS)], ignore_index=True)
    result.to_csv(f"{DATA_DIR}/farms_geocoded.csv", index=False, encoding="utf-8-sig")
    print(f"최종: {len(result)}행 → {DATA_DIR}/farms_geocoded.csv")

    recovered_keys = {(r["시군"], r["농장명"], r["주소"]) for r in recovered}
    still_failing = missing[
        ~missing.apply(lambda r: (r["시군"], r["농장명"], r["주소"]) in recovered_keys, axis=1)
    ]
    print(f"\n계속 실패로 남는 {len(still_failing)}건 (T4 한계 명시용, 시군별):")
    print(still_failing["시군"].value_counts().to_string())


if __name__ == "__main__":
    main()
