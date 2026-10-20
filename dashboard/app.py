"""대시보드 진입점. 실행: `streamlit run app.py`

하는 일
  1) 로그인 사용자와 Role 확인 (auth.py)
  2) Role에 맞는 페이지만 왼쪽 메뉴에 보여줌 (st.navigation)
각 화면은 pages_product/ (상품 관리), pages_data/ (데이터 관리) 폴더의 파일이다.
화면을 추가하려면 파일을 만든 뒤 아래 PRODUCT_PAGES / DATA_PAGES 목록에 한 줄 추가한다.
"""

import streamlit as st

import auth
import data
from auth import current_user

st.set_page_config(page_title="리뷰·상품 대시보드", layout="wide")

# Role별 화면 목록. st.Page(파일경로, title=메뉴 이름, icon=아이콘)
PRODUCT_PAGES = [
    st.Page("pages_product/overview.py", title="통합 조회", icon="🔎", default=True),
    st.Page("pages_product/orders.py", title="주문·매출", icon="💰"),
    st.Page("pages_product/product_sales.py", title="상품 판매", icon="🛍️"),
    st.Page("pages_product/funnel.py", title="구매 퍼널", icon="🔻"),
    st.Page("pages_product/reviews.py", title="리뷰·속성 분석", icon="📝"),
]
DATA_PAGES = [
    st.Page("pages_data/pipeline.py", title="파이프라인 상태", icon="🔧"),
    st.Page("pages_data/payments.py", title="결제 관제", icon="💳"),
    st.Page("pages_data/malformed.py", title="형식 오류", icon="🧩"),
    st.Page("pages_data/anomaly.py", title="이상탐지", icon="🚨"),
    st.Page("pages_data/rca_report.py", title="원인 리포트", icon="🕵️"),
    st.Page("pages_data/reprocess.py", title="재처리 이력", icon="♻️"),
]

user, roles = current_user()
st.sidebar.caption(f"사용자: {user}")
if auth.AUTH_MODE in ("local", "oidc"):
    # 계정을 바꿔 시험하려면 로그아웃이 필요하다.
    st.sidebar.button("로그아웃", on_click=auth.logout)

# 사용자가 가진 Role의 화면만 모은다. 두 Role이면 두 그룹이 모두 보인다.
menu = {}
if "product" in roles:
    menu["상품 관리"] = PRODUCT_PAGES
if "data" in roles:
    menu["데이터 관리"] = DATA_PAGES

if not menu:
    # Role이 하나도 없으면 접근 거부 (ROLES_JSON에 없는 사용자 등)
    st.error("접근 권한이 없습니다. 관리자에게 Role 부여를 요청하세요.")
    st.stop()

st.navigation(menu).run()

# 페이지 실행 뒤에 표시해야 이번 화면에서 더미로 대체된 데이터를 알 수 있다.
# 실데이터가 아직 연결되지 않은 데이터는 더미로 보여주므로, 값을 실제 수치로 오해하지 않게 알린다.
if data.USING_DUMMY:
    st.sidebar.warning("더미 데이터 사용 중: " + ", ".join(sorted(data.USING_DUMMY)))
