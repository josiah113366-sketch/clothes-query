"""컨트롤러 핵심 (HTTP 없이 테스트한다).

순서 규칙:
1. 시작: 검증 → 시작 기록(실패하면 아무것도 바꾸지 않는다) → 바꾸기.
   바꾸기가 실패하면 ended_by="failed" 끝 기록을 최선을 다해 남기고 오류를 올린다.
2. 끝: 되돌리기(제어 파일) → 끝 기록. 끝 기록이 실패하면 다음 tick()에서 다시 쓴다.
3. 잠금 하나로 동시에 두 요청이 상태를 바꾸지 않게 한다.
4. 사건은 한 번에 하나다 (OPERATOR_PAUSE는 예외). 시각은 벽시계(UTC)만 쓴다.
"""

import math
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from sim.common.control import MODES
from sim.common.db import SafeDatabaseError
from sim.controller.control_writer import ControlWriter
from sim.controller.log import IncidentLog, IncidentLogError
from sim.controller.model import (
    DATA_POLLUTION,
    DEFAULT_BURST_MINUTES,
    DEFAULT_MEDIUM_MINUTES,
    DEFAULT_PG_EXTRA_FAIL,
    DEFAULT_PG_OUTAGE_MINUTES,
    DEFAULT_POLLUTION_COUNT,
    DEFAULT_SINK_PAUSE_MINUTES,
    END,
    MAX_PG_OUTAGE_MINUTES,
    MAX_POLLUTION_COUNT,
    MAX_SINK_PAUSE_MINUTES,
    MODE_INCIDENTS,
    OPERATOR_PAUSE,
    PG_OUTAGE,
    PGS,
    POLLUTION_KINDS,
    SCHEMA_VERSION,
    SINK_CONNECTORS,
    SINK_PAUSE,
    START,
    Incident,
    utc_text,
)
from sim.controller.pollution import PollutionError, PollutionExecutor


class ControllerError(RuntimeError):
    """메시지에 접속 정보, 버킷, 행 내용을 싣지 않는다."""


class InvalidRequestError(ControllerError):
    """잘못된 값 (HTTP 400)."""


class IncidentActiveError(ControllerError):
    """다른 사건이 진행 중이다 (HTTP 409)."""


class UnavailableError(ControllerError):
    """이 기능을 쓸 수 없다. 예: DATABASE_URL이 없어 오염을 못 한다 (HTTP 503)."""


class ApplyError(ControllerError):
    """시작 기록은 남겼지만 바꾸기가 실패했다 (HTTP 503)."""


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidRequestError(f"{name}은(는) 숫자여야 합니다.")
    return float(value)


