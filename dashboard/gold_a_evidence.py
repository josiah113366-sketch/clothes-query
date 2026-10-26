"""Read-only evidence for an acknowledged, unpublished funnel snapshot."""

import hashlib
import json
import re

from gold_a_io import GoldAError


class FunnelEvidence:
    def __init__(self, s3, root):
        if not re.fullmatch(r"s3://[a-z0-9.-]+(?:/[A-Za-z0-9_/-]+)?", root.rstrip("/")):
            raise GoldAError("Gold 출력 S3 경로 설정을 확인해 주세요.")
        self.s3, self.root = s3, root.rstrip("/")

    def read(self, uri):
        if not uri.startswith(self.root + "/") or "/../" in uri:
            raise GoldAError("시연 근거가 설정된 데이터 레이크 밖에 있습니다.")
        bucket, key = uri[5:].split("/", 1)
        try:
            return self.s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as error:
            raise GoldAError("퍼널 검증 근거를 읽지 못했습니다. checkpoint·완료 manifest·입력 목록의 S3 읽기 권한을 확인하세요.") from error

    def fixed(self, ref):
        raw = self.read(ref["uri"])
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise GoldAError("시연 근거의 SHA256이 다릅니다.")
        return json.loads(raw)

    def latest(self):
        try:
            state = json.loads(self.read(self.root + "/silver/runtime/clicks/catalog-control/incremental.json"))
            # An owner may be computing a newer batch. Only the acknowledged tip is read.
            if not state.get("tip") or not state.get("athena_query_id"):
                raise GoldAError("Athena 검증을 완료한 퍼널 checkpoint가 없습니다.")
            m = self.fixed(state["tip"])
            run_id = m["run_id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
                raise ValueError()
            base = self.root + "/gold_a/runtime/funnels"
            if state["tip"]["uri"] != base + "/runs/" + run_id + "/manifest.json":
                raise ValueError()
            done = json.loads(self.read(base + "/completed/" + run_id + ".json"))
            if done != m or m["version"] != "funnel-incremental.v1" or m["status"] not in {"PASS", "PARTIAL"}:
                raise ValueError()
            inv = self.fixed(m["inventory"])["objects"]
            identities = {(o["uri"], str(o["etag"]), o["size"]) for o in inv}
            processed = {tuple(p) for p in m["processed"]}
            remaining = m["batch"]["remaining_files"]
            if (len(identities) != len(inv) or len(processed) != len(m["processed"])
                    or not processed <= identities or len(inv) - len(processed) != remaining):
                raise ValueError()
            counts = m["output_counts"]
            expected = {"funnel_daily", "funnel_session_product", "refresh_holds"}
            if set(counts) != expected or any(type(n) is not int or n < 0 for n in counts.values()):
                raise ValueError()
            if any(m["outputs"][t].rstrip("/") != base + "/runs/" + run_id + "/" + t for t in expected):
                raise ValueError()
            if (len(m["held_scopes"]) != counts["refresh_holds"]
                    or (m["status"] == "PASS") != (counts["refresh_holds"] == 0)
                    or (remaining > 0 and (m["status"] != "PARTIAL" or m["coverage_status"] != "BACKFILL_IN_PROGRESS"))):
                raise ValueError()
            return {"run_id": run_id, "completed_at": m["checked_at"],
                    "quality_status": m["status"], "held_scope_count": counts["refresh_holds"],
                    "tables": counts, "scope": f"처리 {len(processed):,}/{len(inv):,}파일 · 미처리 {remaining:,}파일",
                    "source_manifest": state["tip"]["uri"], "verification_query_id": state["athena_query_id"],
                    "coverage_status": m["coverage_status"], "acknowledged_at": "checkpoint 검증 완료; 시각은 manifest 계산 시각",
                    "demo_only": True}
        except GoldAError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise GoldAError("퍼널 checkpoint·완료 기록·입력 범위가 일치하지 않습니다.") from error
