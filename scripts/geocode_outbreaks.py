"""ASF T3 — 발생 마스터(82행, 중복 제거 후) 주소를 카카오로 지오코딩.

scripts/geocode_farms.py의 KEY/_call/in_korea를 그대로 재사용한다(T1과 같은 방식).

**이 출력은 지도의 10km 원 표시 전용이다. 등급 판정에는 절대 쓰지 않는다**
(작업지시서 원칙 4 — 등급/리플레이 검증은 발생 마스터의 주소·날짜만 쓰고, 좌표를 비롯한
파생 데이터는 표시에만 쓴다). Node1의 시군 구조화 추출과도 무관 — 이 스크립트는 좌표만
만들고, 시군 파싱은 app/geo_normalize.py + Node1이 별도로 한다.

실패 행은 T1과 같은 원칙으로 버린다(리 중심점 대체 금지).

실행   python scripts/geocode_outbreaks.py
출력   data/asf_master_v1_geocoded.csv  (마스터 컬럼 + 위도,경도)
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, "scripts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geocode_farms import KEY, _call, in_korea  # noqa: E402

from app.master_loader import load_master_deduped  # noqa: E402

OUT_PATH = "data/asf_master_v1_geocoded.csv"


def geocode_address(addr: str):
    lat, lon, why = _call("address", addr)
    if lat is not None:
        return lat, lon, why
    time.sleep(0.2)
    return None, None, why


def main():
    if not KEY:
        sys.exit("KAKAO_KEY 환경변수가 없습니다.")

    df = load_master_deduped()

    lats, lons = [], []
    failed, suspicious = [], []
    total = len(df)

    for n, (i, row) in enumerate(df.iterrows(), 1):
        addr = str(row["address"])
        lat, lon, why = geocode_address(addr)

        if lat is None:
            failed.append((i, addr, why))
            lats.append(None)
            lons.append(None)
            mark = "x"
        elif not in_korea(lat, lon):
            suspicious.append((i, addr, lat, lon))
            lats.append(None)
            lons.append(None)
            mark = "?"
        else:
            lats.append(round(lat, 6))
            lons.append(round(lon, 6))
            mark = "."

        print(f"  {mark} {n:3d}/{total}  {addr[:40]}", flush=True)
        time.sleep(0.15)

    df = df.copy()
    df["위도"] = lats
    df["경도"] = lons

    drop_idx = [i for i, _, _ in failed] + [i for i, _, _, _ in suspicious]
    result = df.drop(index=drop_idx)

    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    ok = len(df) - len(drop_idx)
    print()
    print(f"좌표 확보 {ok}개 / 전체 {len(df)}개 → {OUT_PATH}")
    print("(이 파일은 지도 10km 원 표시 전용 — 등급 판정에는 사용하지 않는다)")

    if failed:
        print(f"\n실패 {len(failed)}건 (제외됨):")
        for i, addr, why in failed:
            print(f"  idx={i}  {addr}  ({why})")

    if suspicious:
        print(f"\n범위 이탈 {len(suspicious)}건 (제외됨):")
        for i, addr, lat, lon in suspicious:
            print(f"  idx={i}  {addr}  ({lat}, {lon})")


if __name__ == "__main__":
    main()
