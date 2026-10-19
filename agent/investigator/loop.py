"""조사 루프: 이상 하나를 받아 모델이 도구를 고르고, 조회 창구가 실행하고, 결과를 모델에 돌려주는 것을 반복해 리포트를 만든다.

바깥 세상과는 함수 두 개로만 만난다 (그래서 가짜 모델·가짜 원장으로 시험할 수 있다)
  converse(system, messages, tool_specs) -> 모델의 다음 메시지 (Bedrock Converse 모양: {"role": "assistant", "content": [블록...]})
  execute(sql) -> 줄 목록(dict)                       (울타리를 통과한 SELECT만 받는다)

에이전트는 읽기만 한다. 재처리 요청·승인 쓰기는 이 루프에 없다.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from guard import GuardError            # noqa: E402
from ledger_tools import TOOL_SPECS, run_tool   # noqa: E402

from prompt import SYSTEM_PROMPT        # noqa: E402
from report import SUBMIT_REPORT_SPEC, build_report, check_report, fallback_report   # noqa: E402

MAX_TURNS = 10          # 모델을 부르는 최대 횟수 (임의 값)
MAX_REVISIONS = 2       # 리포트가 검사에 걸렸을 때 다시 쓰게 하는 최대 횟수 (임의 값)
# 에이전트에게 알려 주는 이상 정보. 정답과 관련된 값은 넣지 않는다.
ANOMALY_FIELDS = ("anomaly_id", "rule_id", "anomaly_type", "source_table", "window_start", "window_end",
                  "scope_type", "scope_key", "metric", "observed_value", "baseline_value", "evidence_ref")


def _result(use_id, payload, error=False):
    return {"toolResult": {"toolUseId": use_id, "status": "error" if error else "success",
                           "content": [{"json": payload if isinstance(payload, dict) else {"rows": payload}}]}}


def investigate(anomaly: dict, converse, execute, dialect="athena", now: datetime = None,
                max_turns=MAX_TURNS, max_revisions=MAX_REVISIONS) -> dict:
    """이상 하나를 조사해 리포트(dict)를 돌려준다. 조사 기록은 리포트의 `trace`에 남긴다."""
    given = {k: anomaly.get(k) for k in ANOMALY_FIELDS if k in anomaly}
    messages = [{"role": "user", "content": [{"text": "이 이상을 조사해서 submit_report로 제출해 줘.\n"
                                              + json.dumps(given, ensure_ascii=False, default=str)}]}]
    tool_specs = TOOL_SPECS + [SUBMIT_REPORT_SPEC]
    called, trace, revisions = set(), [], 0
    for _ in range(max_turns):
        reply = converse(SYSTEM_PROMPT, messages, tool_specs)
        messages.append(reply)
        uses = [b["toolUse"] for b in reply.get("content", []) if "toolUse" in b]
        if not uses:     # 도구를 안 부르고 글만 썼다: 제출하도록 다시 시킨다
            messages.append({"role": "user", "content": [{"text": "조회 도구로 확인한 뒤 submit_report로 제출해 줘."}]})
            continue
        results = []
        for use in uses:
            name, args = use["name"], use.get("input") or {}
            if name == "submit_report":
                problems = check_report(args, called)
                if not problems or revisions >= max_revisions:
                    report = build_report(anomaly.get("anomaly_id"), args, problems)
                    report["trace"] = trace
                    return report
                revisions += 1
                trace.append({"tool": name, "status": "rejected", "problems": problems})
                results.append(_result(use["toolUseId"], {"problems": problems, "hint": "고쳐서 submit_report를 다시 부르세요."}, error=True))
                continue
            try:
                out = run_tool(name, args, execute, dialect=dialect, now=now)
                called.add(name)
                trace.append({"tool": name, "args": args, "status": "ok"})
                results.append(_result(use["toolUseId"], out))
            except (GuardError, KeyError) as e:     # 울타리가 막았거나 필수 인자가 없다: 모델에게 알려 다시 시도하게 한다
                msg = str(e) if isinstance(e, GuardError) else f"필수 인자가 없습니다: {e}"
                trace.append({"tool": name, "args": args, "status": "error", "error": msg})
                results.append(_result(use["toolUseId"], {"error": msg}, error=True))
        messages.append({"role": "user", "content": results})
    report = fallback_report(anomaly.get("anomaly_id"), f"조사 한도({max_turns}회) 안에 결론을 내지 못했습니다.")
    report["trace"] = trace
    return report
