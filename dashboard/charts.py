"""화면들이 같이 쓰는 차트 도우미 (Apache ECharts, streamlit-echarts).

st.line_chart / st.bar_chart 를 쓰던 자리를 이 모듈의 함수로 바꿨다.
화면 코드는 지금처럼 "x = index, 계열 = 컬럼" 인 DataFrame 을 넘기면 된다.

  line   : 추이 선 차트. 계열이 하나면 선 아래를 그라데이션으로 칠한다.
  bar    : 막대 (묶음/쌓기/가로)
  flow   : 단계 흐름 그림. 단계 사이 점선을 따라 점이 흘러간다 (구매 퍼널)
  gauge  : 링 게이지 하나 (비율, 지연 초 등)
  rank   : 가로 진행 막대 목록 (PG별 비율처럼 항목 몇 개를 0~최대 사이로 비교)

색
  - 계열 색은 PALETTE 순서대로 붙는다 (컬럼 순서 = 색 순서). 같은 값을 .streamlit/config.toml 의
    chartCategoricalColors 에도 넣어 두었다. 색을 바꾸면 두 곳을 같이 바꾼다.
  - PALETTE 6색은 어두운 배경(#16181d)에서 색약 구분 검사를 통과한 순서다
    (인접 쌍 CVD ΔE ≥ 8, 일반 ΔE ≥ 15, 명도·대비). 순서를 바꾸면 다시 검사한다.
    7번째 계열이 필요하면 색을 늘리지 말고 '기타'로 묶는다.
  - 글자색·배경·글꼴은 theme="streamlit" 으로 Streamlit 테마를 그대로 따른다.

규칙 (대시보드 전체 공통)
  - y 축은 하나만 쓴다. 단위가 다른 두 값은 차트를 나눈다.
  - 계열이 2개 이상이면 범례를 둔다. 1개면 범례 없이 패널 제목이 이름을 맡는다.
  - 마우스를 올리면 그 시점의 값을 보여 준다(tooltip). 점마다 숫자를 적지 않는다.
  - 값이 없는 칸(NaN, 분모 0 = 계산 불가)은 0 으로 그리지 않고 비워 둔다(선이 끊긴다).

key 는 화면 안에서 차트마다 달라야 한다 (같은 key 두 번이면 Streamlit 오류).
"""

import datetime as _dt
import math

import pandas as pd
from streamlit_echarts import JsCode, st_echarts

# 계열 색 (청록, 보라, 초록, 호박, 파랑, 빨강). config.toml chartCategoricalColors 와 같은 값·순서.
PALETTE = ["#1e9bc6", "#8b6cf0", "#1aa874", "#c08400", "#3b82f6", "#e8455f"]
# 상태 색. 계열 색으로 쓰지 않는다 (좋음/주의/나쁨). 항상 글자(▲▼, 상태 이름)와 같이 쓴다.
GOOD, WARN, BAD = "#3ddc97", "#f5a524", "#ff5c74"
# 눈금선·빈 막대·게이지 바탕 같은 옅은 선 색 (패널 배경보다 조금 밝게)
TRACK = "#2a2e36"
MUTED = "#8b9099"

# 차트 기본 높이. 너비는 항상 100%.
DEFAULT_HEIGHT = "320px"
# x 축 점이 이보다 많으면 아래에 확대 막대(dataZoom)를 붙인다 (7일 x 24시간 같은 긴 시계열).
ZOOM_FROM_POINTS = 60
# 막대 최대 두께(px). 막대가 몇 개 없을 때 지나치게 두꺼워지지 않게 한다.
BAR_MAX_WIDTH = 26

