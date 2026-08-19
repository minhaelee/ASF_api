"""ASF T1 — 3단계: 검토 중 발견한 3가지 문제를 보정.

사용자 확인 완료 (2026-08-19 리뷰):
1. 주소 표시 컬럼에 시도/시군구 접두어 누락 (성주군 등 42건)
   → build_farms.py 수정 후 재생성된 farms_merged.csv의 주소로 맞춰 patch (API 불필요)
2. 경주시 2건은 "경상북도 경주시"까지만 있어 시청 좌표로 찍힘 → 제외 (사용자 결정)
3. 영덕군 12건: "외N필(...)" 부가 필지 설명 때문에 실패 → 설명 제거 후 재시도 (사용자 결정)
4. 영천시 43건: 번지수가 비정상적으로 큼(하이픈 소실 추정) → 하이픈 복원 시도 (사용자 결정, 위험 감수)
   복원에 성공한 행은 출처파일에 "(번지 하이픈 추정 복원)"을 덧붙여 출력에 명시한다 (작업 원칙 2).
   카카오 주소 검색은 번지가 정확히 맞아야 결과를 주므로, 틀린 추정은 대부분 "검색 결과 없음"으로
   자연 실패한다 — 엉뚱한 곳에 잘못 매칭될 위험은 낮지만 0은 아니다.

입력   data/farms_merged.csv (재생성됨, 주소 접두어 수정 반영)
       data/farms_geocoded.csv (기존 지오코딩 결과)
출력   data/farms_geocoded.csv (덮어씀)
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


def _key(df: pd.DataFrame) -> pd.Series:
    return df["농장명"].astype(str) + "|" + df["주소"].astype(str)


def patch_address_prefix(geo: pd.DataFrame, merged: pd.DataFrame) -> pd.DataFrame:
    """주소에 시군 이름이 없는 행(구버전 build_farms.py 버그로 접두어 누락)만 골라
    새로 생성된 merged의 같은 (시군,농장명) 주소로 맞춘다. 전체 조인 대신 문제 행만
    범위를 좁혀 처리해 (시군,농장명) 키 충돌 위험을 낮춘다."""
    geo = geo.copy()
    needs_fix = ~geo.apply(lambda r: str(r["시군"]) in str(r["주소"]), axis=1)
    n = int(needs_fix.sum())
    if n == 0:
        print("주소 접두어 patch: 대상 없음")
        return geo

    affected_sigun = geo.loc[needs_fix, "시군"].unique()
    lookup = merged[merged["시군"].isin(affected_sigun)]
    dupe_keys = int(lookup.duplicated(subset=["시군", "농장명"], keep=False).sum())
    lookup_map = lookup.drop_duplicates(subset=["시군", "농장명"], keep=False).set_index(["시군", "농장명"])["주소"]

    changed = 0
    for idx in geo.index[needs_fix]:
        key = (geo.at[idx, "시군"], geo.at[idx, "농장명"])
        if key in lookup_map.index:
            geo.at[idx, "주소"] = lookup_map.loc[key]
            changed += 1

    print(f"주소 접두어 patch: {n}건 대상 중 {changed}건 수정 (대상 시군: {sorted(affected_sigun)}, 매칭 제외된 중복키 {dupe_keys}건)")
    return geo


def drop_city_only(geo: pd.DataFrame) -> pd.DataFrame:
    mask = geo["주소"].astype(str).str.split().str.len() <= 2
    n = mask.sum()
    if n:
        print(f"경주시 등 시군 단위까지만 있는 주소 {n}건 제외:")
        for _, r in geo[mask].iterrows():
            print(f"  {r['시군']}  {r['농장명']}  {r['주소']}")
    return geo[~mask]


def clean_yeongdeok_addr(addr: str) -> str:
    # "하저리 237 외3필(237-1.238.234)" / "금호리 41 외1필지(48)" -> 지번만 남김
    addr = re.sub(r"\s*외\s*\d*필지?\s*\([^)]*\)", "", addr)
    # "강구면 금호리 157. 159" -> "강구면 금호리 157" (첫 번째 지번만 사용)
    addr = re.sub(r"^(.*?\d+(?:-\d+)?)[\s.]+\d+.*$", r"\1", addr)
    return addr.strip()


def retry_yeongdeok(merged: pd.DataFrame, geo: pd.DataFrame) -> pd.DataFrame:
    m = merged[merged["시군"] == "영덕군"]
    todo = m[~_key(m).isin(set(_key(geo[geo["시군"] == "영덕군"])))]
    print(f"\n영덕군 재시도 대상: {len(todo)}건")

    recovered = []
    for _, row in todo.iterrows():
        cleaned = clean_yeongdeok_addr(row["_geo_addr"])
        lat, lon, why = _call("address", cleaned)
        mark = "."
        if lat is not None and in_korea(lat, lon):
            r = row[UNIFIED_COLS].to_dict()
            r["위도"], r["경도"] = round(lat, 6), round(lon, 6)
            recovered.append(r)
        else:
            mark = "x"
        print(f"  {mark} {row['주소']}  ->  {cleaned}")
        time.sleep(0.15)

    print(f"영덕군 복구: {len(recovered)}/{len(todo)}건")
    return pd.DataFrame(recovered, columns=UNIFIED_COLS)


def hyphen_candidates(addr: str):
    m = re.search(r"(\d+)\s*$", addr)
    if not m:
        return []
    num = m.group(1)
    head = addr[: m.start()]
    cands = []
    for split in (2, 1, 3):
        if len(num) > split:
            cands.append(f"{head}{num[:-split]}-{num[-split:]}")
    return cands


def retry_yeongcheon(merged: pd.DataFrame, geo: pd.DataFrame) -> pd.DataFrame:
    m = merged[merged["시군"] == "영천시"]
    todo = m[~_key(m).isin(set(_key(geo[geo["시군"] == "영천시"])))]
    print(f"\n영천시 재시도 대상: {len(todo)}건 (하이픈 위치 추정)")

    recovered = []
    for _, row in todo.iterrows():
        found = False
        for cand in hyphen_candidates(row["_geo_addr"]):
            lat, lon, why = _call("address", cand)
            time.sleep(0.15)
            if lat is not None and in_korea(lat, lon):
                r = row[UNIFIED_COLS].to_dict()
                r["위도"], r["경도"] = round(lat, 6), round(lon, 6)
                r["출처파일"] = f"{r['출처파일']} (번지 하이픈 추정 복원: {cand.split()[-1]})"
                recovered.append(r)
                print(f"  . {row['주소']}  ->  {cand}")
                found = True
                break
        if not found:
            print(f"  x {row['주소']}  (후보 전부 실패)")

    print(f"영천시 복구: {len(recovered)}/{len(todo)}건 — 하이픈 추정값이므로 출처파일에 표시됨")
    return pd.DataFrame(recovered, columns=UNIFIED_COLS)


def main():
    if not KEY:
        sys.exit("KAKAO_KEY 환경변수가 없습니다.")

    merged = pd.read_csv(f"{DATA_DIR}/farms_merged.csv", encoding="utf-8-sig")
    geo = pd.read_csv(f"{DATA_DIR}/farms_geocoded.csv", encoding="utf-8-sig")

    geo = patch_address_prefix(geo, merged)
    geo = drop_city_only(geo)

    yeongdeok_new = retry_yeongdeok(merged, geo)
    yeongcheon_new = retry_yeongcheon(merged, geo)

    result = pd.concat([geo, yeongdeok_new, yeongcheon_new], ignore_index=True)

    out_path = f"{DATA_DIR}/farms_geocoded.csv"
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"\n최종: {len(result)}행 → {out_path}")


if __name__ == "__main__":
    main()
