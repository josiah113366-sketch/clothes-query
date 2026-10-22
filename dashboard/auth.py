"""로그인 사용자 확인 + Role(역할) 판정.

이 대시보드는 Role이 두 개다 (화면 단위로 나눔).
  - "product": 상품 관리 (매출, 트렌드 분석, 리뷰 분석)
  - "data"   : 데이터 관리 (이상탐지, 데이터 흐름 체크)
두 Role을 모두 가진 사용자(예: 관리자)는 모든 화면을 본다.

동작 모드는 환경변수 AUTH_MODE 로 고른다.
  - "local": 고정 계정 3개(상품관리/데이터관리/관리자)로 아이디·비밀번호 로그인. 실서비스에서도 이 방식으로 쓸 예정이다.
             계정 파일은 make_test_accounts.py 로 만들고, 실서비스에서는 그 파일을 Secret 으로 마운트해
             LOCAL_ACCOUNTS_FILE 로 가리킨다. 실서비스 조건은 README 의 '실서비스에서 local 로그인 쓸 때' 참고
             (HTTPS 필수, 접속 IP 제한, 로그인 실패 잠금).
  - "dev"  (기본값): 로그인 없이 사이드바에서 Role을 직접 고른다. 로컬 개발·화면 확인용.
                      **EKS에 올릴 때는 반드시 "oidc"로 바꿀 것** (dev는 누구나 Role을 고를 수 있음).
  - "oidc": Streamlit 내장 로그인(st.login, OIDC)으로 이메일을 받고, 이메일 -> Role 표(ROLES_JSON)로 판정.
            OIDC 공급자 설정(.streamlit/secrets.toml)은 EKS 담당자와 정한 뒤 채운다 (README 참고).
"""

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import streamlit as st

# ---- 설정값 -------------------------------------------------------------
# AUTH_MODE: "dev" 또는 "oidc". 기본 "dev" (안전하지 않음, 로컬 전용).
AUTH_MODE = os.getenv("AUTH_MODE", "dev")

# ROLES_JSON: 이메일 -> Role 목록. 예: {"a@x.com": ["product"], "b@x.com": ["product", "data"]}
# 실제 이메일을 코드/Git에 넣지 말고 배포 환경의 Secret 등으로 환경변수에 주입한다.
# 목록에 없는 사용자는 Role이 없어 어떤 화면도 볼 수 없다 (기본 거부).
ROLES_JSON = os.getenv("ROLES_JSON", "{}")

ALL_ROLES = ("product", "data")

# local 모드 테스트 계정 파일. make_test_accounts.py 가 만든다 (Git 제외 폴더 .local/).
# 비밀번호는 저장하지 않고 salt + PBKDF2 해시만 저장한다.
LOCAL_ACCOUNTS_FILE = Path(
    os.getenv("LOCAL_ACCOUNTS_FILE", Path(__file__).parent / ".local" / "accounts.json")
)
# PBKDF2 반복 횟수. make_test_accounts.py 와 반드시 같은 값이어야 로그인된다.
PBKDF2_ITERATIONS = 200_000
# 로그인 실패 잠금: 같은 아이디가 MAX_FAILS 번 연속 틀리면 LOCK_SECONDS 초 동안 로그인을 막는다.
# 무차별 대입(비밀번호 계속 시도)을 늦추기 위한 값이다. 너무 작게 잡으면 정상 사용자가 자주 잠긴다.
MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "5"))
LOCK_SECONDS = int(os.getenv("LOGIN_LOCK_SECONDS", "300"))
# 아이디별 최근 실패 시각. 서버 프로세스 메모리에 있으므로 재시작하면 초기화되고,
# 파드(replica)를 여러 개로 늘리면 파드마다 따로 센다 (replicas 1 일 때 가장 정확).
_FAILS: dict[str, list[float]] = {}


def _locked(username: str) -> bool:
    """최근 LOCK_SECONDS 안에 실패가 MAX_FAILS 번 이상이면 True."""
    now = time.time()
    recent = [t for t in _FAILS.get(username, []) if now - t < LOCK_SECONDS]
    _FAILS[username] = recent
    return len(recent) >= MAX_FAILS


