"""ASF T2 — 리플레이 검증 (작업지시서 4.4). **일회성 스크립트, API 아님** — 표 4개를
콘솔에 출력하는 게 전부다. 대시보드가 실시간으로 다시 돌릴 이유가 없어 API로 노출하지
않기로 사용자와 합의했다.

루프:
    for 주차 T in 2019-09 ~ 2026-08 (7일 간격):
        grade(시군, T) — 확진일 <= T 인 발생만 씀(grade() 자체가 이미 이 규칙을 지킴)
        확진일 > T, <= T+7일(다음 1주) 인 발생이 어느 시군에서 났는지 기록

분모: "시군-주의 사육두수"(app/livestock_stats.py, 그 주차 T의 연도 값). **결측이면
그 시군-주는 집계에서 제외한다** — 추정치로 채우지 않는다(가상 데이터 금지, 원칙 2).
제외 건수를 콘솔에 명시한다.

지표 A(보조): 전체 시군-주를 등급별로 묶어 (발생건수 / 두수합) 비교.
지표 B(주 지표): **같은 시군 안에서** 심각이었던 주들의 발생률 vs 평시였던 주들의
발생률을 비교 — 지역 고유 위험도를 시군별로 고정해 시간축 신호만 남긴다. 두 상태를
모두 겪은 시군만 비교 대상(한쪽 상태가 아예 없으면 비교 자체가 성립하지 않음). 시군별
상세 표 + 그 시군들만 모아 다시 pooled한 집계 행을 같이 낸다(어떻게 집계하든 투명하게
보이도록 — 작업지시서 문장("전 시군에 대해 집계")이 정확한 집계 공식까지 명시하진 않음).

2019~2025 구간과 2026 구간을 분리해서 낸다(4.6 — 2026은 사료 매개라 거리 기반 규칙이
원리적으로 못 잡는 게 기대 결과).

실행: python scripts/replay_validate.py
"""

import sys
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, ".")

from app.geo_normalize import all_sgg_codes, code_to_name, resolve_address  # noqa: E402
from app.grade import grade  # noqa: E402
from app.livestock_stats import livestock_count, never_farming_codes  # noqa: E402
from app.master_loader import load_master_deduped  # noqa: E402

WEEK_START = date(2019, 9, 1)
WEEK_END = date(2026, 8, 31)


def _week_starts():
    d = WEEK_START
    while d <= WEEK_END:
        yield d
        d += timedelta(days=7)


def _load_cases_with_codes() -> pd.DataFrame:
    master = load_master_deduped(verbose=False).copy()
    master["sgg_code"] = master["address"].apply(resolve_address)
    master["case_date_obj"] = master["case_date"].apply(
        lambda s: date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    )

    unresolved = master[master["sgg_code"].isna()]
    if len(unresolved):
        sys.exit(f"[replay] 시군 코드 조인 실패 {len(unresolved)}건: {unresolved['address'].tolist()}")

    return master


def build_replay_table() -> pd.DataFrame:
    master = _load_cases_with_codes()
    codes = all_sgg_codes()

    records = []
    missing_stats = 0

    for i, T in enumerate(_week_starts()):
        as_of_str = T.strftime("%Y%m%d")
        year = T.year
        next_week_end = T + timedelta(days=7)
        next_week_mask = (master["case_date_obj"] > T) & (master["case_date_obj"] <= next_week_end)
        next_week_counts = master[next_week_mask].groupby("sgg_code").size().to_dict()

        for code in codes:
            g = grade(code, as_of_str)
            sigun_name = code_to_name(code)
            head = livestock_count(code, year)
            if head is None:
                missing_stats += 1
                continue
            records.append({
                "code": code,
                "sigun": sigun_name,
                "week": as_of_str,
                "year": year,
                "grade": g["grade"],
                "cases_next_week": next_week_counts.get(code, 0),
                "head_count": head,
            })

        if (i + 1) % 52 == 0:
            print(f"[replay] {i + 1}주차 처리 완료 ({as_of_str})", flush=True)

    df = pd.DataFrame(records)
    never_farming = never_farming_codes()
    print(f"[replay] 총 시군-주 레코드 {len(df)}건, 분모 결측으로 제외된 시군-주 {missing_stats}건")
    print(f"[replay]   (양돈 통계가 어느 해에도 없는 시군구 {len(never_farming)}개가 대부분 — "
          f"서울 자치구 등 원래 양돈이 없는 지역. 부분 결측 5곳은 app/livestock_stats.py 참고)")
    return df


