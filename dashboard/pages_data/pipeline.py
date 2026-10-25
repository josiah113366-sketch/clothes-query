"""[데이터 관리] 파이프라인 상태. 탭 두 개.

지연·점검 탭 : Gold B bronze_lag_snapshots(+ 신뢰성 점검). 실데이터가 없으면 더미로 대체된다.
데이터 흐름 탭: RDS 부터 Gold 까지 단계별 상태 흐름도. **더미 없음** — 읽는 곳이 없는 단계는 회색 '미연결'.

시나리오 2(트래픽 폭주): 파이프라인이 제때 처리하지 못하고 밀리는가?
읽는 법 (노션): S3 Sink 는 15분마다 파일을 쓰므로 lag_sec 은 정상일 때도 0 ~ 약 900초를 톱니 모양으로 반복한다.
        이 모양이 '평소'다. 톱니 꼭대기가 계속 높아지거나 connector_state 가 RUNNING 이 아니면 이상.
        유입(topic_messages)은 그대로인데 지연만 커졌다면 폭주가 아니라 Bronze 적재 자체의 문제다.
        「토픽별 유입」 그래프가 그 구분을 보여 준다 (토픽마다 조회 구간 중앙값 = 1).
시각은 UTC 로 저장되어 있어 화면에서는 KST 로 바꿔 보여준다.
"""

import pandas as pd
import streamlit as st

import charts
import data
import ui
from auth import require_role

require_role("data")

st.title("파이프라인 상태")

t_lag, t_flow = st.tabs(["지연·점검", "데이터 흐름"])

# 지연 톱니의 '평소' 상한(초). 15분 파일 주기 + 여유. 운영하면서 조정한다. (흐름도 판정도 같은 값: data.FLOW_SINK_LAG_WARN)
NORMAL_MAX_SEC = 900 + 120

