"""ASF v3 — 2026-08-26(7차) 농장 레지스트리를 국가 표준 인허가 데이터로 전체 교체.

data/농가현황자료/ 아래 152개 시군별 파일을 하나하나 매핑하려다가, 사용자가 추가로
넣어준 "동물_가축사육업.csv"(지방행정인허가데이터개방시스템, 전국 단일 포맷)가 훨씬
낫다는 걸 확인했다 — 전국 커버리지, 위경도 좌표 97% 포함, 시군마다 다른 컬럼명 문제
자체가 없음. 152개 파일 조합은 폐기했다(사용자 확인, "국가파일로 전체 교체").

트레이드오프: 이 국가 파일엔 사육두수 컬럼이 아예 없다. 기존 farms_geocoded.csv
(T1 산출물)는 일부 농장에 사육두수가 있었지만, 국가 파일로 전체 교체하면 전 농장이
"미상"이 된다 — 사용자가 이 트레이드오프를 알고 명시적으로 선택했다(위치 커버리지
2,285개 -> 5,600+개 우선). farm_order.py/화면은 이미 사육두수 결측을 "미상"으로
정상 처리하므로 코드 변경 없이도 동작한다.

좌표계: 원본 "좌표정보(X)/(Y)"는 위경도가 아니라 EPSG:5174(Bessel 중부원점 TM,
보정계수 없음 — 사용자 확인)다. pyproj로 WGS84(EPSG:4326)로 변환한다.

포함 대상:
    - 동물_가축사육업.csv: 주사육업종에 "돼지" 포함 + 영업상태명="영업/정상"만
    - 동물_도축업.csv: 영업상태명="영업/정상"만, 축종="도축장"으로 태깅(2026-08-26
      피드백 — 도축장도 ASF 전파 경로로 지목되는 시설이라 포함. 축종 컬럼이 따로
      없어 돼지 전용 도축장만 못 걸러내므로 전체 활성 도축장을 포함한다)
    - "위탁농장"은 별도 시설이 아니라 계약 형태일 뿐이라 가축사육업 인허가를
      그대로 받으므로, 이미 위 가축사육업 데이터에 자동으로 포함돼 있다(별도 처리 불필요)

제외: 동물_종축업.csv(축종 구분 컬럼이 없어 돼지 전용 종돈장만 못 거름, 소·닭 등
종축업까지 섞여 들어가는 걸 피하려 이번엔 제외), 동물_동물운송업.csv(고정된 "시설"이
아니라 이동 수단 사업자라 성격이 다름 — 필요하면 별도 레이어로 추후 검토)

좌표 결측 행(가축사육업 176건 + 도축업 20건, 전부 지번주소는 있음)은
scripts/geocode_farms.py의 카카오 호출 로직을 그대로 가져와 보완한다.

실행   python scripts/ingest_national_licenses_2026.py
출력   data/farms_geocoded.csv 전체 교체(기존 파일은 git 히스토리에 남음)
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import requests
from dotenv import load_dotenv
from pyproj import Transformer

load_dotenv()

KEY = os.getenv("KAKAO_KEY")
HEADERS = {"Authorization": f"KakaoAK {KEY}"}
LAT_RANGE = (33.0, 38.7)
LON_RANGE = (124.5, 132.0)

RAW_DIR = "data/농가현황자료"
UNIFIED_COLS = ["시군", "농장명", "축종", "주소", "사육두수", "위도", "경도", "기준일자", "출처파일"]

_transformer = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)


def _to_wgs84(x: str, y: str) -> tuple[float, float] | tuple[None, None]:
    if pd.isna(x) or pd.isna(y):
        return None, None
    lon, lat = _transformer.transform(float(x), float(y))
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        return None, None
    return round(lat, 6), round(lon, 6)


def _best_addr(row) -> str:
    for col in ["도로명주소", "지번주소"]:
        v = row.get(col)
        if pd.notna(v) and str(v).strip():
            return str(v).strip()
    return ""


def _sigun_from_addr(addr: str) -> str:
    """"부산광역시 사하구 장림동 ..." -> "사하구". app/geo_normalize.py::parse_address_prefix와
    동일한 단순 토큰 분리 규칙(스크립트는 app/ 패키지에 안 의존하는 T1 이래 관례를 유지)."""
    parts = addr.strip().split(maxsplit=2)
    return parts[1] if len(parts) >= 2 else ""


def load_farms() -> pd.DataFrame:
    cols = ["영업상태명", "주사육업종", "사업장명", "도로명주소", "지번주소",
            "좌표정보(X)", "좌표정보(Y)", "최종수정시점"]
    df = pd.read_csv(f"{RAW_DIR}/동물_가축사육업.csv", encoding="cp949", dtype=str, usecols=cols)
    pig = df[(df["주사육업종"].str.contains("돼지", na=False)) & (df["영업상태명"] == "영업/정상")].copy()

    rows = []
    for _, r in pig.iterrows():
        addr = _best_addr(r)
        if not addr:
            continue
        lat, lon = _to_wgs84(r["좌표정보(X)"], r["좌표정보(Y)"])
        rows.append({
            "시군": _sigun_from_addr(addr), "농장명": r["사업장명"], "축종": "돼지",
            "주소": addr, "사육두수": None, "위도": lat, "경도": lon,
            "기준일자": r.get("최종수정시점"), "출처파일": "동물_가축사육업.csv",
        })
    out = pd.DataFrame(rows)
    print(f"가축사육업(돼지, 영업/정상): {len(pig)}행 -> 주소 있는 {len(out)}행")
    return out


def load_slaughterhouses() -> pd.DataFrame:
    cols = ["영업상태명", "사업장명", "도로명주소", "지번주소", "좌표정보(X)", "좌표정보(Y)", "최종수정시점"]
    df = pd.read_csv(f"{RAW_DIR}/동물_도축업.csv", encoding="cp949", dtype=str, usecols=cols)
    active = df[df["영업상태명"] == "영업/정상"].copy()

    rows = []
    for _, r in active.iterrows():
        addr = _best_addr(r)
        if not addr:
            continue
        lat, lon = _to_wgs84(r["좌표정보(X)"], r["좌표정보(Y)"])
        rows.append({
            "시군": _sigun_from_addr(addr), "농장명": r["사업장명"], "축종": "도축장",
            "주소": addr, "사육두수": None, "위도": lat, "경도": lon,
            "기준일자": r.get("최종수정시점"), "출처파일": "동물_도축업.csv",
        })
    out = pd.DataFrame(rows)
    print(f"도축업(영업/정상): {len(active)}행 -> 주소 있는 {len(out)}행")
    return out


def _geocode_call(endpoint: str, query: str):
    try:
        r = requests.get(
            f"https://dapi.kakao.com/v2/local/search/{endpoint}.json",
            params={"query": query, "size": 1}, headers=HEADERS, timeout=10,
        )
    except requests.RequestException as e:
        return None, None, f"네트워크 오류: {e}"
    if r.status_code == 401:
        sys.exit("API 키가 잘못됐습니다. KAKAO_KEY 환경변수를 확인하세요.")
    if r.status_code != 200:
        return None, None, f"HTTP {r.status_code}"
    docs = r.json().get("documents", [])
    if not docs:
        return None, None, "검색 결과 없음"
    return float(docs[0]["y"]), float(docs[0]["x"]), ""


def fill_missing_coords(df: pd.DataFrame) -> pd.DataFrame:
    missing_idx = df.index[df["위도"].isna() | df["경도"].isna()]
    total = len(missing_idx)
    if total == 0:
        return df
    print(f"\n좌표 보완 지오코딩 대상: {total}건")

    filled, failed = 0, 0
    for n, i in enumerate(missing_idx, 1):
        addr = str(df.at[i, "주소"])
        lat, lon, why = _geocode_call("address", addr)
        if lat is None:
            time.sleep(0.15)
            lat, lon, why = _geocode_call("keyword", addr)
        if lat is not None and LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]:
            df.at[i, "위도"] = round(lat, 6)
            df.at[i, "경도"] = round(lon, 6)
            filled += 1
            mark = "."
        else:
            failed += 1
            mark = "x"
        print(f"  {mark} {n:4d}/{total}  {addr[:40]}", flush=True)
        time.sleep(0.15)

    print(f"보완 완료: {filled}건 성공, {failed}건 실패(제외 예정)")
    return df


def main():
    if not KEY:
        sys.exit("KAKAO_KEY 환경변수가 없습니다. .env를 확인하세요.")

    farms = load_farms()
    slaughterhouses = load_slaughterhouses()
    merged = pd.concat([farms, slaughterhouses], ignore_index=True)
    print(f"\n병합: {len(merged)}행 (돼지 농장 {len(farms)} + 도축장 {len(slaughterhouses)})")

    merged = fill_missing_coords(merged)

    before = len(merged)
    merged = merged.dropna(subset=["위도", "경도"])
    print(f"\n좌표 확보 최종: {len(merged)}행 (좌표 없어 제외 {before - len(merged)}행)")

    out_path = "data/farms_geocoded.csv"
    merged[UNIFIED_COLS].to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"저장: {out_path} (기존 파일 전체 교체)")


if __name__ == "__main__":
    main()
