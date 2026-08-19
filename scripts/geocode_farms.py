"""ASF T1 — 2단계: 좌표 없는 농장만 카카오 로컬 API로 지오코딩.

.venv/geocode.py의 주소 검색 → 키워드 검색 폴백, 남한 좌표 범위 검증 로직을 그대로 가져오되,
이미 위도/경도가 있는 행은 API를 호출하지 않고 건너뛴다는 점이 다르다
(원본 geocode.py는 입력 CSV의 모든 행을 무조건 재조회한다).

준비
    .env(.venv/.env, 상위 디렉터리 탐색으로 자동 인식)에 KAKAO_KEY 필요

실행
    python scripts/geocode_farms.py

입력   data/farms_merged.csv
출력   data/farms_geocoded.csv   (지오코딩 실패 행은 제외 — 리 중심점 대체 금지)
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

KEY = os.getenv("KAKAO_KEY")
HEADERS = {"Authorization": f"KakaoAK {KEY}"}

# 남한 영역. 이 범위를 벗어나면 잘못 잡힌 좌표다.
LAT_RANGE = (33.0, 38.7)
LON_RANGE = (124.5, 132.0)

DATA_DIR = "data"
UNIFIED_COLS = ["시군", "농장명", "축종", "주소", "사육두수", "위도", "경도", "기준일자", "출처파일"]


def _call(endpoint: str, query: str):
    """카카오 로컬 API 호출. 실패 시 (None, None, 사유)를 돌려준다."""
    try:
        r = requests.get(
            f"https://dapi.kakao.com/v2/local/search/{endpoint}.json",
            params={"query": query, "size": 1},
            headers=HEADERS,
            timeout=10,
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

    # 카카오는 x가 경도, y가 위도다.
    return float(docs[0]["y"]), float(docs[0]["x"]), ""


def geocode(addr: str, fallback: str):
    """주소 검색 → 실패 시 키워드 검색 순으로 시도."""
    lat, lon, why = _call("address", addr)
    if lat is not None:
        return lat, lon, "주소", why

    time.sleep(0.2)
    lat, lon, why = _call("keyword", fallback)
    if lat is not None:
        return lat, lon, "키워드", why

    return None, None, None, why


def in_korea(lat, lon) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def main():
    if not KEY:
        sys.exit("KAKAO_KEY 환경변수가 없습니다. .venv/.env를 확인하세요.")

    df = pd.read_csv(f"{DATA_DIR}/farms_merged.csv", encoding="utf-8-sig")

    has_coord = df["위도"].notna() & df["경도"].notna()
    todo_idx = df.index[~has_coord]

    failed, suspicious, ok_by_method = [], [], {"주소": 0, "키워드": 0}
    total = len(todo_idx)

    for n, i in enumerate(todo_idx, 1):
        row = df.loc[i]
        addr = str(row["_geo_addr"])
        fallback = f"{row['시군']} {row['농장명']}"

        lat, lon, how, why = geocode(addr, fallback)

        if lat is None:
            failed.append((i, addr, why))
            mark = "x"
        elif not in_korea(lat, lon):
            suspicious.append((i, addr, lat, lon))
            mark = "?"
        else:
            df.at[i, "위도"] = round(lat, 6)
            df.at[i, "경도"] = round(lon, 6)
            ok_by_method[how] += 1
            mark = "."

        print(f"  {mark} {n:4d}/{total}  {addr[:40]}", flush=True)
        time.sleep(0.15)

    # 지오코딩 대상이었는데 실패했거나(좌표 없음) 범위 밖(suspicious)인 행은 버린다.
    fail_idx = [i for i, _, _ in failed] + [i for i, _, _, _ in suspicious]
    result = df.drop(index=fail_idx).drop(columns=["_geo_addr"])[UNIFIED_COLS]

    out_path = f"{DATA_DIR}/farms_geocoded.csv"
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    ok = len(df) - len(fail_idx)
    print()
    print(f"좌표 확보 {ok}개 / 전체 {len(df)}개 → {out_path}")
    print(f"  이번 실행 지오코딩: 주소검색 {ok_by_method['주소']}건 / 키워드검색 {ok_by_method['키워드']}건")

    if failed:
        print(f"\n실패 {len(failed)}건 (제외됨) — 손으로 보완하려면 원본에서 주소 확인")
        for i, addr, why in failed:
            print(f"  idx={i}  {addr}  ({why})")

    if suspicious:
        print(f"\n범위 이탈 {len(suspicious)}건 (제외됨) — 좌표가 한반도 밖입니다")
        for i, addr, lat, lon in suspicious:
            print(f"  idx={i}  {addr}  ({lat}, {lon})")


if __name__ == "__main__":
    main()
