"""S3 Sink 확인에 쓰는 설계 수치. 값은 이 파일 한 곳에만 둔다 (커넥터 쪽은 connectors/member-s3-sink.json)."""

from sim.cdc import params as cdc_params

CONNECTOR_NAME = "member-s3-sink"
TOPIC = cdc_params.TOPIC  # source 커넥터가 내보내는 토픽과 같아야 한다
CONSUMER_GROUP = (
    f"connect-{CONNECTOR_NAME}"  # Kafka Connect가 싱크 커넥터에 붙이는 소비자 그룹 이름
)
DEFAULT_CONFIG_PATH = "../connectors/member-s3-sink.json"
SOURCE_CONFIG_PATH = "../connectors/member-source.json"

BUCKET_ENV = "S3_BUCKET"
REGION_ENV = "AWS_REGION"
CREDENTIAL_ENV_NAMES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)  # 이름만 쓴다. 값은 읽어 출력하지 않는다
BUCKET_REFERENCE = "${env:S3_BUCKET}"  # 커넥터 JSON에는 버킷 이름 대신 이 참조만 적는다
REGION_REFERENCE = "${env:AWS_REGION}"

PATH_PREFIX = "bronze"
TOPIC_PREFIX_PATH = f"{PATH_PREFIX}/{TOPIC}/"
# bronze/<토픽>/dt=YYYY-MM-DD/<토픽>+<파티션>+<시작offset>.json (offset은 0으로 채운 숫자일 수 있다)
KEY_PATTERN = (
    rf"{PATH_PREFIX}/{TOPIC}/dt=(?P<dt>\d{{4}}-\d{{2}}-\d{{2}})/"
    rf"{TOPIC}\+(?P<partition>\d+)\+(?P<offset>\d+)\.json"
)
PARTITION_FOLDER_PATTERN = r"dt=\d{4}-\d{2}-\d{2}"

# 커넥터 설정 안전장치
REQUIRED_PARTITIONER_SUFFIX = "TimeBasedPartitioner"
REQUIRED_PATH_FORMAT = "'dt'=YYYY-MM-dd"
REQUIRED_TIMEZONE = "UTC"
REQUIRED_FORMAT_SUFFIX = "format.json.JsonFormat"
FORBIDDEN_CONFIG_KEYS = ("aws.access.key.id", "aws.secret.access.key", "aws.secret.key")
CREDENTIAL_PATTERN = r"AKIA[0-9A-Z]{16}"

# verify
QUIET_SECONDS = 30  # 마지막 파일 이후 이만큼 지나야 "다 썼다"고 본다
SMALL_FILE_BYTES = 10_000  # 이보다 작은 파일이 절반을 넘으면 경고 (통과/실패 아님)
FUTURE_DAYS_ALLOWED = 1  # dt가 오늘(UTC)보다 이만큼 넘게 앞서면 실패

SETUP_WAIT_SECONDS = 60
S3_TIMEOUT_SECONDS = 15
