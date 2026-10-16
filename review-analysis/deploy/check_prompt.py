"""배포 스크립트의 프롬프트와 속성이 학습·평가에 쓴 것과 같은지 확인한다. 실행(저장소 루트에서): python deploy/check_prompt.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'deploy'))
from review_analysis import schema3 as S3, score as SC   # noqa: E402
import score_batch as B   # noqa: E402

S3.set_aspects(True)
assert B.ASPECTS == list(S3.ASPECTS3), (B.ASPECTS, S3.ASPECTS3)
assert B.PROMPT == SC.SHORT_SCORE, '프롬프트가 학습·평가용과 다릅니다'
print('프롬프트·속성 일치')
