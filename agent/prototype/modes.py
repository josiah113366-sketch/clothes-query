"""시연 모드(일상 / 중간 3배 / 폭주 10배)별 탐지 시간 시험.

실행: python3 modes.py
- 규칙 R1: 최근 15분 PG 원인 실패 3건 이상. 가짜 데이터 30회 반복.
- 판정 주기는 5분(팀 제안)과 1분(참고) 두 가지로 잰다.
- 사건 1 = PG 장애, 사건 2 = 소비 지연(프로토타입에서는 평소의 20배 유입 급증), 사건 3 = 스키마 오염.
"""
from evaluate_v3 import score
from ledger_v3 import generate_ledger

MODES = (("일상", 900), ("중간 3배", 2700), ("폭주 10배", 9000))
STEPS = (5, 1)
NAMES = {"INC-001": "사건1 PG 장애", "INC-002": "사건2 소비 지연", "INC-003": "사건3 스키마 오염"}


def run(vol, step, seeds=range(30)):
    times = {k: [] for k in NAMES}
    hits = {k: 0 for k in NAMES}
    false_alarms = 0
    for s in seeds:
        h, lag, fp = score(generate_ledger(s, vol), r1_k=3, r1_win=15, step=step)
        for k in NAMES:
            hits[k] += h.get(k, 0)
            times[k].extend([lag[k]] if lag.get(k) is not None and k in lag else [])
        false_alarms += len(fp)
    return times, hits, false_alarms / len(seeds)


if __name__ == "__main__":
    for step in STEPS:
        print(f"\n[판정 {step}분마다] 걸린 시간(분) 평균 / 최대, 탐지 횟수(30회 중), 오탐(하루당)")
        for name, vol in MODES:
            times, hits, fp = run(vol, step)
            cells = []
            for k, label in NAMES.items():
                t = times[k]
                cells.append(f"{label} {sum(t) / len(t):.0f}/{max(t)} ({hits[k]}/30)" if t else f"{label} -")
            print(f"{name:<8}{vol:>5}건/일  " + "  |  ".join(cells) + f"  |  오탐 {fp:.2f}")
