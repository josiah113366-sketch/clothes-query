# Funnel incremental infrastructure connection

2026-10-25: prepared against main `55b3591` (PR #125).

## Applied access

Only `clothes-query-dev-silver-gold-a-driver` receives the new inline policy
`funnel-incremental-control`:

- `s3:PutObject`: `s3://clothes-query-datalake/pipelines/requests/funnels-incremental/*`
- `glue:GetPartitions`: `gold_a.refresh_holds_runs` and its catalog/database ancestors

Existing Driver and Executor policies are retained. Executor does not receive these
control operations. Neither role gains ground-truth access.

## Airflow runtime

`airflow/airflow-silver-gold-a-runtime`, JSON key `config`:

```json
{
  "funnel_athena_workgroup": "clothes-query-dev-athena-review-score",
  "funnel_athena_output": "s3://clothes-query-datalake/athena-results/review-score/"
}
```

These keys extend the existing JSON; do not replace its image, identities, or other
settings. `prepare_trade_runtime.py --trade-publication` supplies these defaults.
Both can be overridden together with `--funnel-athena-workgroup` and
`--funnel-athena-output`. A new Athena workgroup is not created.

## Validation and remaining execution

- Terraform validate passed; reviewed plan added exactly one inline policy.
- Apply completed; subsequent full plan reported no changes.
- IAM simulations allowed both operations for Driver and denied them for Executor.
- Ground-truth writes remained denied for both roles.
- Runtime/resource regression tests: 19 passed.
- Existing image digest was preserved. No funnel/Spark run was triggered here.

The workload owner must supply a new immutable image containing PR #125's
incremental modules before testing one bounded batch. Infrastructure authorization
checks do not establish successful Spark computation or Athena publication.
