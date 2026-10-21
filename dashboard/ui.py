"""여러 화면이 같이 쓰는 선택 위젯과 표시 도우미."""

import pandas as pd
import streamlit as st

import data

# 기간 선택 기본값(일). 화면 성격에 맞게 바꿔도 된다.
DEFAULT_DAYS = 14


def pick_period(key: str, max_days: int = 30, default: int = DEFAULT_DAYS) -> int:
    """최근 N일 선택. 더미 데이터가 30일치라 최대 30. 실데이터 연결 후 늘려도 된다."""
    return st.slider("조회 기간(최근 N일)", 3, max_days, default, key=f"days_{key}")


def pick_products(key: str, multi: bool = True) -> list[str]:
    """상품(article_id) 선택. 이름 + article_id 로 보여주고 article_id 목록을 돌려준다.

    상품별 통합 조회는 article_id 기준이다 (노션). product_code 는 '디자인 묶음' 기준이다.
    """
    p = data.PRODUCTS
    labels = {r.article_id: f"{r['name']} ({r.article_id})" for _, r in p.iterrows()}
    if multi:
        picked = st.multiselect(
            "상품", list(labels), default=list(labels), format_func=labels.get, key=f"prod_{key}"
        )
    else:
        picked = [st.selectbox("상품", list(labels), format_func=labels.get, key=f"prod_{key}")]
    return picked


def last_days(df: pd.DataFrame, col: str, days: int) -> pd.DataFrame:
    """date 컬럼 기준 최근 N일만 남긴다."""
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
    st.caption("※ 현재는 더미 데이터입니다. 금액은 취소·환불 차감 전 값입니다.")
