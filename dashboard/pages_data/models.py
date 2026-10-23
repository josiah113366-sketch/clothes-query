"""[데이터 관리] 감성분석 모델. 데이터: athena-review-score 의 점수 테이블·점수 로그 (지금은 더미).

탭 4개
  1) 모델 버전·패치노트 버전 목록, Gold 가 읽는 버전, 버전을 누르면 바뀐 내용·평가 지표(이전 버전 대비)
  2) 모델별 리뷰 분석 버전 하나를 골라 속성 11개의 언급 수·평균 점수·점수 분포를 본다
  3) 버전 비교      같은 후기·속성의 두 버전 점수를 나란히 비교한다
  4) 일별 분석 현황  날짜별 Job 결과, 파싱 실패, 미점수 잔량
읽는 법 (노션·설계 규칙)
  - 모델 버전을 섞어 합산하지 않는다. 화면마다 버전을 하나 고르거나 버전별로 나눠 보여준다.
  - 속성별 언급 수를 합쳐 전체 후기 수로 쓰지 않는다 (후기 하나가 여러 속성을 언급).
  - Gold 는 후기마다 model_version_no 가 가장 큰 결과를 읽는다. 메이저(0.0 -> 1.0)는 평가 모델/로직 변경, 마이너는 작은 수정.
  - 후기 원문은 이 화면에 표시하지 않는다. review_id 로 별도 확인한다 (원문은 내부용).
"""

import pandas as pd
import streamlit as st

import data
import ui
from auth import require_role

require_role("data")

st.title("감성분석 모델")

reg = data.get_model_registry().copy()
versions = reg.sort_values("model_version_no", ascending=False).model_version.tolist()
gold_version = reg.loc[reg.gold_read, "model_version"].iloc[0]

t_status, t_aspect, t_compare, t_runs = st.tabs(
    ["모델 버전·패치노트", "모델별 리뷰 분석", "버전 비교", "일별 분석 현황"]
)

# ---- 1) 모델 버전·패치노트 -----------------------------------------------
with t_status:
    cur = reg[reg.model_version == gold_version].iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Gold가 읽는 버전", gold_version)
    c2.metric(
        "마지막 분석(KST)",
        data.to_kst(pd.Series([cur.last_analyzed_at])).iloc[0].strftime("%m-%d %H:%M"),
    )
    c3.metric("미점수 후기(현재 버전)", f"{int(cur.unscored_reviews):,}")

    st.subheader("버전 목록")
    view = reg.sort_values("model_version_no", ascending=False).reset_index(drop=True)
    table = pd.DataFrame(
        {
            "모델 버전": view.model_version,
            "버전 번호": view.model_version_no,
            "변경 유형": view.change_type,
            "Gold 읽기": view.gold_read.map({True: "✅", False: ""}),
            "배포일(KST)": data.to_kst(view.deployed_at).dt.strftime("%Y-%m-%d"),
            "분석한 후기 수": view.analyzed_reviews,
            "미점수 후기": view.unscored_reviews.map(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            ),
            "요약": view.summary,
        }
    )
    # 행을 누르면 아래에 그 버전의 패치노트가 나온다. 아무것도 누르지 않았으면 Gold가 읽는 버전을 보여준다.
    event = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="mdl_table",
    )
    st.caption("행을 누르면 패치노트가 나옵니다. 번호가 큰 결과를 Gold가 읽습니다.")
    rows = event.selection.rows
    sel = view.iloc[rows[0]] if rows else view[view.model_version == gold_version].iloc[0]
    older = view[view.model_version_no < sel.model_version_no]
    prev = older.iloc[0] if len(older) else None

    st.subheader(f"패치노트: {sel.model_version} (버전 번호 {sel.model_version_no:.1f})")
    st.markdown(
        f"**{sel.change_type}** · 배포 {data.to_kst(pd.Series([sel.deployed_at])).iloc[0]:%Y-%m-%d}"
        + (" · Gold 읽기 중" if sel.gold_read else "")
    )
    st.write(sel.summary)
    if sel.rescore_required:
        st.warning(
            "이 버전을 올리면 기존 후기가 모두 재점수화 대상이 됩니다(점수 로그에 새 번호가 없음)."
        )

    st.markdown("**바뀐 내용**")
    log = data.get_model_changelog()
    log = log[log.model_version == sel.model_version]
    if log.empty:
        st.info("이 버전의 패치노트가 아직 없습니다.")
    for cat, grp in log.groupby("category", sort=False):
        st.markdown(f"- **{cat}**")
        for _, r in grp.iterrows():
            st.markdown(f"    - {r['item']}: {r.detail}")

    st.markdown(
        "**평가 지표**" + (f" (이전 버전 {prev.model_version} 대비)" if prev is not None else "")
    )
    e1, e2, e3 = st.columns(3)
    for col, name, key, inv in (
        (e1, "F1", "f1", False),
        (e2, "MAE", "mae", True),
        (e3, "QWK", "qwk", False),
    ):
        # MAE 는 낮을수록 좋아서 증가를 빨간색으로 표시한다.
        delta = None if prev is None else f"{sel[key] - prev[key]:+.3f}"
        col.metric(name, f"{sel[key]:.3f}", delta, delta_color="inverse" if inv else "normal")
    st.caption(
        f"평가 세트: {sel.eval_set} ({int(sel.eval_n)}건). 평가 세트가 다른 버전끼리는 직접 비교하지 않습니다. "
        "지표와 패치노트를 어디에 기록해 읽을지는 아직 정해지지 않았습니다(TODO)."
    )

