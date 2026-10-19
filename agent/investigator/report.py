"""원인 리포트 형식(제안)과 검사. 채점 스크립트(agent/eval)가 같은 형식을 읽는다.

리포트 = {report_id, anomaly_id, cause_layer, conclusion, claims: [{text, evidence: [{tool}]}]}
"""
import uuid

LAYERS = ("PAYMENT", "INGEST", "DATA_QUALITY", "UNKNOWN")

SUBMIT_REPORT_SPEC = {"toolSpec": {
    "name": "submit_report",
    "description": "조사를 끝내고 원인 리포트를 제출한다. claims의 모든 주장에 이번 조사에서 부른 도구를 evidence로 붙여야 한다.",
    "inputSchema": {"json": {"type": "object", "required": ["cause_layer", "conclusion", "claims"], "properties": {
        "cause_layer": {"type": "string", "enum": list(LAYERS), "description": "원인 층. 증거가 부족하면 UNKNOWN"},
        "conclusion": {"type": "string", "description": "결론 한두 문장. 재처리가 도움이 될지도 적는다"},
        "claims": {"type": "array", "description": "주장 목록", "items": {"type": "object", "required": ["text", "evidence"], "properties": {
            "text": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object", "required": ["tool"], "properties": {"tool": {"type": "string"}}}}}}}}}},
}}


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
    for i, c in enumerate(claims, 1):
        evidence = c.get("evidence") if isinstance(c, dict) else None
        if not evidence:
            problems.append(f"주장 {i}번에 evidence가 없습니다. 근거 도구를 붙이거나 그 주장을 빼세요.")
            continue
        for e in evidence:
            tool = e.get("tool") if isinstance(e, dict) else None
            if tool not in called_tools:
                problems.append(f"주장 {i}번의 evidence '{tool}'는 이번 조사에서 부르지 않은 도구입니다. 먼저 부르거나 빼세요.")
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