# y 값 표시 형식. tooltip 용(_FORMATS)과 축 눈금용(_AXIS_FORMATS, 더 짧게).
#   None : 1,234   "pct" : 0~1 비율 -> 15.3%   "won" : 금액   "sec" : 초
_FORMATS = {
    "pct": "(v) => v == null ? '계산 불가' : (v * 100).toFixed(1) + '%'",
    "won": "(v) => v == null ? '-' : Math.round(v).toLocaleString('ko-KR') + '원'",
    "sec": "(v) => v == null ? '-' : Math.round(v).toLocaleString('ko-KR') + '초'",
    None: "(v) => v == null ? '-' : (Number.isInteger(v) ? v.toLocaleString('ko-KR') "
    ": v.toLocaleString('ko-KR', {maximumFractionDigits: 2}))",
}
_AXIS_FORMATS = {
    "pct": "(v) => Math.round(v * 100) + '%'",
    "won": "(v) => v >= 1e8 ? (v / 1e8).toFixed(1) + '억' : v >= 1e4 ? Math.round(v / 1e4)"
    ".toLocaleString('ko-KR') + '만' : v.toLocaleString('ko-KR')",
    "sec": "(v) => v.toLocaleString('ko-KR') + '초'",
    None: "(v) => v.toLocaleString('ko-KR')",
}


def color(i: int) -> str:
    """i 번째 계열 색. 6개를 넘으면 처음부터 다시 쓰지만, 그런 차트는 만들지 않는다(위 규칙)."""
    return PALETTE[i % len(PALETTE)]


def gradient(hex_color: str, top: float = 0.35) -> dict:
    """위에서 아래로 옅어지는 세로 그라데이션 (선 아래 영역용). top = 맨 위 불투명도."""
    a = f"{round(top * 255):02x}"
    return {
        "type": "linear",
        "x": 0,
        "y": 0,
        "x2": 0,
        "y2": 1,
        "colorStops": [
            {"offset": 0, "color": hex_color + a},
            {"offset": 1, "color": hex_color + "00"},
        ],
    }


def x_labels(index) -> list[str]:
    """x 축 글자. 날짜면 짧게: 하루 단위면 MM-DD, 시각이 있으면 MM-DD HH:mm."""
    is_time = pd.api.types.is_datetime64_any_dtype(index) or (
        len(index) > 0 and all(isinstance(v, _dt.date) for v in index)
    )
    if not is_time:  # 범주(속성 이름, PG 등)나 숫자는 그대로 글자로
        return [str(v) for v in index]
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    daily = bool((idx == idx.normalize()).all())
    return list(idx.strftime("%m-%d" if daily else "%m-%d %H:%M"))


def values(s) -> list:
    """NaN/None 은 null 로 (ECharts 는 빈 칸으로 그림). numpy 숫자는 파이썬 숫자로."""
    out = []
    for v in pd.Series(s).tolist():
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append(None)
        elif isinstance(v, float) and v.is_integer() and abs(v) < 2**53:
            out.append(int(v))
        else:
            out.append(v)
    return out


def _frame(data) -> pd.DataFrame:
    return data.to_frame() if isinstance(data, pd.Series) else data


def _base(df: pd.DataFrame, labels: dict | None, fmt: str | None, pointer: str):
    """line / bar 공통 옵션: tooltip, 범례, 여백, 값 축."""
    names = [str((labels or {}).get(c, c)) for c in df.columns]
    opt = {
        "color": PALETTE,
        "tooltip": {
            "trigger": "axis",
            # line 은 세로 십자선, bar 는 해당 칸 전체를 옅게 칠한다
            "axisPointer": {"type": pointer},
            "valueFormatter": JsCode(_FORMATS[fmt]),
            "confine": True,
        },
        # 범례는 아래에 둔다 (참고 화면과 같은 배치). containLabel: 축 글자가 잘리지 않게
        "grid": {
            "left": 4,
            "right": 12,
            "top": 16,
            "bottom": 30 if len(names) > 1 else 4,
            "containLabel": True,
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {"formatter": JsCode(_AXIS_FORMATS[fmt]), "color": MUTED},
            "splitLine": {"lineStyle": {"color": TRACK}},
        },
    }
    if len(names) > 1:
        opt["legend"] = {
            "bottom": 0,
            "type": "scroll",
            "icon": "roundRect",
            "itemWidth": 14,
            "itemHeight": 4,
            "textStyle": {"color": MUTED},
        }
    return opt, names


