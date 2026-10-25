"""[데이터 관리] 감성분석 모델. **실데이터만** 쓴다 (더미 없음, lemin 2026-10-25).
버전·패치노트·평가 지표: S3 model-registry(MODEL_REGISTRY_URI). 점수 현황: Athena 의 점수 테이블·점수 로그·Silver 리뷰 실행(상품·별점),
실행 요약: S3 staging 의 _summary_scores_*.json. 조회 코드는 model_io.py, 설정은 data.py 의 감성분석 모델 절을 본다.
읽기에 실패하거나 설정이 없으면 그 탭(또는 칸)을 '미연결'로 보여 주고 가짜 숫자를 만들지 않는다.

탭 4개
  1) 모델 버전·패치노트 버전 목록, Gold 가 읽는 버전, 버전을 누르면 바뀐 내용·평가 지표(이전 버전 대비)
  2) 모델별 리뷰 분석 버전 하나를 골라 속성 11개의 언급 수·평균 점수·점수 분포를 본다
  3) 버전 비교      같은 후기·속성의 두 버전 점수를 나란히 비교한다 (점수 차가 큰 후기는 원문도 같이 본다)
  4) 일별 분석 현황  Job 실행별 입력 후기·속성 0개·파싱 실패·소요 시간, 미점수 잔량
읽는 법 (노션·설계 규칙)
  - 모델 버전을 섞어 합산하지 않는다. 화면마다 버전을 하나 고르거나 버전별로 나눠 보여준다.
  - 속성별 언급 수를 합쳐 전체 후기 수로 쓰지 않는다 (후기 하나가 여러 속성을 언급).
  - Gold 는 후기마다 model_version_no 가 가장 큰 결과를 읽는다. 메이저(0.0 -> 1.0)는 평가 모델/로직 변경, 마이너는 작은 수정.
  - 후기 원문은 3탭의 '점수 차가 큰 후기'에서만 보여 준다(어느 버전 판정이 맞는지 사람이 읽고 판단). 원문은 팀 내부용이다.
"""

import logging

import charts
import data
import model_io
import numpy as np
import pandas as pd
import streamlit as st
import ui
from auth import require_role

require_role("data")

st.title("감성분석 모델")


def not_connected(what: str, reason: str) -> None:
    """읽지 못한 곳은 가짜 값을 만들지 않고 회색 '미연결'로 알린다 (파이프라인 흐름 탭과 같은 규칙)."""
    st.info(f"⚪ 미연결 · {what}\n\n{reason}")


def load(what: str, fn, *args):
    """조회 함수를 부르고, 연결 안 됨·실패면 '미연결' 안내를 보이고 None 을 돌려준다."""
    try:
        return fn(*args)
    except data.ModelDataUnavailable as e:
        not_connected(what, str(e))
    except Exception:
        logging.getLogger(__name__).exception("감성분석 모델 조회 실패: %s", what)
        not_connected(what, "조회 중 오류가 났습니다. 대시보드 로그를 확인해 주세요.")
    return None


def num(x, fmt="{:,.0f}"):
    """값이 없으면(NaN·None) '-' 로. 0 과 구분한다."""
    return "-" if x is None or pd.isna(x) else fmt.format(x)


reg = load("모델 레지스트리(버전·패치노트·평가 지표)", data.get_model_registry)
if reg is None:
    st.stop()
reg = reg.copy()
# 분석 현황(점수 로그)은 따로 읽는다. 못 읽으면 해당 칸만 '-' 이고 탭 1 에 사유를 적는다.
status = None
status_err = None
try:
    status = data.get_model_analysis_status()
except data.ModelDataUnavailable as e:
    status_err = str(e)
except Exception:
    logging.getLogger(__name__).exception("감성분석 분석 현황 조회 실패")
    status_err = "조회 중 오류가 났습니다. 대시보드 로그를 확인해 주세요."
for col in ("last_analyzed_at", "analyzed_reviews", "unscored_reviews"):
    reg[col] = pd.NaT if col == "last_analyzed_at" else np.nan
if status is not None:
    st_idx = status.set_index("model_version")
    for col in ("last_analyzed_at", "analyzed_reviews", "unscored_reviews"):
        reg[col] = reg.model_version.map(st_idx[col])
