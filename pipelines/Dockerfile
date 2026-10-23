ARG SPARK_IMAGE=apache/spark:4.2.0
FROM ${SPARK_IMAGE}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_EC2_METADATA_DISABLED=true \
    AWS_DEFAULT_REGION=ap-northeast-1 \
    JAVA_HOME=/opt/java/openjdk \
    SPARK_HOME=/opt/spark \
    PYSPARK_PYTHON=/usr/bin/python3 \
    PYSPARK_DRIVER_PYTHON=/usr/bin/python3 \
    PYTHONPATH=/opt/pipelines \
    PATH=/opt/java/openjdk/bin:/opt/spark/bin:$PATH
WORKDIR /opt/pipelines
COPY pipelines/requirements.txt /opt/pipelines/pipelines/requirements.txt
RUN python3 -m pip install --no-cache-dir -r pipelines/requirements.txt \
    && python3 -c "import sys; assert sys.version_info[:3] == (3, 10, 12), sys.version"
# 팀 기본 이미지의 연결 JAR은 검증 후 재사용한다. 같은 SDK를 새 레이어에 다시 넣지 않는다.
RUN python3 - <<'PYTHON'
import hashlib
from pathlib import Path
from urllib.request import urlopen

jars = Path('/opt/spark/jars')
required = [
    ('org/apache/hadoop', 'hadoop-aws', '3.5.0', '66bd9eefb938b1a1657487324b63c13df2d8b17164a1dd24e0ef37b905bc5baa'),
    ('software/amazon/awssdk', 'bundle', '2.35.4', 'db4b55f24ad1b4e70f17eb1717a4de76a8dadc5a27d764be7c44ff67b2c1c677'),
    ('software/amazon/s3/analyticsaccelerator', 'analyticsaccelerator-s3', '1.3.1', '4959a9747cbb479c73c3ffbcd479bee5b014f8b2880994585a8693fb9d24675e'),
    ('org/wildfly/openssl', 'wildfly-openssl', '2.2.5.Final', '71fb7932f99a727edb23c5a2cb8c6855ac7196fad41aa0669b3998e277165154'),
    ('org/apache/spark', 'spark-hadoop-cloud_2.13', '4.2.0', 'a16b70cb5c0cd9b75726e7435da404d52ee3d64dc5124ffd1f1452d3d494e0d2'),
]
for group, artifact, version, digest in required:
    target = jars / (artifact + '-' + version + '.jar')
    existing = list(jars.glob(artifact + '-[0-9]*.jar'))
    if any(path != target for path in existing):
        raise RuntimeError('JAR version conflict: ' + artifact)
    reused = target.exists()
    if not reused:
        url = 'https://repo.maven.apache.org/maven2/' + '/'.join((group, artifact, version, target.name))
        with urlopen(url, timeout=120) as source, target.open('wb') as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
    with target.open('rb') as source:
        actual = hashlib.sha256()
        while chunk := source.read(1024 * 1024):
            actual.update(chunk)
    if actual.hexdigest() != digest:
        raise RuntimeError('JAR checksum mismatch: ' + target.name)
    # 기존 JAR의 권한을 다시 변경하면 copy-up으로 레이어가 커질 수 있다.
    if not reused:
        target.chmod(0o644)
    print(('Reused: ' if reused else 'Installed: ') + target.name)
PYTHON
COPY pipelines/ /opt/pipelines/pipelines/
COPY docs/contracts/format_rules.yaml /opt/pipelines/docs/contracts/format_rules.yaml
ARG CODE_REF=unknown
ENV PIPELINE_CODE_REF=$CODE_REF
RUN test -n "$CODE_REF" && test "$CODE_REF" != unknown
USER 185:0
ENTRYPOINT ["/opt/entrypoint.sh"]