def _zoom(opt: dict, n: int) -> None:
    if n > ZOOM_FROM_POINTS:
        opt["dataZoom"] = [
            {"type": "inside"},
            {
                "type": "slider",
                "height": 10,
                "bottom": opt["grid"]["bottom"] - 2,
                "showDetail": False,
                "borderColor": "transparent",
                "backgroundColor": TRACK,
                "fillerColor": GOOD + "55",
                "handleSize": 14,
                "moveHandleSize": 0,
                "dataBackground": {"lineStyle": {"opacity": 0}, "areaStyle": {"opacity": 0}},
            },
        ]
        opt["grid"]["bottom"] += 22


def _cat_axis(labels: list[str], gap: bool) -> dict:
    return {
        "type": "category",
        "data": labels,
        "boundaryGap": gap,
        "axisLabel": {"color": MUTED, "hideOverlap": True},
        "axisLine": {"lineStyle": {"color": TRACK}},
        "axisTick": {"show": False},
    }


def line(
    data,
    *,
    key: str,
    labels: dict | None = None,
    fmt: str | None = None,
    area: bool | None = None,
    dashed: tuple = (),
    threshold: float | None = None,
    threshold_label: str = "기준",
    colors: list[str] | None = None,
    height: str = DEFAULT_HEIGHT,
):
    """선 차트. index = x 축(날짜·시각), 컬럼 = 계열.

    labels   : {컬럼 이름: 화면 이름}. 없으면 컬럼 이름 그대로.
    fmt      : 값 형식 (None / "pct" / "won" / "sec").
    area     : 선 아래 그라데이션. 기본은 계열이 1~2개일 때만 칠한다(많으면 겹쳐 탁해짐).
    dashed   : 점선으로 그릴 컬럼 이름들 (예: '받은 것' 처럼 비교 대상).
    threshold: 점선 가로 기준선 (예: 지연 경고 기준 초). 계열이 아니라 범례에 없다.
    colors   : 계열 색을 직접 줄 때 (필터로 계열 수가 바뀌어도 같은 대상이 같은 색이어야 할 때).
    """
    df = _frame(data)
    opt, names = _base(df, labels, fmt, "line")
    opt["xAxis"] = _cat_axis(x_labels(df.index), gap=False)
    if area is None:
        area = len(df.columns) <= 2
    cols = colors or PALETTE
    opt["color"] = cols
    opt["series"] = []
    for i, (col, name) in enumerate(zip(df.columns, names, strict=True)):
        c = cols[i % len(cols)]
        s = {
            "name": name,
            "type": "line",
            "data": values(df[col]),
            "showSymbol": len(df) <= 20,  # 점이 많으면 동그라미를 숨기고 선만
            "symbolSize": 6,
            "smooth": 0.25,
            "lineStyle": {"width": 2, "color": c, "type": "dashed" if col in dashed else "solid"},
            "itemStyle": {"color": c},
            "emphasis": {"focus": "series"},
            "connectNulls": False,
        }
        if area and col not in dashed:
            s["areaStyle"] = {"color": gradient(c, 0.35 if i == 0 else 0.18)}
        opt["series"].append(s)
    if threshold is not None and opt["series"]:
        opt["series"][0]["markLine"] = {
            "silent": True,
            "symbol": "none",
            "lineStyle": {"type": "dashed", "width": 1, "color": WARN},
            "label": {
                "formatter": f"{threshold_label} {threshold:,.0f}",
                "position": "insideEndTop",
                "color": WARN,
            },
            "data": [{"yAxis": threshold}],
        }
    _zoom(opt, len(df))
    return st_echarts(options=opt, height=height, key=key)


