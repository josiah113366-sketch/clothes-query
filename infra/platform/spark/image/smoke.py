"""Synthetic compute only: no S3, PostgreSQL or Kafka connections/writes."""
import json
import sys
import time

from pyspark.sql import SparkSession


def work(values):
    values = list(values)
    time.sleep(5)
    return iter(x * x for x in values)


spark = SparkSession.builder.appName('infra-spark-synthetic-smoke').getOrCreate()
try:
    assert spark.version == '4.2.0', spark.version
    loader = spark._jvm.java.lang.Thread.currentThread().getContextClassLoader()
    for class_name in [
        'org.apache.hadoop.fs.s3a.S3AFileSystem',
        'software.amazon.awssdk.auth.credentials.ContainerCredentialsProvider',
        'org.postgresql.Driver',
        'org.apache.spark.sql.kafka010.KafkaSourceProvider',
    ]:
        spark._jvm.java.lang.Class.forName(class_name, False, loader)
    print('SMOKE_CONNECTOR_CLASSES_OK', flush=True)
    if '--quick' in sys.argv:
        result = spark.range(1000).count()
        assert result == 1000
    else:
        values = spark.sparkContext.parallelize(range(24), 24).mapPartitions(work).collect()
        assert sum(values) == sum(x*x for x in range(24))
        print('SMOKE_COMPUTE_OK', flush=True)
        # Leave a short idle window to observe Executor removal before stopping Driver.
        time.sleep(45)
    print('SMOKE_SUCCESS ' + json.dumps({'spark': spark.version, 'synthetic_only': True}), flush=True)
finally:
    spark.stop()
