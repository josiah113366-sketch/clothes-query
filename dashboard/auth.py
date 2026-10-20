"""로그인 사용자 확인 + Role(역할) 판정.

이 대시보드는 Role이 두 개다 (화면 단위로 나눔).
  - "product": 상품 관리 (매출, 트렌드 분석, 리뷰 분석)
  - "data"   : 데이터 관리 (이상탐지, 데이터 흐름 체크)
두 Role을 모두 가진 사용자(예: 관리자)는 모든 화면을 본다.

동작 모드는 환경변수 AUTH_MODE 로 고른다.
  - "dev"  (기본값): 로그인 없이 사이드바에서 Role을 직접 고른다. 로컬 개발·화면 확인용.
                      **EKS에 올릴 때는 반드시 "oidc"로 바꿀 것** (dev는 누구나 Role을 고를 수 있음).
  - "oidc": Streamlit 내장 로그인(st.login, OIDC)으로 이메일을 받고, 이메일 -> Role 표(ROLES_JSON)로 판정.
            OIDC 공급자 설정(.streamlit/secrets.toml)은 EKS 담당자와 정한 뒤 채운다 (README 참고).
"""

import json
import os

import streamlit as st

# ---- 설정값 -------------------------------------------------------------
# AUTH_MODE: "dev" 또는 "oidc". 기본 "dev" (안전하지 않음, 로컬 전용).
AUTH_MODE = os.getenv("AUTH_MODE", "dev")

# ROLES_JSON: 이메일 -> Role 목록. 예: {"a@x.com": ["product"], "b@x.com": ["product", "data"]}
# 실제 이메일을 코드/Git에 넣지 말고 배포 환경의 Secret 등으로 환경변수에 주입한다.
# 목록에 없는 사용자는 Role이 없어 어떤 화면도 볼 수 없다 (기본 거부).
ROLES_JSON = os.getenv("ROLES_JSON", "{}")

ALL_ROLES = ("product", "data")


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