def hash_password(password: str, salt_hex: str) -> str:
    """비밀번호 해시(hex). make_test_accounts.py 도 이 함수를 쓴다."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    ).hex()


def _verify_local(username: str, password: str) -> list[str] | None:
    """아이디/비밀번호가 맞으면 Role 목록을, 아니면 None. 계정 파일이 없으면 아무도 못 들어간다."""
    try:
        accounts = json.loads(LOCAL_ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        st.error("테스트 계정 파일이 없습니다. `python make_test_accounts.py` 를 먼저 실행하세요.")
        return None
    acc = accounts.get(username)
    if acc is None:
        # 계정이 없어도 같은 계산을 해서 응답 시간 차이로 아이디 존재 여부가 드러나지 않게 한다.
        hash_password(password, "00" * 16)
        return None
    ok = hmac.compare_digest(hash_password(password, acc["salt"]), acc["hash"])
    return [r for r in acc["roles"] if r in ALL_ROLES] if ok else None


def _local_login_form() -> None:
    """아이디/비밀번호 입력 화면. 맞으면 session_state 에 저장하고 다시 실행한다."""
    st.title("로그인")
    with st.form("local_login"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
    if submitted:
        name = username.strip()
        if _locked(name):
            # 잠긴 동안은 비밀번호가 맞아도 들어갈 수 없다 (시도 자체를 막음).
            st.error(
                f"로그인 실패가 많아 잠시 막혔습니다. {LOCK_SECONDS // 60}분 뒤에 다시 시도하세요."
            )
            return
        roles = _verify_local(name, password)
        if roles is None:
            if len(_FAILS) > 1000:  # 없는 아이디를 계속 넣어 메모리가 불어나는 것을 막는다
                _FAILS.clear()
            _FAILS.setdefault(name, []).append(time.time())
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
        else:
            _FAILS.pop(name, None)
            st.session_state["local_user"] = {"name": username.strip(), "roles": roles}
            st.rerun()


def logout() -> None:
    """로그아웃 버튼 콜백. oidc 는 Streamlit 로그아웃, local 은 세션 값을 지운다."""
    if AUTH_MODE == "oidc":
        st.logout()
    else:
        st.session_state.pop("local_user", None)


def _roles_for_email(email: str) -> list[str]:
    """이메일에 허용된 Role 목록을 돌려준다. 모르는 사용자는 빈 목록(= 접근 불가)."""
    try:
        table = json.loads(ROLES_JSON)
    except json.JSONDecodeError:
        # 설정이 깨져 있으면 아무도 못 들어가게 막는다 (열어두는 쪽으로 실패하지 않음).
        st.error("ROLES_JSON 형식이 올바르지 않습니다. 관리자에게 문의하세요.")
        return []
    # 대소문자 차이로 거부되지 않게 소문자로 비교한다.
    table = {k.lower(): v for k, v in table.items()}
    return [r for r in table.get(email.lower(), []) if r in ALL_ROLES]


def current_user(interactive: bool = True) -> tuple[str, list[str]]:
    """(표시 이름, Role 목록)을 돌려준다. 로그인이 안 됐으면 로그인 화면을 보여주고 실행을 멈춘다.

    interactive=True : app.py에서만 쓴다. dev 모드의 Role 선택 위젯을 화면에 그린다.
    interactive=False: 페이지의 권한 검사(require_role)용. 위젯을 그리지 않고 선택된 값만 읽는다.
                       (위젯을 두 번 그리면 Role 선택 화면이 2개로 보이는 문제가 생긴다)
    """
    if AUTH_MODE == "local":
        user = st.session_state.get("local_user")
        if user is None:
            if interactive:
                _local_login_form()
            st.stop()  # 로그인 전에는 아래 화면 코드를 실행하지 않음
        return user["name"], list(user["roles"])

    if AUTH_MODE == "oidc":
        # st.user: Streamlit 1.42+ 의 OIDC 로그인 정보. 로그인 전에는 is_logged_in 이 False.
        if not st.user.is_logged_in:
            st.title("로그인이 필요합니다")
            st.button("로그인", on_click=st.login)
            st.stop()  # 아래 코드는 실행하지 않음
        email = st.user.get("email", "")
        return email, _roles_for_email(email)

    # ---- dev 모드: 사이드바에서 Role 직접 선택 (로컬 확인 전용) ----
    if interactive:
        st.sidebar.warning("AUTH_MODE=dev: 로컬 확인용입니다")
        # key: 선택값을 session_state["dev_roles"]에 저장해 페이지 쪽 검사에서 읽게 한다.
        st.sidebar.multiselect(
            "Role 선택(dev)", ALL_ROLES, default=list(ALL_ROLES), key="dev_roles"
        )
    return "dev-user", list(st.session_state.get("dev_roles", ALL_ROLES))


def require_role(*allowed: str) -> None:
    """페이지 파일 맨 위에서 호출한다. 허용된 Role이 없으면 화면을 멈춘다.

    메뉴에서 숨기는 것만으로는 URL을 직접 입력해 들어올 수 있으므로,
    각 페이지에서도 한 번 더 검사한다 (이중 방어).
    """
    _, roles = current_user(interactive=False)
    if not set(roles) & set(allowed):
        st.error("이 화면을 볼 권한이 없습니다.")
        st.stop()
