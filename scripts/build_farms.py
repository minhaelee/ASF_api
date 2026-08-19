"""ASF T1 — 1단계: 농장 현황 두 파일을 하나의 스키마로 통합.

입력
    data/양돈농가현황_통합.csv           (UTF-8, 전국, 사용자가 돼지로 필터링 완료)
    data/경기도_우제류축산농가현황.csv    (CP949, 경기도, 축종명으로 돼지만 걸러서 사용)

경기도 시군은 우제류축산농가현황 파일을 우선한다 (최신 + 좌표 보유율이 높음).
양돈농가현황_통합의 경기도 행은 전부 이 파일의 경기 돼지 시군에 포함되므로,
통합 파일의 경기도 행은 드롭하고 경기 부분은 우제류 파일로 완전히 대체한다.

출력
    data/farms_merged.csv
    열: 시군,농장명,축종,주소,사육두수,위도,경도,기준일자,출처파일,_geo_addr
    (_geo_addr는 geocode_farms.py가 쓰는 지오코딩 질의용 주소. 최종 산출물에는 남기지 않는다)
"""

import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = "data"
UNIFIED_COLS = ["시군", "농장명", "축종", "주소", "사육두수", "위도", "경도", "기준일자", "출처파일"]


def _first_nonnull(*values):
    for v in values:
        if pd.notna(v) and str(v).strip():
            return str(v).strip()
    return None


def _with_prefix(addr: str, sido: str, sigungu: str) -> str:
    if sigungu and sigungu in addr:
        return addr
    return f"{sido} {sigungu} {addr}".strip()


def load_tonghap() -> pd.DataFrame:
    df = pd.read_csv(f"{DATA_DIR}/양돈농가현황_통합.csv", encoding="utf-8")
    df = df[df["시도"] != "경기도"].copy()

    rows = []
    dropped_no_addr = 0
    for _, r in df.iterrows():
        base_addr = _first_nonnull(r.get("도로명주소"), r.get("지번주소"))
        if base_addr is None:
            dropped_no_addr += 1
            continue
        geo_addr = _with_prefix(base_addr, str(r.get("시도", "")).strip(), str(r.get("시군구", "")).strip())
        rows.append({
            "시군": r.get("시군구"),
            "농장명": r.get("농장명"),
            "축종": r.get("축종"),
            "주소": geo_addr,
            "사육두수": r.get("사육두수"),
            "위도": r.get("위도"),
            "경도": r.get("경도"),
            "기준일자": r.get("기준일자"),
            "출처파일": r.get("원본파일"),
            "_geo_addr": geo_addr,
        })
    out = pd.DataFrame(rows)
    print(f"양돈농가현황_통합 (경기 제외): {len(df)}행 중 주소 없어 제외 {dropped_no_addr}행 → 사용 {len(out)}행")
    return out


def load_gyeonggi() -> pd.DataFrame:
    df = pd.read_csv(f"{DATA_DIR}/경기도_우제류축산농가현황.csv", encoding="cp949")
    pig = df[df["축종명"].astype(str).str.contains("돼지", na=False)].copy()

    rows = []
    dropped_no_addr = 0
    for _, r in pig.iterrows():
        base_addr = _first_nonnull(r.get("소재지도로명주소"), r.get("소재지지번주소"))
        if base_addr is None:
            dropped_no_addr += 1
            continue
        rows.append({
            "시군": r.get("시군명"),
            "농장명": r.get("농장명"),
            "축종": r.get("축종명"),
            "주소": base_addr,
            "사육두수": r.get("사육두수"),
            "위도": r.get("위도"),
            "경도": r.get("경도"),
            "기준일자": r.get("데이터기준일자"),
            "출처파일": "경기도_우제류축산농가현황.csv",
            "_geo_addr": base_addr,
        })
    out = pd.DataFrame(rows)
    print(f"경기도_우제류축산농가현황 (돼지만): {len(pig)}행 중 주소 없어 제외 {dropped_no_addr}행 → 사용 {len(out)}행")
    return out


def main():
    tonghap = load_tonghap()
    gyeonggi = load_gyeonggi()

    merged = pd.concat([tonghap, gyeonggi], ignore_index=True)

    has_coord = merged["위도"].notna() & merged["경도"].notna()
    need_geocode = (~has_coord).sum()

    out_path = f"{DATA_DIR}/farms_merged.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")

    print()
    print(f"병합 완료: {len(merged)}행 → {out_path}")
    print(f"  기존 좌표 보유: {has_coord.sum()}행")
    print(f"  지오코딩 필요: {need_geocode}행")


if __name__ == "__main__":
    main()
