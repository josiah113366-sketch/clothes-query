# Spark access preparation and operational policy reconciliation

2026-10-24. Existing operational permissions belong to infra/stacks/spark-access; the basic trade preparation tool is not a replacement deployment.

## Existing applied scope

- Trade: Bronze v2, immutable outputs, magic cleanup, publication and R6 reads. A normal EKS batch and Athena publication succeeded.
- Funnels: click input and Silver/Gold outputs, Driver partition registration. Actual Driver and Executor HeadObject of the formerly failing object returned HTTP 200. Full retry is separate.
- Reviews: raw input/output and frozen scores for both roles. Athena/latest-view/Iceberg source access is Driver-only. Actual Driver SELECT succeeded; full review DAG execution is pending.
- Reprocessing: Driver request/manifest creation and Silver events, detection R6 read. End-to-end recovery remains separate.
- Cleanup: Driver-only pods/configmaps deletecollection was already applied and present in the trade wrapper. It now lives in the shared runtime generator, without duplication.

## Code changes and limits

- Trade tool/example/tests use only the three approved Bronze v2 trade roots.
- Request configuration cannot widen data access: only pipelines/requests/ and its descendants are accepted.
- Existing bindings are preserved; overwrite and identity collisions fail. Shared namespace ownership/quota stays with the platform.
- Base preparation still returns complete_job_policy=false and identifies the operational policy owner. No complete policy is duplicated in workload-access.
- Reviews transition to bronze_v2/reviews/ under the newly confirmed compatible-superset contract. Legacy read access remains until migration verification. No Bronze writes or deletes are added.

## Validation and pending work

Basic trade/runtime regression: 21 tests; full Spark preparation regression: 29 tests passed. CI on 14f20d3 passed all checks. Later review-v2 policy changes require their own plan and verification.

Full funnel/review publication, R6 sequential consumption, partial recovery and same-run dashboard metrics/holds remain end-to-end checks. New rollback run IDs require explicit confirmation; old successful output deletion is not a general grant.
