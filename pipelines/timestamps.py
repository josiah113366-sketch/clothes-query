"""Python 3.10에서도 1~6자리 ISO 소수초를 손실 없이 파싱한다."""
from __future__ import annotations

import re
from datetime import datetime

_FRACTION = re.compile(r"(\d{2}:\d{2}:\d{2})\.(\d{1,6})(?=(?:[+-]\d{2}:\d{2})?$)")


def parse_iso_datetime(value: str) -> datetime:
    """시간대·허용 정밀도 정책은 호출자가 검사하며 값은 반올림하지 않는다."""
    value = value[:-1] + "+00:00" if value.endswith("Z") else value
    # 3.10 fromisoformat은 소수초 3/6자리만 받는다. 부족한 자리만 0으로 채운다.
    value = _FRACTION.sub(lambda match: match[1] + "." + match[2].ljust(6, "0"), value)
    return datetime.fromisoformat(value)
