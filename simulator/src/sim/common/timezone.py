"""시뮬레이터가 쓰는 시간대. 업무 시각(가입 시각, 요일·시간대 곡선)은 KST 기준이다."""

from datetime import timedelta, timezone

# 고정 오프셋 (+09:00). zoneinfo는 slim 이미지에 tzdata가 없을 수 있어 쓰지 않는다.
KST = timezone(timedelta(hours=9))
