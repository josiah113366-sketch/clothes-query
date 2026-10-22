"""원인 리포트 형식(제안)과 검사. 채점 스크립트(agent/eval)가 같은 형식을 읽는다.

리포트 = {report_id, anomaly_id, cause_layer, conclusion, claims: [{text, kind, evidence: [{tool}]}]}
  kind = FACT(확인된 사실: 도구 결과로 확인했고 근거 필수) / ASSUMPTION(추정: 도구로 확인 못 한 해석, 근거는 있으면 적는다)
  같은 시기에 변한 지표는 조사 단서일 뿐 원인으로 단정하지 않는다 -> 단정할 수 없는 것은 ASSUMPTION으로 적는다.
"""
import re
import uuid

LAYERS = ("PAYMENT", "INGEST", "DATA_QUALITY", "UNKNOWN")
KINDS = ("FACT", "ASSUMPTION")

SUBMIT_REPORT_SPEC = {"toolSpec": {
    "name": "submit_report",
    "description": "조사를 끝내고 원인 리포트를 제출한다. 확인된 사실(FACT)에는 이번 조사에서 부른 도구를 evidence로 반드시 붙이고, 도구로 확인하지 못한 해석은 추정(ASSUMPTION)으로 적는다.",
    "inputSchema": {"json": {"type": "object", "required": ["cause_layer", "conclusion", "claims"], "properties": {
        "cause_layer": {"type": "string", "enum": list(LAYERS), "description": "원인 층. 증거가 부족하면 UNKNOWN"},
        "conclusion": {"type": "string", "description": "결론 한두 문장. 재처리가 도움이 될지도 적는다"},
        "claims": {"type": "array", "description": "주장 목록", "items": {"type": "object", "required": ["text", "kind", "evidence"], "properties": {
            "text": {"type": "string"},
            "kind": {"type": "string", "enum": list(KINDS), "description": "FACT=도구 결과로 확인한 사실(근거 필수), ASSUMPTION=확인 못 한 추정"},
            "evidence": {"type": "array", "items": {"type": "object", "required": ["tool"], "properties": {"tool": {"type": "string"}}}}}}}}}},
}}


# 결론·사실 문장이 "~이 없다/정상이다"라고 단정하려면, 그것을 확인하는 도구를 불렀어야 한다 (제안).
# 문장에 (주제 낱말)과 (부정·정상 낱말)이 같이 있으면 걸린다. 낱말 규칙이라 완벽하지 않다: 놓치는 문장도, 필요 없이 걸리는 문장도 있을 수 있다.
# 걸리면 되돌려 보내서 도구를 먼저 부르거나 "확인하지 못했다"로 고치게 한다.
DENIAL_WORDS = ("없", "정상", "아닙니다", "아니다")
DENIAL_RULES = (
    (("오염", "중복"), ("duplicate_success_orders",), "데이터 오염·중복"),
    (("형식", "깨진", "스키마"), ("malformed_summary", "malformed_fields"), "형식 오류"),
    (("지연",), ("bronze_lag",), "적재 지연"),
    (("원장", "적재"), ("ledger_reliability",), "원장·적재 상태"),
)


def unsupported_denials(text: str, called_tools: set) -> list:
    """text 안에서, 확인하는 도구를 부르지 않고 "없다/정상"이라고 쓴 문장 -> [(문장, 필요한 도구 목록, 주제)]"""
    found = []
    for sentence in re.split(r"[.。!?\n]", str(text or "")):
        if not any(w in sentence for w in DENIAL_WORDS):
            continue
        for topics, tools, label in DENIAL_RULES:
            if any(t in sentence for t in topics) and not (set(tools) & called_tools):
                found.append((sentence.strip(), tools, label))
    return found


def check_report(raw: dict, called_tools: set) -> list:
    """고쳐야 할 점 목록. 비어 있으면 통과."""
    problems = []
    if raw.get("cause_layer") not in LAYERS:
        problems.append(f"cause_layer는 {list(LAYERS)} 중 하나여야 합니다.")
    if not str(raw.get("conclusion") or "").strip():
        problems.append("conclusion이 비어 있습니다.")
    claims = raw.get("claims")
    if not isinstance(claims, list) or not claims:
        problems.append("claims가 비어 있습니다. 주장을 하나 이상 적으세요.")
        return problems
    facts = 0
    for i, c in enumerate(claims, 1):
        c = c if isinstance(c, dict) else {}
        kind, evidence = c.get("kind"), c.get("evidence") or []
        if kind not in KINDS:
            problems.append(f"주장 {i}번의 kind는 {list(KINDS)} 중 하나여야 합니다.")
            continue
        if kind == "FACT":
            facts += 1
            if not evidence:
                problems.append(f"주장 {i}번은 확인된 사실(FACT)인데 evidence가 없습니다. 근거 도구를 붙이거나, 확인하지 못했다면 kind를 ASSUMPTION으로 바꾸세요.")
        for e in evidence:
            tool = e.get("tool") if isinstance(e, dict) else None
            if tool not in called_tools:
                problems.append(f"주장 {i}번의 evidence '{tool}'는 이번 조사에서 부르지 않은 도구입니다. 먼저 부르거나 빼세요.")
    texts = [str(raw.get("conclusion") or "")] + [str(c.get("text") or "") for c in claims if isinstance(c, dict) and c.get("kind") == "FACT"]
    seen = set()
    for text in texts:                                         # 확인하지 않은 것을 "없다/정상"이라고 쓴 문장 (추정(ASSUMPTION) 문장은 보지 않는다)
        for sentence, tools, label in unsupported_denials(text, called_tools):
            if sentence not in seen:
                seen.add(sentence)
                problems.append(f"'{sentence}'는 {label}을(를) 확인하는 도구({', '.join(tools)})를 부르지 않고 쓴 단정입니다. 먼저 도구를 부르거나, 확인하지 못했다면 '확인하지 못했다'로 고치세요.")
    if facts == 0 and raw.get("cause_layer") != "UNKNOWN":
        problems.append("확인된 사실(FACT)이 하나도 없습니다. 원인 층을 고르려면 도구로 확인한 사실이 필요합니다. 없다면 cause_layer를 UNKNOWN으로 하세요.")
    return problems


def build_report(anomaly_id, raw: dict, problems=None) -> dict:
    report = {"report_id": "rep-" + uuid.uuid4().hex[:8], "anomaly_id": anomaly_id, "cause_layer": raw.get("cause_layer"),
              "conclusion": raw.get("conclusion"), "claims": raw.get("claims", [])}
    if problems:
        report["problems"] = problems
    return report


def fallback_report(anomaly_id, reason: str) -> dict:
    """한도 안에 결론을 못 냈을 때. 억지로 고르지 않고 UNKNOWN으로 남긴다."""
    return {"report_id": "rep-" + uuid.uuid4().hex[:8], "anomaly_id": anomaly_id, "cause_layer": "UNKNOWN",
            "conclusion": reason, "claims": [], "problems": [reason]}
