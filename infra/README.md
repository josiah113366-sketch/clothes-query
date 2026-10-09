# infra

clothes-query의 AWS 인프라를 Terraform으로 관리한다. 리전은 `ap-northeast-1`(도쿄).

## 스택 순서와 의존 관계

```
bootstrap → network → eks → platform
```

| 스택 | 위치 | 내용 | 의존 | 상태 |
|---|---|---|---|---|
| `bootstrap` | `bootstrap/` | state 저장용 S3 버킷 (버저닝, 암호화, 퍼블릭 차단) | 없음 | 코드 작성됨 |
| `network` | `stacks/network/` | VPC, 서브넷, NAT 등 | bootstrap | 예정 |
| `eks` | `stacks/eks/` | EKS 클러스터, 노드그룹, IAM(IRSA), access entry | network | 예정 |
| `platform` | `stacks/platform/` | Helm으로 Kafka / Spark / Airflow 설치 | eks | 예정 |

## apply / destroy 순서

- apply: `bootstrap → network → eks → platform`
- destroy: 역순 (`platform → eks → network → bootstrap`). `bootstrap`은 모든 스택의 state를 담고 있으므로 가장 마지막에 지운다.

## state

- 버킷: `clothes-query-tfstate-<AWS계정ID>` (프로젝트 전체에 하나)
- key: `clothes-query/dev/<스택명>/terraform.tfstate` (스택마다 다르게)
- `bootstrap`만 local state를 쓴다. 자세한 내용은 [bootstrap/bootstrap.md](bootstrap/bootstrap.md) 참고.