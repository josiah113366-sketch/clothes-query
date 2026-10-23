"""테스트 계정 3개(상품 관리 / 데이터 관리 / 관리자)를 만든다. 실행: `python make_test_accounts.py`

- 결과 파일: .local/accounts.json (Git 제외 폴더). 파일에는 비밀번호가 아니라 salt + 해시만 저장한다.
- 비밀번호는 실행할 때 무작위로 만들어 **화면에 한 번만** 출력한다. 잃어버리면 다시 실행해 새로 만든다.
- `--same-as-id`: 비밀번호를 아이디와 똑같이 만든다(팀 합의로 쓰는 약한 비밀번호). 아이디가 코드에 공개돼 있으므로
  접속 보호는 허용 IP와 로그인 실패 잠금에만 의지한다.
- 이미 파일이 있으면 덮어쓰지 않는다 (--force 로 새로 만들기).
- 로컬 시험 전용이다. 실서비스 로그인(OIDC)을 대신하지 않는다.
"""

import json
import secrets
import sys

from auth import LOCAL_ACCOUNTS_FILE, hash_password

# (아이디, 가진 Role). 이름이나 Role 조합을 바꾸려면 여기만 고친다.
ACCOUNTS = [
    ("product_user", ["product"]),
    ("data_user", ["data"]),
    ("admin", ["product", "data"]),
]


def main() -> None:
    if LOCAL_ACCOUNTS_FILE.exists() and "--force" not in sys.argv:
        sys.exit(f"{LOCAL_ACCOUNTS_FILE} 가 이미 있습니다. 새로 만들려면 --force 를 붙이세요.")
    out, shown = {}, []
    for name, roles in ACCOUNTS:
        # 기본은 12자 안팎의 무작위 비밀번호. --same-as-id 이면 아이디와 같게 한다.
        password = name if "--same-as-id" in sys.argv else secrets.token_urlsafe(9)
        salt = secrets.token_hex(16)
        out[name] = {"salt": salt, "hash": hash_password(password, salt), "roles": roles}
        shown.append((name, password, roles))
    LOCAL_ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_ACCOUNTS_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"저장: {LOCAL_ACCOUNTS_FILE}\n(비밀번호는 지금만 보입니다)")
    for name, password, roles in shown:
        print(f"  아이디 {name:<13} 비밀번호 {password:<14} Role {roles}")


if __name__ == "__main__":
    main()
