"""여러 화면이 같이 쓰는 선택 위젯과 표시 도우미."""

import pandas as pd
import streamlit as st

import data

# 기간 선택 기본값(일). 화면 성격에 맞게 바꿔도 된다.
DEFAULT_DAYS = 14


def begin_gold_page(*channels):
    """화면을 다시 실행할 때 업무별 완료 실행을 한 번만 선택한다."""
    st.session_state.pop("_gold_a_reader", None)
    st.session_state["_gold_a_channels"] = channels
    if not data.gold_a_real():
        st.warning("Gold A 미리보기: 더미 데이터입니다.")
        return
    for channel in channels:
        run = data.gold_call("run", channel)
        if not run:
            st.info(f"{channel}: 아직 공개된 완료 실행이 없습니다.")
            continue
        st.caption(
            f"{channel} · 실행 {run['run_id']} · 완료 {run['completed_at']} UTC · {run['quality_status']}"
        )
        holds = data.gold_call("holds", channel)
        if not holds.empty:
            st.warning(
                f"{channel}: 갱신 보류 {len(holds)}개. 이전 정상 결과가 유지된 범위와 결과가 없는 범위를 확인하세요."
            )
            with st.expander(f"{channel} 갱신 보류 범위"):
                st.dataframe(holds, hide_index=True, width="stretch")


def has_rows(df):
    if not df.empty:
        return True
    message = {
        "NO_RUN": "아직 공개된 완료 실행이 없습니다.",
        "NOT_REQUESTED": "이 실행에서는 감성분석 결과를 제공하지 않았습니다.",
    }.get(df.attrs.get("state"), "선택한 기간·상품의 결과가 없습니다. 0건으로 판정하지 않습니다.")
    st.info(message)
    return False


def require_rows(df):
    if not has_rows(df):
        st.stop()


def select_model(df, key):
    require_rows(df)
    column = "model_key" if "model_key" in df else "model_version"
    chosen = st.selectbox("모델 버전", sorted(df[column].dropna().unique()), key=key)
    return df[df[column] == chosen]


def pick_period(key: str, max_days: int = 30, default: int = DEFAULT_DAYS) -> int:
    """최근 N일 선택. 더미 데이터가 30일치라 최대 30. 실데이터 연결 후 늘려도 된다."""
    return st.slider("조회 기간(최근 N일)", 3, max_days, default, key=f"days_{key}")


def pick_products(key: str, multi: bool = True) -> list[str]:
    """상품(article_id) 선택. 이름 + article_id 로 보여주고 article_id 목록을 돌려준다.

    상품별 통합 조회는 article_id 기준이다 (노션). product_code 는 '디자인 묶음' 기준이다.
    """
    p = data.product_options()
    labels = {r.article_id: f"{r['name']} ({r.article_id})" for _, r in p.iterrows()}
    if not labels:
        st.info("공개 결과에 조회할 상품이 없습니다.")
        st.stop()
    if multi:
        picked = st.multiselect(
            "상품", list(labels), default=list(labels), format_func=labels.get, key=f"prod_{key}"
        )
    else:
        picked = [st.selectbox("상품", list(labels), format_func=labels.get, key=f"prod_{key}")]
    return picked


def last_days(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """date 컬럼 기준 최근 N일만 남긴다."""
    if data.gold_a_real():
        start = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize() - pd.Timedelta(
            days=days - 1
        )
        return df[df[col] >= start]
    return df[df[col] > df[col].max() - pd.Timedelta(days=days)]


def pct(x: float) -> str:
    """비율 표시. NaN(= 분모 0, 계산 불가)은 0%가 아니라 '계산 불가'로 보여준다."""
    return "계산 불가" if pd.isna(x) else f"{x:.1%}"


def date_note(kind: str) -> None:
    """차트 날짜의 의미를 항상 표시한다 (노션: 판매=결제일, 퍼널=첫 조회일, 리뷰=작성일)."""
    note = {
        "sales": "결제일(KST) 기준",
        "funnel": "첫 조회일(KST) 기준",
        "review": "리뷰 작성일(KST) 기준",
        "hour": "KST 1시간 단위",
    }[kind]
    st.caption(f"📅 날짜 기준: {note}")


def dummy_note() -> None:
    source = "Athena 완료 실행 조회" if data.gold_a_real() else "더미 데이터"
    st.caption(f"※ {source}. 금액은 취소·환불 차감 전 값입니다.")
