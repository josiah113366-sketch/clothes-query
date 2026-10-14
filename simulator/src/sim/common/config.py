"""환경 변수 설정. 현재 작업 폴더(simulator/)의 .env를 읽고, 환경 변수가 우선한다."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from sim.member.params import DEFAULT_SEED

DEFAULT_REGION_FILE = "data/region_weights_202609.csv"
DEFAULT_CONNECT_URL = "http://localhost:8083"
DEFAULT_KAFKA_BOOTSTRAP = "localhost:29092"


class ConfigError(RuntimeError):
    """설정이 잘못됐을 때. 메시지에 접속 정보를 담지 않는다."""


@dataclass(frozen=True)
class Config:
    database_url: str = ""
    seed: int = DEFAULT_SEED
    region_file: Path = Path(DEFAULT_REGION_FILE)
    connect_url: str = DEFAULT_CONNECT_URL
    kafka_bootstrap: str = DEFAULT_KAFKA_BOOTSTRAP

    def __repr__(self) -> str:  # 접속 정보가 출력에 섞이지 않게 한다
        return f"Config(seed={self.seed}, region_file={self.region_file.name!r})"


def load_config(
    env: Mapping[str, str] | None = None,
    base_dir: Path | None = None,
    require_database: bool = True,
) -> Config:
    """설정을 읽는다. 상대 경로는 base_dir(기본: 현재 작업 폴더, 즉 simulator/) 기준이다."""
    base = base_dir or Path.cwd()
    if env is None:
        load_dotenv(base / ".env", override=False)
        env = os.environ

    database_url = env.get("DATABASE_URL", "").strip()
    if require_database and not database_url:
        raise ConfigError("DATABASE_URL이 설정되지 않았습니다 (환경 변수 또는 simulator/.env).")

    raw_seed = env.get("SIM_SEED", "").strip()
    try:
        seed = int(raw_seed) if raw_seed else DEFAULT_SEED
    except ValueError:
        raise ConfigError("SIM_SEED는 정수여야 합니다.") from None

    region_file = Path(env.get("SIM_REGION_FILE", "").strip() or DEFAULT_REGION_FILE)
    if not region_file.is_absolute():
        region_file = base / region_file
    return Config(
        database_url=database_url,
        seed=seed,
        region_file=region_file,
        connect_url=env.get("CONNECT_URL", "").strip() or DEFAULT_CONNECT_URL,
        kafka_bootstrap=env.get("KAFKA_BOOTSTRAP", "").strip() or DEFAULT_KAFKA_BOOTSTRAP,
    )