# ---- 2) 모델별 리뷰 분석 ------------------------------------------------
with t_aspect:
    ver = st.selectbox("모델 버전", versions, key="mdl_ver")
    days = ui.pick_period("mdl")
    ui.date_note("review")
    rd = ui.last_days(data.get_model_review_daily(), "review_date", days)
    rd = rd[rd.model_version == ver]
    sc = ui.last_days(data.get_model_score_daily(), "review_date", days)
    sc = sc[sc.model_version == ver]

    total = int(rd.analyzed_review_count.sum())
    zero = int(rd.zero_aspect_review_count.sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("분석한 후기 수", f"{total:,}")
    m2.metric("속성이 0개인 후기", f"{zero:,}")
    m3.metric("속성 0개 비율", ui.pct(zero / total if total else float("nan")))
    st.line_chart(rd.set_index("review_date")[["analyzed_review_count"]])

    st.subheader("속성별 점수")
    sc = sc.assign(weighted=sc.score * sc.review_count)
    g = sc.groupby("aspect", as_index=False)[["review_count", "weighted"]].sum()
    neg = sc[sc.score < 0].groupby("aspect")["review_count"].sum()
    g["mean_score"] = data.safe_div(g.weighted, g.review_count)
    g["neg_rate"] = data.safe_div(g.aspect.map(neg).fillna(0), g.review_count)
    dist = sc.pivot_table(index="aspect", columns="score", values="review_count", aggfunc="sum")
    g = g.merge(dist.add_prefix("점수 ").reset_index(), on="aspect")
    g["aspect"] = pd.Categorical(g.aspect, categories=data.ASPECTS, ordered=True)
    g = g.sort_values("aspect")
    show = g.rename(
        columns={"aspect": "속성", "review_count": "언급 후기 수", "mean_score": "평균 점수"}
    ).assign(**{"부정(<0) 비율": g.neg_rate.map(ui.pct)})
    st.dataframe(
        show.drop(columns=["weighted", "neg_rate"]),
        hide_index=True,
        width="stretch",
        column_config={"평균 점수": st.column_config.NumberColumn(format="%.2f")},
    )
    st.bar_chart(g.set_index("aspect")[["mean_score"]])
    st.caption(
        "점수는 -2~+2, 언급하지 않은 속성은 행이 없습니다. 속성별 언급 후기 수를 합쳐 전체 후기 수로 쓰지 않습니다. "
        "버전을 바꿔 가며 비교하되 서로 다른 버전의 값을 더하지 않습니다."
    )

# ---- 3) 버전 비교 -------------------------------------------------------
with t_compare:
    if len(versions) < 2:
        st.info("비교할 버전이 둘 이상 필요합니다.")
    else:
        ca, cb = st.columns(2)
        va = ca.selectbox("기준 버전(A)", versions[::-1], key="mdl_a")
        vb = cb.selectbox("비교 버전(B)", versions, key="mdl_b")
        if va == vb:
            st.info("서로 다른 버전을 고르세요.")
        else:
            df = data.get_model_score_diff(va, vb).copy()
            df["diff"] = df.score_b - df.score_a
            df["changed"] = df["diff"] != 0
            k1, k2, k3 = st.columns(3)
            k1.metric("비교한 후기 수", f"{df.review_id.nunique():,}")
            k2.metric("점수가 바뀐 속성 비율", ui.pct(df.changed.mean()))
            k3.metric("평균 점수 차(B-A)", f"{df['diff'].mean():+.3f}")

            st.subheader("속성별 변경")
            by = df.groupby("aspect", as_index=False).agg(
                pairs=("changed", "size"), changed=("changed", "sum"), mean_diff=("diff", "mean")
            )
            by["changed_rate"] = data.safe_div(by.changed, by.pairs)
            by["aspect"] = pd.Categorical(by.aspect, categories=data.ASPECTS, ordered=True)
            by = by.sort_values("aspect")
            st.dataframe(
                by.assign(**{"변경 비율": by.changed_rate.map(ui.pct)})
                .rename(
                    columns={
                        "aspect": "속성",
                        "pairs": "비교 쌍",
                        "changed": "변경 수",
                        "mean_diff": "평균 차",
                    }
                )
                .drop(columns="changed_rate"),
                hide_index=True,
                width="stretch",
                column_config={"평균 차": st.column_config.NumberColumn(format="%+.3f")},
            )

            st.subheader("점수 이동표 (행: A 점수, 열: B 점수)")
            st.dataframe(
                pd.crosstab(df.score_a, df.score_b).reindex(
                    index=data.SCORES, columns=data.SCORES, fill_value=0
                ),
                width="stretch",
            )

            st.subheader("점수 차가 큰 후기(|차| ≥ 2)")
            big = df[df["diff"].abs() >= 2].sort_values("diff", key=lambda s: -s.abs()).head(20)
            st.dataframe(
                big[["review_id", "aspect", "score_a", "score_b", "diff"]],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "두 버전이 모두 점수를 낸 (후기, 속성) 쌍만 비교합니다. 한쪽에만 있는 속성은 제외합니다. "
                "후기 원문은 표시하지 않으며 review_id로 별도 확인합니다."
            )

# ---- 4) 일별 분석 현황 ---------------------------------------------------
with t_runs:
    runs = data.get_model_runs().copy()
    runs["finished_at"] = data.to_kst(runs.finished_at)
    last = runs.sort_values("run_date").iloc[-1]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("최근 실행 상태", last.status)
    r2.metric("최근 입력 후기", f"{int(last.input_reviews):,}")
    r3.metric("최근 파싱 실패", f"{int(last.parse_failed):,}")
    r4.metric("미점수 잔량", f"{int(last.unscored_left):,}")
    problem = runs[(runs.status == "FAILED") | (runs.parse_failed > 0)]
    if len(problem):
        st.warning(
            f"실패했거나 파싱 실패가 있었던 실행이 {len(problem)}건 있습니다. 아래 표에서 확인하세요."
        )
    st.dataframe(
        runs.sort_values("run_date", ascending=False)
        .assign(run_date=lambda d: d.run_date.dt.strftime("%Y-%m-%d"))
        .rename(
            columns={
                "run_date": "작성일(KST)",
                "model_version": "모델 버전",
                "status": "상태",
                "input_reviews": "입력 후기",
                "scored_reviews": "점수 후기",
                "zero_aspect_reviews": "속성 0개",
                "parse_failed": "파싱 실패",
                "unscored_left": "미점수 잔량",
                "duration_min": "소요(분)",
                "finished_at": "종료(KST)",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={"소요(분)": st.column_config.NumberColumn(format="%.1f")},
    )
    st.bar_chart(runs.set_index("run_date")[["input_reviews", "parse_failed"]])
    st.caption(
        "입력은 '아직 점수가 없는 후기'만이고, 0건이면 Job을 띄우지 않습니다(SKIPPED_NO_INPUT). "
        "파싱에 실패한 후기는 점수 로그에 넣지 않아 다음 실행에서 다시 시도됩니다. 시각은 KST로 변환했습니다."
    )

st.caption("※ 현재는 더미 데이터입니다. 모델 이름과 수치는 실제 값이 아닙니다.")
