"""시연 모드별 탐지 시간·오탐 시험 (시뮬레이터 확률표 2026-10-16 기준).

실행: python3 modes.py
- 규칙 R1: 최근 15분 PG 원인 실패 3건 이상. 판정은 5분마다. 가짜 데이터 30회 반복.
- 주문 속도는 확률표의 분당 주문을 하루로 환산(x1440)해 넣는다. 이 프로토타입은 하루 내내 같은 속도라고 가정한다.
- 평소 PG 원인 실패율(시도당)을 0과 1.15%(확률표 값) 두 가지로 잰다.
  0이면 평소 PG 원인 실패가 없다고 본 옛 가정이고, 1.15%는 확률표가 정한 평소 값이다.
- R1을 두 가지로 잰다: (가) 고정 "3건 이상", (나) "3건 이상 + 그 PG 결제 시도 중 PG 원인 실패 비율 20% 이상"(제안).
- 사건 1 = PG 장애, 사건 2 = 소비 지연(프로토타입에서는 평소의 20배 유입 급증), 사건 3 = 스키마 오염.
"""
from evaluate_v3 import score
from ledger_v3 import generate_ledger

MODES = (("일상 새벽(분당 0.7건)", 1008), ("일상 하루평균(5,000건/일)", 5000), ("일상 저녁 피크(분당 6.3건)", 9072),
         ("중간(분당 19건)", 27360), ("폭주(분당 63건)", 90720))
VARIANTS = (("평소 PG 실패 0, 고정 3건", 0.0, 0.0), ("평소 PG 실패 1.15%, 고정 3건", 0.0115, 0.0),
            ("평소 PG 실패 1.15%, 3건 + 비율 20% (제안)", 0.0115, 0.2))
NAMES = {"INC-001": "사건1 PG 장애", "INC-002": "사건2 소비 지연", "INC-003": "사건3 스키마 오염"}


def run(vol, base_rate, rate=0.0, k=3, step=5, seeds=range(30)):
    times = {key: [] for key in NAMES}
    hits = {key: 0 for key in NAMES}
    false_alarms = 0
    for s in seeds:
        h, lag, fp = score(generate_ledger(s, vol, pg_base_rate=base_rate), r1_k=k, r1_rate=rate, r1_win=15, step=step)
        for key in NAMES:
            hits[key] += h.get(key, 0)
            if lag.get(key) is not None:
                times[key].append(lag[key])
        false_alarms += len(fp)
    return times, hits, false_alarms / len(seeds)


if __name__ == "__main__":
    for title, base, rate in VARIANTS:
        print(f"\n[{title}, 판정 5분마다] 걸린 시간(분) 평균/최대 (30회 중 탐지 횟수), 오탐(하루당)")
        for name, vol in MODES:
            times, hits, fp = run(vol, base, rate)
            cells = []
            for key, label in NAMES.items():
                t = times[key]
                cells.append(f"{label} {sum(t) / len(t):.0f}/{max(t)} ({hits[key]}/30)" if t else f"{label} -")
            print(f"{name:<26}" + " | ".join(cells) + f" | 오탐 {fp:.2f}")