with t_lag:
    lag = data.get_bronze_lag(180).copy()
    lag["collected_at_kst"] = data.to_kst(lag.collected_at)

    latest = lag[lag.collected_at == lag.collected_at.max()]
    # 한 토픽에 파티션이 여러 개라(실데이터: 토픽 5개 · 15파티션) 같은 시각·토픽 행이 여러 줄이다.
    # 토픽 단위로 모은다: 지연 초는 가장 느린 파티션(max), 밀린 메시지는 합계(sum),
    # 커넥터 상태는 파티션 값들을 이어 붙인다(전부 RUNNING 이면 "RUNNING" 하나).
    latest_t = (
        latest.groupby("topic")
        .agg(
            lag_sec=("lag_sec", "max"),
            lag_msgs=("lag_msgs", "sum"),
            connector_state=("connector_state", lambda s: ",".join(sorted(set(s.dropna())))),
        )
        .reset_index()
    )
    bad = latest_t[(latest_t.connector_state != "RUNNING") | (latest_t.lag_sec > NORMAL_MAX_SEC)]
    # 1분 추이: 지연은 토픽·파티션 중 최대, 밀린 메시지는 전체 합계
    per_min = lag.groupby("collected_at_kst").agg(
        lag_sec=("lag_sec", "max"), lag_msgs=("lag_msgs", "sum")
    )
    ui.kpis(
        [
            {
                "label": "지연/이상 토픽",
                "value": f"{len(bad)}",
                "unit": f"/ {latest.topic.nunique()}개",
                "color": charts.BAD if len(bad) else charts.GOOD,
                "sub": "평소 범위 초과 또는 RUNNING 아님",
            },
            {
                "label": "최대 지연",
                "value": f"{latest.lag_sec.max():,.0f}",
                "unit": "초",
                "sub": "마지막 측정, 토픽 중 최대",
                "spark": per_min.lag_sec,
            },
            {
                "label": "밀린 메시지",
                "value": f"{int(latest.lag_msgs.sum()):,}",
                "unit": "건",
                "sub": "마지막 측정, 토픽 합계",
                "spark": per_min.lag_msgs,
            },
            {
                "label": "마지막 측정(KST)",
                "value": latest.collected_at_kst.max().strftime("%H:%M"),
                "sub": "1분마다 측정",
            },
        ]
    )
    if len(bad):
        st.warning("평소 범위를 넘었거나 커넥터가 RUNNING 이 아닌 토픽이 있습니다.")
        st.dataframe(
            bad[["topic", "lag_sec", "lag_msgs", "connector_state"]],
            hide_index=True,
            width="stretch",
        )

    with ui.panel("토픽별 Bronze 적재 지연", "1분 측정 · KST · 초"):
        # pivot 대신 pivot_table(max): 같은 시각·토픽에 파티션 행이 여러 개라 가장 느린 파티션 값을 쓴다
        pv = lag.pivot_table(
            index="collected_at_kst", columns="topic", values="lag_sec", aggfunc="max"
        )
        pv = pv[sorted(pv.columns)]  # 토픽 이름 순서 = 색 순서 (고정)
        charts.line(
            pv,
            key="pl_lag",
            fmt="sec",
            area=False,
            threshold=NORMAL_MAX_SEC,
            threshold_label="경고 기준",
            height="340px",
        )
        st.caption(
            f"평소 모양: 0~약 900초 톱니. 점선 경고 기준은 {NORMAL_MAX_SEC}초(코드 NORMAL_MAX_SEC)."
        )

    with ui.panel("토픽별 유입 (평소 대비)", "1분 · KST · 1 = 조회 구간 중앙값"):
        inflow = data.get_topic_inflow(data.INFLOW_MINUTES).copy()
        if inflow.empty:
            st.warning(
                f"최근 {data.INFLOW_MINUTES // 60}시간 동안 원장에 들어온 메시지가 없습니다. 적재 잡이 멈췄는지 확인하세요."
            )
        else:
            inflow["minute_kst"] = data.to_kst(inflow.minute)
            per_topic = inflow.pivot_table(
                index="minute_kst", columns="topic", values="messages", aggfunc="sum"
            ).fillna(0)
            per_topic = per_topic[sorted(per_topic.columns)]  # 토픽 이름 순서 = 색 순서 (지연 그래프와 같게)
            # 토픽마다 크기가 수십~수천 배 달라서(클릭 > 주문 > 결제) 평소(중앙값) 대비 배수로 한 그래프에 그린다
            ratio = (per_topic / per_topic.median().where(lambda m: m > 0)).round(2)
            charts.line(
                ratio,
                key="pl_inflow",
                area=False,
                threshold=1.0,
                threshold_label="평소(중앙값)",
                height="300px",
            )
            last = per_topic.iloc[-1].astype(int)
            st.caption(
                "최근 1분 건수: "
                + ", ".join(f"{topic} {count:,}" for topic, count in last.items())
                + ". 지연과 함께 유입도 늘었으면 폭주, 유입은 그대로인데 지연만 커지면 S3 Sink(Bronze 적재)의 문제입니다."
            )

    with ui.panel("원장 신뢰성 점검"):
        st.dataframe(
            data.get_reliability_checks().assign(checked_at=lambda d: data.to_kst(d.checked_at)),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        "점검에 문제가 나오면 그 시간대의 탐지 결과는 믿지 않고 Gold B부터 고친 뒤 재판정합니다."
    )
    dummy = (
        ["원장 신뢰성 점검"]
        + (["지연 측정"] if "get_bronze_lag" in data.USING_DUMMY else [])
        + (["유입"] if "get_topic_inflow" in data.USING_DUMMY else [])
    )
    st.caption(f"※ 지금 더미 데이터: {', '.join(dummy)}.")