def bar(
    data,
    *,
    key: str,
    labels: dict | None = None,
    fmt: str | None = None,
    stacked: bool = False,
    horizontal: bool = False,
    colors: list[str] | None = None,
    height: str = DEFAULT_HEIGHT,
):
    """막대 차트. index = 막대 묶음, 컬럼 = 계열.

    stacked   : 계열을 쌓는다 (합계가 의미 있을 때만. 예: 사유별 오류 건수).
    horizontal: 가로 막대. 이름이 긴 범주(속성 등)에 쓴다. 위에서부터 index 순서.
    """
    df = _frame(data)
    opt, names = _base(df, labels, fmt, "shadow")
    cat = _cat_axis(x_labels(df.index), gap=True)
    val = opt.pop("yAxis")
    if horizontal:
        cat["inverse"] = True  # 첫 행이 맨 위
        cat["axisLabel"] = {"color": MUTED}
        opt["xAxis"], opt["yAxis"] = val, cat
    else:
        opt["xAxis"], opt["yAxis"] = cat, val
    cols = colors or PALETTE
    opt["color"] = cols
    # 끝만 4px 둥글게. 쌓은 막대는 조각마다 둥글면 어색해서 2px. 조각 사이는 1px 패널색 틈.
    r = 2 if stacked else 4
    radius = [0, r, r, 0] if horizontal else [r, r, 0, 0]
    opt["series"] = [
        {
            "name": name,
            "type": "bar",
            "data": values(df[col]),
            "barMaxWidth": BAR_MAX_WIDTH,
            "itemStyle": {
                "borderRadius": radius,
                "color": cols[i % len(cols)],
                **({"borderWidth": 1, "borderColor": "#16181d"} if stacked else {}),
            },
            "emphasis": {"focus": "series"},
            **({"stack": "total"} if stacked else {}),
        }
        for i, (col, name) in enumerate(zip(df.columns, names, strict=True))
    ]
    _zoom(opt, 0 if horizontal else len(df))
    return st_echarts(options=opt, height=height, key=key)


def flow(
    stages: list[tuple[str, float, str]],
    *,
    key: str,
    notes: list[str] | None = None,
    height: str = "170px",
):
    """단계 흐름 그림. stages = [(단계 이름, 값, 표시 글자), ...] 왼쪽부터.

    단계 사이 점선 위를 점이 흘러가 '방문이 다음 단계로 넘어간다'는 느낌만 준다(장식).
    notes = 단계 사이 글자 (예: '조회의 8.2%'). 길이는 단계 수 - 1.
    점 흐름 속도는 모든 구간이 같다. 값의 크기를 뜻하지 않는다 (값은 아래 숫자로 읽는다).
    """
    n = len(stages)
    xs = [i * 100 for i in range(n)]
    links = [{"coords": [[xs[i] + 14, 0], [xs[i + 1] - 14, 0]]} for i in range(n - 1)]
    opt = {
        "animation": True,
        "grid": {"left": 0, "right": 0, "top": 0, "bottom": 0},
        "xAxis": {"show": False, "min": -45, "max": xs[-1] + 45},
        "yAxis": {"show": False, "min": -1.2, "max": 0.8},
        "series": [
            {
                "type": "lines",
                "coordinateSystem": "cartesian2d",
                "zlevel": 1,
                "silent": True,
                # period: 점 하나가 구간을 지나는 초. trailLength: 꼬리 길이(0~1)
                "effect": {
                    "show": True,
                    "period": 2.5,
                    "trailLength": 0.25,
                    "symbol": "circle",
                    "symbolSize": 5,
                    "color": GOOD,
                },
                "lineStyle": {"color": TRACK, "type": "dashed", "width": 1.5},
                "data": links,
            },
            {
                "type": "scatter",
                "symbolSize": 46,
                "silent": True,
                "itemStyle": {
                    "color": "#1f2229",
                    "borderColor": GOOD + "88",
                    "borderWidth": 1.5,
                    "shadowBlur": 12,
                    "shadowColor": GOOD + "55",
                },
                "label": {
                    "show": True,
                    "position": "bottom",
                    "distance": 10,
                    "formatter": JsCode("(p) => '{v|' + p.data[2] + '}\\n{n|' + p.data[3] + '}'"),
                    "rich": {
                        "v": {
                            "fontSize": 16,
                            "fontWeight": "bold",
                            "color": "#e6e7ea",
                            "padding": [0, 0, 4, 0],
                        },
                        "n": {"fontSize": 12, "color": MUTED},
                    },
                },
                "data": [[xs[i], 0, s[2], s[0]] for i, s in enumerate(stages)],
            },
        ],
    }
    if notes:
        opt["series"].append(
            {
                "type": "scatter",
                "symbolSize": 0,
                "silent": True,
                "label": {
                    "show": True,
                    "formatter": JsCode("(p) => p.data[2]"),
                    "color": MUTED,
                    "fontSize": 11,
                },
                "data": [[(xs[i] + xs[i + 1]) / 2, 0.45, t] for i, t in enumerate(notes)],
            }
        )
    return st_echarts(options=opt, height=height, key=key)