reg["last_analyzed_at"] = pd.to_datetime(reg["last_analyzed_at"], utc=True, errors="coerce")

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
    # 분석 현황(점수 로그)을 못 읽으면 '-' (0 이 아니다). 사유는 아래에 적는다.
    last = data.to_kst(pd.Series([cur.last_analyzed_at])).iloc[0]
    c2.metric("마지막 분석(KST)", "-" if pd.isna(last) else last.strftime("%m-%d %H:%M"))
    c3.metric(
        "미점수 후기(현재 버전)",
        "-" if pd.isna(cur.unscored_reviews) else f"{int(cur.unscored_reviews):,}",
    )

    if status_err:
        not_connected("분석 현황(점수 로그)", status_err)
    elif pd.isna(cur.unscored_reviews):
        st.caption("미점수 후기 수는 최근 Silver 실행을 읽지 못해 '-' 로 표시합니다.")

    st.subheader("버전 목록")
    view = reg.sort_values("model_version_no", ascending=False).reset_index(drop=True)
    table = pd.DataFrame(
        {
            "모델 버전": view.model_version,
            "버전 번호": view.model_version_no,
            "변경 유형": view.change_type,
            "Gold 읽기": view.gold_read.map({True: "✅", False: ""}),
            "배포일(KST)": data.to_kst(view.deployed_at).dt.strftime("%Y-%m-%d"),
            "분석한 후기 수": view.analyzed_reviews.map(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            ),
            "미점수 후기": view.unscored_reviews.map(
                lambda x: "-" if pd.isna(x) else f"{int(x):,}"
            ),
            "요약": view.summary,
            "되돌림 기준": view.based_on.fillna(""),
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
    if isinstance(sel.based_on, str) and sel.based_on:
        # 되돌림(roll-forward): 번호를 올리면서 원래 버전의 가중치·코드를 그대로 다시 배포한 버전
        st.info(
            f"되돌림 버전입니다. {sel.based_on} 의 모델·실행 코드를 그대로 쓰고 번호만 올렸습니다."
        )
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
        if sel[key] is None or pd.isna(sel[key]):
            col.metric(name, "-")  # 패치노트에 평가 지표가 없는 버전
            continue
        delta = (
            None
            if prev is None or prev[key] is None or pd.isna(prev[key])
            else f"{sel[key] - prev[key]:+.3f}"
        )
        col.metric(name, f"{sel[key]:.3f}", delta, delta_color="inverse" if inv else "normal")
    same_set = prev is None or prev.eval_set == sel.eval_set
    st.caption(
        f"평가 세트: {sel.eval_set} ({num(sel.eval_n)}건)."
        + ("" if same_set else " 이전 버전과 평가 세트가 달라 차이는 참고만 하세요.")
        + " 패치노트와 지표의 원본은 review-analysis/releases/ 이고, 모델을 올릴 때 S3 로 배포됩니다."
    )
    if sel.notes:
        st.markdown("**배포 뒤 정정·추가**")
        for n in sel.notes:
            st.markdown(f"- {n['date']}: {n['text']}")

# ---- 2) 모델별 리뷰 분석 ------------------------------------------------
with t_aspect:
    ver = st.selectbox("모델 버전", versions, key="mdl_ver")
    days = ui.pick_period("mdl", max_days=90)
    ui.date_note("review")
    rd = load("작성일별 분석 후기 수(점수 로그)", data.get_model_review_daily, days)
    sc = load("속성별 점수(점수 테이블)", data.get_model_score_daily, days)
    if rd is None or sc is None:
        st.stop()
    rd = rd[rd.model_version == ver]
    sc = sc[sc.model_version == ver]
    if rd.empty:
        st.info("이 기간에 이 버전으로 분석한 후기가 없습니다.")
        st.stop()

    total = int(rd.analyzed_review_count.sum())
    zero = int(rd.zero_aspect_review_count.sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("분석한 후기 수", f"{total:,}")
    m2.metric("속성이 0개인 후기", f"{zero:,}")
    m3.metric("속성 0개 비율", ui.pct(zero / total if total else float("nan")))
    charts.line(
        rd.set_index("review_date")[["analyzed_review_count"]],
        key="mdl_daily",
        labels={"analyzed_review_count": "분석한 후기 수"},
        height="240px",
    )

    st.subheader("속성별 점수")
    sc = sc.assign(weighted=sc.score * sc.review_count)
    g = sc.groupby("aspect", as_index=False)[["review_count", "weighted"]].sum()
    neg = sc[sc.score < 0].groupby("aspect")["review_count"].sum()
    g["mean_score"] = data.safe_div(g.weighted, g.review_count)
    g["neg_rate"] = data.safe_div(g.aspect.map(neg).fillna(0), g.review_count)
    dist = sc.pivot_table(index="aspect", columns="score", values="review_count", aggfunc="sum")
    g = g.merge(dist.add_prefix("점수 ").reset_index(), on="aspect")
    g["aspect"] = pd.Categorical(
        g.aspect, categories=data.model_aspect_categories(g.aspect), ordered=True
    )
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
    # 평균 점수는 -2~+2 라 0 기준 위아래로 뻗는다
    charts.bar(
        g.set_index("aspect")[["mean_score"]],
        key="mdl_aspect",
        labels={"mean_score": "평균 점수"},
        height="280px",
    )
    st.caption(
        "점수는 -2~+2, 언급하지 않은 속성은 행이 없습니다. 속성별 언급 후기 수를 합쳐 전체 후기 수로 쓰지 않습니다. "
        "버전을 바꿔 가며 비교하되 서로 다른 버전의 값을 더하지 않습니다."
    )

    # ---- 후기 목록: 원문 + Gold 가 읽는 최신 속성 점수 -------------------------------
    # 원문은 팀 내부용이다(허용 IP·로그인 뒤에서만 열림). 캡처해 외부로 보내지 않는다.
    # 위의 버전별 집계와 달리 이 목록은 후기마다 번호가 가장 큰 결과(= Gold 가 읽는 값)를 쓴다.
    with ui.panel(
        "후기 목록", f"최근 {days}일 · 최대 {model_io.LIST_LIMIT}건 · Gold 가 읽는 최신 결과"
    ):
        f1, f2, f3 = st.columns([1, 1, 1])
        product = f1.text_input("상품 ID(선택)", key="mdl_list_product").strip()
        aspect = f2.selectbox("속성", ["전체"] + data.MODEL_ASPECTS, key="mdl_list_aspect")
        picked = f3.multiselect(
            "점수(고른 속성이 이 점수인 후기)", data.SCORES, key="mdl_list_scores"
        )
        if picked and aspect == "전체":
            st.caption("속성을 '전체'로 두면 어느 속성이든 고른 점수가 있는 후기를 찾습니다.")
        rl = None
        try:
            rl = data.get_review_list(
                days, product, "" if aspect == "전체" else aspect, tuple(sorted(picked))
            )
        except ValueError as e:  # 상품 ID 형식 등 입력 오류
            st.warning(str(e))
        except data.ModelDataUnavailable as e:
            not_connected("후기 목록(Silver 리뷰 + 점수 뷰)", str(e))
        except Exception:
            logging.getLogger(__name__).exception("후기 목록 조회 실패")
            not_connected(
                "후기 목록(Silver 리뷰 + 점수 뷰)",
                "조회 중 오류가 났습니다. 대시보드 로그를 확인해 주세요.",
            )
        if rl is not None:
            if rl.empty:
                st.info("조건에 맞는 후기가 없습니다. 기간·필터를 바꿔 보세요.")
            else:
                if len(rl) >= model_io.LIST_LIMIT:
                    st.caption(
                        f"최근 작성일 순으로 {model_io.LIST_LIMIT}건까지만 보여 줍니다. 상품·속성·점수로 좁혀 보세요."
                    )
                st.dataframe(
                    rl[
                        [
                            "review_date",
                            "review_id",
                            "product_id",
                            "rating",
                            "review_text",
                            "scores",
                        ]
                    ],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "review_date": st.column_config.DateColumn("작성일", format="YYYY-MM-DD"),
                        "review_id": "후기",
                        "product_id": "상품",
                        "rating": st.column_config.NumberColumn("별점", format="%d"),
                        "review_text": st.column_config.TextColumn("후기 원문", width="large"),
                        "scores": st.column_config.TextColumn("속성별 점수", width="medium"),
                    },
                )
                st.caption(
                    "점수는 -2~+2, 언급하지 않은 속성은 나오지 않습니다. 아직 점수가 없는 후기는 목록에 없습니다. "
                    "후기 원문은 팀 내부용입니다. 캡처해서 외부(메신저 밖, 외부 서비스)로 보내지 않습니다."
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
            cmp_days = ui.pick_period("mdl_cmp", max_days=90)
            df = load("버전 비교(점수 테이블)", data.get_model_score_diff, va, vb, cmp_days)
            if df is None:
                st.stop()
            if df.empty:
                st.info("이 기간에 두 버전이 모두 점수를 낸 (후기, 속성) 쌍이 없습니다.")
                st.stop()
            df = df.copy()
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
            by["aspect"] = pd.Categorical(
                by.aspect, categories=data.model_aspect_categories(by.aspect), ordered=True
            )
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

            # 점수 차가 큰 후기: 원문을 같이 보여 줘 사람이 어느 버전 판정이 맞는지 읽고 판단한다.
            # 원문은 팀 내부용이다 (허용 IP·로그인 뒤에서만 열림). 캡처해 외부로 보내지 않는다.
            # 원문·상품·별점은 최근 Silver 실행에서 읽는다(못 읽으면 원문 칸을 비우고 점수 비교는 그대로 보여 준다).
            # BIG_DIFF_LIMIT: 표에 보여줄 최대 행 수. 차가 큰 순서로 자른다.
            BIG_DIFF_LIMIT = 100
            big = df[df["diff"].abs() >= 2].sort_values("diff", key=lambda s: -s.abs())
            big = big.head(BIG_DIFF_LIMIT)
            meta = None
            if len(big):
                try:
                    meta = data.get_review_meta(tuple(big.review_id.unique()))
                except Exception:
                    logging.getLogger(__name__).exception("후기 메타 조회 실패")
            if meta is None or meta.empty:
                meta = pd.DataFrame(
                    columns=[
                        "review_id",
                        "product_id",
                        "product_name",
                        "category",
                        "rating",
                        "review_text",
                    ]
                )
            big = big.merge(
                meta[["review_id", "product_id", "product_name", "rating", "review_text"]],
                on="review_id",
                how="left",
            )
            with ui.panel(
                "점수 차가 큰 후기(|차| ≥ 2)",
                f"{len(big):,}쌍 · 차가 큰 순 · 최대 {BIG_DIFF_LIMIT}",
            ):
                st.dataframe(
                    big[
                        [
                            "review_id",
                            "review_date",
                            "product_id",
                            "aspect",
                            "score_a",
                            "score_b",
                            "diff",
                            "rating",
                            "review_text",
                        ]
                    ],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "review_id": "후기",
                        "review_date": st.column_config.DateColumn("작성일", format="YYYY-MM-DD"),
                        "product_id": "상품",
                        "aspect": "속성",
                        "score_a": st.column_config.NumberColumn(f"A ({va})", format="%+d"),
                        "score_b": st.column_config.NumberColumn(f"B ({vb})", format="%+d"),
                        "diff": st.column_config.NumberColumn("차(B-A)", format="%+d"),
                        "rating": st.column_config.NumberColumn("별점", format="%d"),
                        "review_text": st.column_config.TextColumn("후기 원문", width="large"),
                    },
                )
                # 한 후기를 골라 모든 속성의 A/B 점수를 나란히 본다
                if len(big):
                    rid = st.selectbox(
                        "후기 자세히 보기", list(big.review_id.unique()), key="mdl_big_rid"
                    )
                    info = meta[meta.review_id == rid]
                    if len(info):
                        i = info.iloc[0]
                        st.markdown(
                            f"**별점 {num(i.rating)}점** · 상품 {i.product_id} ({i.product_name})"
                        )
                        if isinstance(i.review_text, str) and i.review_text:
                            st.info(i.review_text)
                    else:
                        st.caption("이 후기의 상품·별점을 최근 Silver 실행에서 찾지 못했습니다.")
                    one = df[df.review_id == rid].copy()
                    one["aspect"] = pd.Categorical(
                        one.aspect,
                        categories=data.model_aspect_categories(one.aspect),
                        ordered=True,
                    )
                    st.dataframe(
                        one.sort_values("aspect")[["aspect", "score_a", "score_b", "diff"]],
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "aspect": "속성",
                            "score_a": st.column_config.NumberColumn(f"A ({va})", format="%+d"),
                            "score_b": st.column_config.NumberColumn(f"B ({vb})", format="%+d"),
                            "diff": st.column_config.NumberColumn("차(B-A)", format="%+d"),
                        },
                    )
                st.caption(
                    "두 버전이 모두 점수를 낸 (후기, 속성) 쌍만 비교합니다. 한쪽에만 있는 속성은 제외합니다. "
                    "후기 원문은 팀 내부용입니다. 캡처해서 외부(메신저 밖, 외부 서비스)로 보내지 않습니다."
                )

# ---- 4) 일별 분석 현황 ---------------------------------------------------
with t_runs:
    runs = load("Job 실행 요약(S3 _summary_scores_*.json)", data.get_model_runs)
    if runs is None:
        st.stop()
    if runs.empty:
        st.info("아직 Job 실행 요약이 없습니다.")
        st.stop()
    runs = runs.copy()
    runs["analyzed_at"] = data.to_kst(runs.analyzed_at)
    runs = runs.sort_values("analyzed_at", ascending=False).reset_index(drop=True)
    last = runs.iloc[0]
    left = reg.loc[reg.model_version == gold_version, "unscored_reviews"].iloc[0]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("최근 실행(KST)", f"{last.analyzed_at:%m-%d %H:%M}")
    r2.metric("최근 입력 후기", num(last.input_reviews))
    r3.metric("최근 파싱 실패", num(last.parse_failed))
    r4.metric("미점수 잔량", num(left))
    if (runs.parse_failed > 0).any():
        st.warning(
            f"파싱 실패가 있었던 실행이 {int((runs.parse_failed > 0).sum())}건 있습니다. 아래 표에서 확인하세요."
        )
    st.dataframe(
        runs.assign(analyzed_at=lambda d: d.analyzed_at.dt.strftime("%Y-%m-%d %H:%M")).rename(
            columns={
                "analyzed_at": "분석 시각(KST)",
                "model_version": "모델 버전",
                "model_version_no": "버전 번호",
                "input_reviews": "입력 후기",
                "scored_reviews": "점수 후기",
                "zero_aspect_reviews": "속성 0개",
                "parse_failed": "파싱 실패",
                "output_rows": "출력 행",
                "seconds": "소요(초)",
                "per_second": "초당 후기",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "소요(초)": st.column_config.NumberColumn(format="%.0f"),
            "초당 후기": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    chart = runs.assign(label=runs.analyzed_at.dt.strftime("%m-%d %H:%M")).iloc[::-1]
    charts.bar(
        chart.set_index("label")[["input_reviews", "parse_failed"]],
        key="mdl_runs",
        labels={"input_reviews": "입력 후기", "parse_failed": "파싱 실패"},
        height="260px",
    )
    st.caption(
        "Job 한 번이 한 줄이고, 성공한 Job 의 요약 파일(S3)만 나옵니다. 실패한 Job 은 요약이 없어 보이지 않으니 SageMaker·Airflow 에서 확인하세요. "
        "점수 후기 = 입력 − 파싱 실패 − 속성 0개. 파싱에 실패한 후기는 점수 로그에 넣지 않아 다음 실행에서 다시 시도됩니다. "
        "미점수 잔량은 최근 Silver 실행 기준이며 Gold 가 읽는 버전만 계산합니다. 시각은 KST로 변환했습니다."
    )

st.caption(
    "※ 실데이터입니다 (Athena 점수 테이블·점수 로그, S3 모델 레지스트리·실행 요약). 읽지 못한 곳은 '미연결'로 표시합니다."
)