# ---------------------------------------------------------------------
# 데이터 흐름 탭. 더미 없음 (lemin 2026-10-24)
# ---------------------------------------------------------------------
# 단계 목록. x, y = 흐름도 격자 좌표 (x 왼쪽→오른쪽, y 위→아래).
# hint = 미연결일 때 '무엇이 있어야 연결되는지'. data.get_flow_status() 가 값을 주는 단계는 hint 를 쓰지 않는다.
_NEED_ATHENA = (
    "대시보드 Athena 연결 필요 (DASHBOARD_ATHENA_WORKGROUP + 읽기 권한 Pod Identity, TODO F3)"
)
_NEED_SILVER_RUNS = (
    "Silver 완료 기록 표가 거래(silver.silver_runs)만 있음. 이 모듈도 같은 형식의 완료 기록이 필요"
)
STAGES = [
    # 거래 줄: RDS -> CDC -> Kafka -> S3 Sink -> Bronze
    {
        "id": "rds",
        "name": "RDS",
        "x": 0,
        "y": 3.4,
        "hint": _NEED_ATHENA + ". 연결되면 CDC 토픽 유입으로 추정",
    },
    {
        "id": "cdc",
        "name": "CDC",
        "x": 1,
        "y": 3.4,
        "hint": _NEED_ATHENA
        + ". 연결되면 CDC 토픽 유입으로 추정 (커넥터 상태를 직접 보려면 수집기 확장 필요)",
    },
    {"id": "kafka", "name": "Kafka", "x": 2, "y": 3.4, "hint": _NEED_ATHENA},
    {"id": "sink", "name": "S3 Sink v2", "x": 3, "y": 3.4, "hint": _NEED_ATHENA},
    {"id": "bronze", "name": "Bronze", "x": 4, "y": 3.4, "hint": _NEED_ATHENA},
    # Silver (모듈별)
    {"id": "s_mem", "name": "회원", "x": 5.6, "y": 2.9, "hint": _NEED_SILVER_RUNS},
    {"id": "s_trade", "name": "거래", "x": 5.6, "y": 3.9, "hint": _NEED_ATHENA},
    {"id": "s_click", "name": "클릭", "x": 5.6, "y": 4.9, "hint": _NEED_SILVER_RUNS},
    {"id": "s_prod", "name": "상품", "x": 5.6, "y": 1.9, "hint": _NEED_SILVER_RUNS},
    # Gold A (표별. 같은 channel 실행에서 만들어진다)
    {"id": "a_sales", "name": "주문·매출", "x": 7.4, "y": 3.9, "hint": _NEED_ATHENA},
    {"id": "a_prod", "name": "상품 판매", "x": 7.4, "y": 2.9, "hint": _NEED_ATHENA},
    {"id": "a_funnel", "name": "퍼널", "x": 7.4, "y": 4.9, "hint": _NEED_ATHENA},
    {"id": "a_rprod", "name": "리뷰 상품", "x": 7.4, "y": 6.1, "hint": _NEED_ATHENA},
    {"id": "a_raspect", "name": "리뷰 속성", "x": 7.4, "y": 7.1, "hint": _NEED_ATHENA},
    # Gold B (관제용, Kafka 에서 1분마다)
    {"id": "b_ledger", "name": "원장", "x": 3, "y": 0, "hint": _NEED_ATHENA},
    {"id": "b_pay", "name": "결제 원장", "x": 4.5, "y": 0, "hint": _NEED_ATHENA},
    {"id": "b_malformed", "name": "형식 오류", "x": 4.5, "y": 1, "hint": _NEED_ATHENA},
    {"id": "collector", "name": "지연 수집기", "x": 3, "y": 1, "hint": _NEED_ATHENA},
    {
        "id": "anomaly",
        "name": "이상 탐지",
        "x": 6,
        "y": 0.5,
        "hint": "gold_b.anomaly 표 확정 후 연결 (이상 탐지 화면과 같은 데이터)",
    },
    # 리뷰 줄 (Kafka 를 거치지 않고 S3 로 바로 들어온다)
    {
        "id": "r_bronze",
        "name": "Bronze 리뷰",
        "x": 4,
        "y": 6.6,
        "hint": "대시보드 S3 읽기 권한 필요 (bronze_v2/reviews/ 목록)",
    },
    {"id": "r_silver", "name": "Silver 리뷰", "x": 5.6, "y": 6.1, "hint": _NEED_SILVER_RUNS},
    {
        "id": "r_score",
        "name": "감성 점수",
        "x": 5.6,
        "y": 7.1,
        "hint": "점수 로그 review_score_log(Iceberg) 연결 필요 (TODO B6·B7)",
    },
]
EDGES = [
    ("rds", "cdc", 1),
    ("cdc", "kafka", 1),
    ("kafka", "sink", 1),
    ("sink", "bronze", 1),
    ("bronze", "s_mem", 1),
    ("bronze", "s_trade", 1),
    ("bronze", "s_click", 1),
    ("s_trade", "a_sales", 1),
    ("s_trade", "a_prod", 1),
    ("s_prod", "a_prod", 1),
    ("s_click", "a_funnel", 1),
    ("s_prod", "a_funnel", 1),
    ("kafka", "b_ledger", 1),
    ("b_ledger", "b_pay", 1),
    ("b_ledger", "b_malformed", 1),
    ("kafka", "collector", 1),
    ("b_pay", "anomaly", 1),
    ("collector", "anomaly", 1),
    ("r_bronze", "r_silver", 1),
    ("r_silver", "r_score", 1),
    ("r_silver", "a_rprod", 1),
    ("r_score", "a_raspect", 1),
]
GROUPS = [
    {"name": "Gold B · 관제", "x0": 2.55, "y0": -0.55, "x1": 6.45, "y1": 1.4},
    {"name": "Silver", "x0": 5.1, "y0": 1.45, "x1": 6.1, "y1": 7.65},
    {"name": "Gold A", "x0": 6.9, "y0": 2.45, "x1": 7.9, "y1": 7.65},
]
# 문제 구간 표에서 바로 볼 화면
_GO = {
    "sink": "지연·점검 탭",
    "bronze": "지연·점검 탭",
    "kafka": "결제 관제",
    "b_pay": "결제 관제",
    "b_malformed": "형식 오류",
    "anomaly": "이상 탐지",
    "r_score": "감성분석 모델",
}