def gauge(
    value: float | None,
    *,
    key: str,
    max_value: float = 1.0,
    fmt: str | None = "pct",
    label: str = "",
    tone: str = GOOD,
    height: str = "190px",
):
    """링 게이지 하나. value 가 None(계산 불가)이면 빈 링과 '계산 불가'를 보여 준다.

    tone: 링 색. 상태를 뜻할 때는 GOOD/WARN/BAD 를 쓰고, 화면 글자로도 상태를 적는다.
    """
    shown = {
        "pct": "(v) => (v * 100).toFixed(1) + '%'",
        "sec": "(v) => Math.round(v).toLocaleString('ko-KR') + '초'",
        None: "(v) => v.toLocaleString('ko-KR')",
    }[fmt]
    opt = {
        "series": [
            {
                "type": "gauge",
                "startAngle": 90,
                "endAngle": -270,
                "min": 0,
                "max": max_value,
                "radius": "88%",
                "pointer": {"show": False},
                "progress": {
                    "show": value is not None,
                    "roundCap": True,
                    "width": 11,
                    "itemStyle": {"color": tone, "shadowBlur": 10, "shadowColor": tone + "66"},
                },
                "axisLine": {"lineStyle": {"width": 11, "color": [[1, TRACK]]}},
                "splitLine": {"show": False},
                "axisTick": {"show": False},
                "axisLabel": {"show": False},
                "title": {"offsetCenter": [0, "32%"], "fontSize": 12, "color": MUTED},
                "detail": {
                    "offsetCenter": [0, "-4%"],
                    "fontSize": 24,
                    "fontWeight": "bold",
                    "color": "#e6e7ea",
                    "formatter": "계산 불가" if value is None else JsCode(shown),
                },
                "data": [{"value": 0 if value is None else min(value, max_value), "name": label}],
            }
        ]
    }
    return st_echarts(options=opt, height=height, key=key)


def rank(
    items: list[tuple[str, float | None, str]],
    *,
    key: str,
    max_value: float = 1.0,
    fmt: str | None = "pct",
    height: str | None = None,
):
    """가로 진행 막대 목록. items = [(이름, 값, 색), ...] 위에서부터.

    막대 뒤에 회색 바탕(최대값까지)을 깔아 '얼마나 찼나'를 보여 준다. 값은 막대 오른쪽에 적는다.
    """
    lab = {
        "pct": "(p) => p.value == null ? '계산 불가' : (p.value * 100).toFixed(1) + '%'",
        None: "(p) => p.value == null ? '-' : p.value.toLocaleString('ko-KR')",
    }[fmt]
    opt = {
        "grid": {"left": 4, "right": 70, "top": 4, "bottom": 4, "containLabel": True},
        "xAxis": {"type": "value", "max": max_value, "show": False},
        "yAxis": {
            "type": "category",
            "inverse": True,
            "data": [i[0] for i in items],
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {"color": "#e6e7ea", "fontSize": 13},
        },
        "tooltip": {
            "trigger": "item",
            "formatter": JsCode(lab.replace("(p) =>", "(p) => p.name + ': ' + (") + ")"),
        },
        "series": [
            {
                "type": "bar",
                "barWidth": 8,
                "showBackground": True,
                "backgroundStyle": {"color": TRACK, "borderRadius": 4},
                "itemStyle": {"borderRadius": 4},
                "label": {
                    "show": True,
                    "position": "right",
                    "fontWeight": "bold",
                    "fontSize": 13,
                    "color": "#e6e7ea",
                    "distance": 10,
                    "formatter": JsCode(lab),
                },
                "data": [
                    {
                        "value": None
                        if v is None or (isinstance(v, float) and math.isnan(v))
                        else v,
                        "itemStyle": {"color": c},
                    }
                    for _, v, c in items
                ],
            }
        ],
    }
    return st_echarts(options=opt, height=height or f"{max(len(items) * 42, 80)}px", key=key)