def indicator_a(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for g in ["평시", "주의", "심각"]:
        sub = df[df["grade"] == g]
        n_cases = int(sub["cases_next_week"].sum())
        head_weeks = int(sub["head_count"].sum())
        rate = (n_cases / (head_weeks / 10_000)) if head_weeks > 0 else None
        rows.append({
            "등급": g,
            "시군-주": len(sub),
            "발생건수": n_cases,
            "두수합(두-주)": head_weeks,
            "발생률(만두-주당)": round(rate, 3) if rate is not None else None,
        })
    return pd.DataFrame(rows)


def indicator_b(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    per_county_rows = []
    qualifying_codes = []

    for code, g in df.groupby("code"):
        sim = g[g["grade"] == "심각"]
        pyeongsi = g[g["grade"] == "평시"]
        if sim.empty or pyeongsi.empty:
            continue  # 두 상태를 모두 겪어야 "같은 시군 안 시점 간 비교"가 성립한다

        qualifying_codes.append(code)
        sim_cases, sim_head = int(sim["cases_next_week"].sum()), int(sim["head_count"].sum())
        pyeongsi_cases, pyeongsi_head = int(pyeongsi["cases_next_week"].sum()), int(pyeongsi["head_count"].sum())
        sim_rate = sim_cases / (sim_head / 10_000) if sim_head else None
        pyeongsi_rate = pyeongsi_cases / (pyeongsi_head / 10_000) if pyeongsi_head else None

        per_county_rows.append({
            "시군": code_to_name(code),
            "심각_주수": len(sim), "심각_발생": sim_cases,
            "심각_발생률": round(sim_rate, 3) if sim_rate is not None else None,
            "평시_주수": len(pyeongsi), "평시_발생": pyeongsi_cases,
            "평시_발생률": round(pyeongsi_rate, 3) if pyeongsi_rate is not None else None,
        })

    per_county_df = pd.DataFrame(per_county_rows)

    qualifying_df = df[df["code"].isin(qualifying_codes)]
    sim_all = qualifying_df[qualifying_df["grade"] == "심각"]
    pyeongsi_all = qualifying_df[qualifying_df["grade"] == "평시"]
    sim_all_head = int(sim_all["head_count"].sum())
    pyeongsi_all_head = int(pyeongsi_all["head_count"].sum())
    pooled_sim_rate = int(sim_all["cases_next_week"].sum()) / (sim_all_head / 10_000) if sim_all_head else None
    pooled_pyeongsi_rate = int(pyeongsi_all["cases_next_week"].sum()) / (pyeongsi_all_head / 10_000) if pyeongsi_all_head else None

    pooled_summary = {
        "비교 대상 시군 수(양쪽 상태 다 겪음)": len(qualifying_codes),
        "심각 발생률(pooled, 만두-주당)": round(pooled_sim_rate, 3) if pooled_sim_rate is not None else None,
        "평시 발생률(pooled, 만두-주당)": round(pooled_pyeongsi_rate, 3) if pooled_pyeongsi_rate is not None else None,
        "비율(심각/평시)": (
            round(pooled_sim_rate / pooled_pyeongsi_rate, 2)
            if pooled_sim_rate is not None and pooled_pyeongsi_rate not in (None, 0)
            else None
        ),
    }
    return per_county_df, pooled_summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    df = build_replay_table()

    period_a = df[df["year"] <= 2025]
    period_b = df[df["year"] == 2026]

    for label, sub in [("2019~2025", period_a), ("2026", period_b)]:
        n_case_weeks = int(sub["cases_next_week"].sum())
        print()
        print(f"########## {label} 구간 (다음주 발생 총 {n_case_weeks}건, 시군-주 {len(sub)}건) ##########")
        print("이벤트 수가 적어 신뢰구간이 넓다 — 통계적 유의성 검정 없이 서술적 비교로만 해석할 것.")

        print()
        print(f"----- 지표 A ({label}, 시군 간 비교, 보조 지표) -----")
        print(indicator_a(sub).to_string(index=False))

        print()
        print(f"----- 지표 B ({label}, 시군 내 시점 간 비교, 주 지표) -----")
        per_county_df, pooled = indicator_b(sub)
        if per_county_df.empty:
            print("(이 구간엔 심각/평시 두 상태를 모두 겪은 시군이 없음)")
        else:
            print(per_county_df.to_string(index=False))
            print()
            for k, v in pooled.items():
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