@st.fragment(run_every=60)
def flow_tab():
    """흐름도 탭. 이 부분만 60초마다 다시 그린다 (지연 수집기 측정 주기와 같다)."""
    head, btn = st.columns([5, 1], vertical_alignment="bottom")
    if btn.button("새로고침", icon=":material/refresh:", width="stretch", key="flow_refresh"):
        data.get_flow_status.clear()  # 캐시(60초)를 비우고 지금 다시 읽는다
    res = data.get_flow_status()
    checked = data.to_kst(pd.Series([res["checked_at"]])).iloc[0]
    head.caption(f"마지막 조회 {checked:%H:%M:%S} KST · 60초마다 자동으로 다시 읽습니다")

    nodes = []
    for s in STAGES:
        status, value, detail = res["stages"].get(s["id"], ("off", "미연결", s["hint"]))
        nodes.append(s | {"status": status, "value": value, "detail": detail})
    count = {k: sum(n["status"] == k for n in nodes) for k in charts.STATUS_LABEL}
    connected = len(nodes) - count["off"]
    ui.kpis(
        [
            {
                "label": "연결된 단계",
                "value": f"{connected}",
                "unit": f"/ {len(nodes)}",
                "color": charts.PALETTE[0],
                "sub": "상태를 읽는 단계",
            },
            {
                "label": "정상",
                "value": f"{count['ok']}",
                "color": charts.GOOD,
                "sub": "평소 주기 안",
            },
            {
                "label": "지연",
                "value": f"{count['warn']}",
                "color": charts.WARN,
                "sub": "평소 주기 초과",
            },
            {
                "label": "멈춤·실패",
                "value": f"{count['bad']}",
                "color": charts.BAD,
                "sub": "커넥터 멈춤, 실행 실패",
            },
            {
                "label": "미연결·확인 불가",
                "value": f"{count['off'] + count['unknown']}",
                "color": charts.STATUS_COLOR["off"],
                "sub": f"미연결 {count['off']} · 확인 불가 {count['unknown']}",
            },
        ]
    )
    with ui.panel(
        "전체 데이터 흐름",
        "원 = 단계 · 테두리 색 = 상태 · 점선 회색 = 미연결 · 마우스를 올리면 세부 값",
    ):
        charts.pipeline_flow(nodes, EDGES, key="pl_flow", groups=GROUPS, height="960px")
        st.caption(
            "초록 정상 · 주황 지연 · 빨강 멈춤·실패 · 회색 확인 불가 · 점선 회색 미연결. "
            "회색 단계로 이어지는 화살표는 점이 흐르지 않습니다 (흐르는지 알 수 없어서)."
        )

    problems = [n for n in nodes if n["status"] in ("warn", "bad", "unknown")]
    if problems:
        with ui.panel("확인할 단계", "지연·멈춤·확인 불가만 모았습니다"):
            st.dataframe(
                pd.DataFrame(
                    {
                        "단계": [n["name"] for n in problems],
                        "상태": [charts.STATUS_LABEL[n["status"]] for n in problems],
                        "값": [n["value"] for n in problems],
                        "설명": [n["detail"].replace("\n", " · ") for n in problems],
                        "볼 화면": [_GO.get(n["id"], "") for n in problems],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
    off = [n for n in nodes if n["status"] == "off"]
    if off:
        with st.expander(f"미연결 단계 {len(off)}개와 연결에 필요한 것"):
            st.dataframe(
                pd.DataFrame(
                    {"단계": [n["name"] for n in off], "필요한 것": [n["hint"] for n in off]}
                ),
                hide_index=True,
                width="stretch",
            )


with t_flow:
    flow_tab()