class ControllerService:
    def __init__(
        self,
        control_writer: ControlWriter,
        incident_log: IncidentLog,
        pollution: PollutionExecutor | None,
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
        medium_minutes: float = DEFAULT_MEDIUM_MINUTES,
        burst_minutes: float = DEFAULT_BURST_MINUTES,
    ) -> None:
        if medium_minutes <= 0 or burst_minutes <= 0:
            raise ValueError("자동 복귀 시간은 0보다 커야 합니다.")
        self._writer = control_writer
        self._log = incident_log
        self._pollution = pollution
        self._clock = clock
        self._new_id = new_id
        self._return_minutes = {"medium": medium_minutes, "burst": burst_minutes}
        self._lock = threading.RLock()
        self.mode = "normal"
        self.running = True
        self.pg_extra_fail: dict[str, float] = {}
        self.active: Incident | None = None  # 모드 사건 또는 PG 장애
        self.pause: Incident | None = None  # OPERATOR_PAUSE
        self.pending_ends: list[dict] = []  # 쓰지 못한 끝 기록 (tick에서 다시 쓴다)
        self.last_error: str | None = None

    # --- 시작과 상태 ---

    def start(self) -> None:
        """깨끗한 상태(normal, running, 장애 없음)로 제어 파일을 쓴다. 서버를 켤 때 부른다."""
        with self._lock:
            self._write_control()

    def status(self) -> dict:
        """운영자용. 정답표 내용(result)은 싣지 않고 사건 종류와 시각만 보여 준다."""
        with self._lock:

            def brief(incident: Incident | None) -> dict | None:
                if incident is None:
                    return None
                return {
                    "type": incident.type,
                    "started_at": utc_text(incident.started_at),
                    "ends_at": utc_text(incident.ends_at) if incident.ends_at else None,
                }

            return {
                "mode": self.mode,
                "running": self.running,
                "pg_extra_fail": dict(self.pg_extra_fail),
                "active": brief(self.active),
                "pause": brief(self.pause),
                "pending_end_records": len(self.pending_ends),
                "last_error": self.last_error,
            }

    # --- 요청 ---

    def set_mode(self, mode: object) -> dict:
        if mode not in MODES:
            raise InvalidRequestError(f"mode는 {', '.join(MODES)} 중 하나여야 합니다.")
        with self._lock:
            if mode == self.mode:
                return self.status()
            if mode == "normal":
                if self.active is not None and self.active.type in MODE_INCIDENTS.values():
                    self._end(self.active, "manual")
                return self.status()
            self._require_no_active()
            minutes = self._return_minutes[str(mode)]
            now = self._clock()
            incident = Incident(
                self._new_id(),
                MODE_INCIDENTS[str(mode)],
                now,
                now + timedelta(minutes=minutes),
                {"mode": mode, "planned_minutes": minutes},
            )
            self._start(incident, mode=str(mode))
            return self.status()

    def set_running(self, running: object) -> dict:
        if not isinstance(running, bool):
            raise InvalidRequestError("running은 true/false여야 합니다.")
        with self._lock:
            if running == self.running:
                return self.status()
            if not running:
                incident = Incident(self._new_id(), OPERATOR_PAUSE, self._clock(), None, {})
                self._start(incident, running=False)
            elif self.pause is not None:
                self._end(self.pause, "manual")
            return self.status()

    def start_pg_outage(
        self,
        pg: object,
        extra_fail: object = DEFAULT_PG_EXTRA_FAIL,
        minutes: object = DEFAULT_PG_OUTAGE_MINUTES,
    ) -> dict:
        if pg not in PGS:
            raise InvalidRequestError(f"pg는 {', '.join(PGS)} 중 하나여야 합니다.")
        extra = _number(extra_fail, "extra_fail")
        span = _number(minutes, "minutes")
        if not 0 < extra <= 1:
            raise InvalidRequestError("extra_fail은 0보다 크고 1 이하여야 합니다.")
        if not 0 < span <= MAX_PG_OUTAGE_MINUTES:
            raise InvalidRequestError(
                f"minutes는 0보다 크고 {MAX_PG_OUTAGE_MINUTES} 이하여야 합니다."
            )
        with self._lock:
            self._require_no_active()
            now = self._clock()
            incident = Incident(
                self._new_id(),
                PG_OUTAGE,
                now,
                now + timedelta(minutes=span),
                {"pg": pg, "extra_fail": extra, "planned_minutes": span},
            )
            self._start(incident, pg_extra_fail={str(pg): extra})
            return self.status()

    def start_data_pollution(self, kind: object, count: object = DEFAULT_POLLUTION_COUNT) -> dict:
        if kind not in POLLUTION_KINDS:
            raise InvalidRequestError(f"kind는 {', '.join(POLLUTION_KINDS)} 중 하나여야 합니다.")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= MAX_POLLUTION_COUNT
        ):
            raise InvalidRequestError(
                f"count는 1 이상 {MAX_POLLUTION_COUNT} 이하의 정수여야 합니다."
            )
        if self._pollution is None:
            raise UnavailableError("DATABASE_URL이 없어 데이터 오염을 쓸 수 없습니다.")
        with self._lock:
            self._require_no_active()
            try:
                available = self._pollution.check(str(kind), count)  # 기록하기 전에 읽기만
            except PollutionError as error:
                raise InvalidRequestError(str(error)) from None
            incident = Incident(
                self._new_id(),
                DATA_POLLUTION,
                self._clock(),
                None,
                {"kind": kind, "requested_count": count, "available_count": available},
            )
            self._log.write(self._record(START, incident))  # 실패하면 아무것도 바꾸지 않는다
            try:
                result = self._pollution.apply(str(kind), count, incident.incident_id)
            except (PollutionError, SafeDatabaseError) as error:
                self._end_record_best_effort(incident, "failed", {})
                self.last_error = f"데이터 오염 적용 실패 ({type(error).__name__})"
                raise ApplyError(self.last_error) from None
            summary = {
                "kind": result.kind,
                "affected_count": result.affected_count,
                "order_ids": list(result.order_ids),
            }
            self._write_end_or_queue(self._record(END, incident, "complete", summary))
            return self.status()

    def start_sink_pause(
        self,
        connector: object = SINK_CONNECTORS[0],
        minutes: object = DEFAULT_SINK_PAUSE_MINUTES,
    ) -> dict:
        """정답표만 남긴다. 사람이 이 뒤에 kubectl로 멈추고, 재개를 확인한 뒤 end_active()."""
        if connector not in SINK_CONNECTORS:
            raise InvalidRequestError(
                f"connector는 {', '.join(SINK_CONNECTORS)} 중 하나여야 합니다."
            )
        span = _number(minutes, "minutes")
        if not 0 < span <= MAX_SINK_PAUSE_MINUTES:
            raise InvalidRequestError(
                f"minutes는 0보다 크고 {MAX_SINK_PAUSE_MINUTES} 이하여야 합니다."
            )
        with self._lock:
            self._require_no_active()
            incident = Incident(
                self._new_id(),
                SINK_PAUSE,
                self._clock(),
                None,  # 자동 종료하면 실제 재개 시각과 정답표가 어긋난다
                {"connector": connector, "planned_minutes": span},
            )
            self._log.write(self._record(START, incident))  # 실패하면 아무것도 바꾸지 않는다
            self.active = incident
            self.last_error = None
            return self.status()

    def end_active(self, reason: str = "manual") -> dict:
        with self._lock:
            if self.active is None:
                raise InvalidRequestError("진행 중인 사건이 없습니다.")
            self._end(self.active, reason)
            return self.status()

    def tick(self) -> None:
        """1초마다 부른다. 쓰지 못한 끝 기록을 다시 쓰고, 시간이 된 사건을 끝낸다."""
        with self._lock:
            self._retry_pending_ends()
            due = self.active.ends_at if self.active is not None else None
            if self.active is not None and due is not None and self._clock() >= due:
                try:
                    self._end(self.active, "timer")
                except ControllerError:
                    pass  # 되돌리기 실패는 last_error에 남았다. 다음 tick에서 다시 한다

    def shutdown(self) -> None:
        """진행 중 사건을 shutdown으로 끝내고 제어 파일을 normal, 장애 없음으로 되돌린다."""
        with self._lock:
            for incident in (self.active, self.pause):
                if incident is not None:
                    try:
                        self._end(incident, "shutdown")
                    except ControllerError:
                        pass
            self.mode, self.running, self.pg_extra_fail = "normal", True, {}
            self.active = self.pause = None
            try:
                self._write_control()
            except OSError:
                self.last_error = "종료 중 제어 파일을 되돌리지 못했습니다."
            self._retry_pending_ends()

    # --- 내부 ---

    def _require_no_active(self) -> None:
        if self.active is not None:
            raise IncidentActiveError(
                f"진행 중인 사건이 있습니다 ({self.active.type}). 끝난 뒤 다시 시도하세요."
            )

    def _write_control(self) -> None:
        self._writer.write(self.running, self.mode, self.pg_extra_fail)

    def _record(
        self,
        phase: str,
        incident: Incident,
        ended_by: str | None = None,
        result: dict | None = None,
    ) -> dict:
        record: dict = {
            "schema_version": SCHEMA_VERSION,
            "incident_id": incident.incident_id,
            "phase": phase,
            "type": incident.type,
            "at": utc_text(self._clock() if phase == END else incident.started_at),
        }
        if phase == START:
            record["params"] = dict(incident.params)
        else:
            record["ended_by"] = ended_by
            record["result"] = result or {}
        return record

    def _start(
        self,
        incident: Incident,
        *,
        mode: str | None = None,
        running: bool | None = None,
        pg_extra_fail: Mapping[str, float] | None = None,
    ) -> None:
        self._log.write(self._record(START, incident))  # IncidentLogError면 아무것도 안 바꾼다
        before = (self.mode, self.running, dict(self.pg_extra_fail))
        if mode is not None:
            self.mode = mode
        if running is not None:
            self.running = running
        if pg_extra_fail is not None:
            self.pg_extra_fail = dict(pg_extra_fail)
        try:
            self._write_control()
        except OSError as error:
            self.mode, self.running, self.pg_extra_fail = before
            self._end_record_best_effort(incident, "failed", {})
            self.last_error = f"제어 파일을 쓰지 못했습니다 ({type(error).__name__})"
            raise ApplyError(self.last_error) from None
        if incident.type == OPERATOR_PAUSE:
            self.pause = incident
        else:
            self.active = incident
        self.last_error = None

    def _end(self, incident: Incident, ended_by: str) -> None:
        if incident.type == SINK_PAUSE:  # 제어 파일로 바꾼 것이 없다. 끝 기록만
            self.active = None
            self._write_end_or_queue(self._record(END, incident, ended_by))
            return
        before = (self.mode, self.running, dict(self.pg_extra_fail))
        if incident.type == OPERATOR_PAUSE:
            self.running = True
        elif incident.type == PG_OUTAGE:
            self.pg_extra_fail = {}
        else:  # 모드 사건
            self.mode = "normal"
        try:
            self._write_control()  # 되돌리기 먼저
        except OSError as error:
            self.mode, self.running, self.pg_extra_fail = before
            self.last_error = f"제어 파일을 되돌리지 못했습니다 ({type(error).__name__})"
            raise ApplyError(self.last_error) from None
        if incident is self.pause:
            self.pause = None
        if incident is self.active:
            self.active = None
        self._write_end_or_queue(self._record(END, incident, ended_by))

    def _write_end_or_queue(self, record: dict) -> None:
        try:
            self._log.write(record)
        except IncidentLogError:
            self.pending_ends.append(record)
            self.last_error = "끝 기록을 쓰지 못했습니다. 잠시 뒤 다시 씁니다."

    def _end_record_best_effort(self, incident: Incident, ended_by: str, result: dict) -> None:
        self._write_end_or_queue(self._record(END, incident, ended_by, result))

    def _retry_pending_ends(self) -> None:
        still: list[dict] = []
        for record in self.pending_ends:
            try:
                self._log.write(record)
            except IncidentLogError:
                still.append(record)
        if self.pending_ends and not still:
            self.last_error = None
        self.pending_ends = still
