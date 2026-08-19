"""ASF T1 — retry_failures.py의 patch_address_prefix가 과도하게 걸러낸 10건 복구.

성주군 "성신농장"(8건) + 이름 없는 2건이 전부 동일 주소(초전면 용봉리, 사육두수만 다른
별도 축사)인데, (시군,농장명) 키가 겹친다는 이유로 drop_duplicates(keep=False)가
통째로 제외했고 이후 drop_city_only가 접두어 없는 짧은 주소로 오인해 삭제했다.
실제로는 좌표가 유효한 별개 축사 10건이라 복구한다 (원본 사육두수 확인 완료, 8.19 리뷰).

입력   data/farms_merged.csv (해당 10건의 _geo_addr, 사육두수 등)
출력   data/farms_geocoded.csv (10행 추가)
"""

import sys

import pandas as pd

sys.path.insert(0, "scripts")
from geocode_farms import KEY, _call, in_korea  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = "data"
UNIFIED_COLS = ["시군", "농장명", "축종", "주소", "사육두수", "위도", "경도", "기준일자", "출처파일"]


def main():
    if not KEY:
        sys.exit("KAKAO_KEY 환경변수가 없습니다.")

    merged = pd.read_csv(f"{DATA_DIR}/farms_merged.csv", encoding="utf-8-sig")
    geo = pd.read_csv(f"{DATA_DIR}/farms_geocoded.csv", encoding="utf-8-sig")

    target = merged[(merged["시군"] == "성주군") & (merged["주소"].str.contains("초전면 용봉리"))]
    print(f"복구 대상: {len(target)}건 (주소 전부 동일하므로 1회만 조회)")

    addr = target.iloc[0]["_geo_addr"]
    lat, lon, why = _call("address", addr)
    if lat is None or not in_korea(lat, lon):
        sys.exit(f"지오코딩 실패: {addr} ({why}) — 복구 중단, 기존 파일 변경 없음")

    print(f"  {addr}  ->  ({lat}, {lon})")

    rows = []
    for _, row in target.iterrows():
        r = row[UNIFIED_COLS].to_dict()
        r["위도"], r["경도"] = round(lat, 6), round(lon, 6)
        rows.append(r)

    result = pd.concat([geo, pd.DataFrame(rows, columns=UNIFIED_COLS)], ignore_index=True)
    result.to_csv(f"{DATA_DIR}/farms_geocoded.csv", index=False, encoding="utf-8-sig")
    print(f"복구 완료: {len(rows)}건 추가 → 전체 {len(result)}행")


if __name__ == "__main__":
    main()
