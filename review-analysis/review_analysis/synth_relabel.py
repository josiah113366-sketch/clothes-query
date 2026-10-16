"""합성 리뷰 정답 보정 (2026-10-13 사용자 지시). 원본 파일은 덮어쓰지 않고, 평가·학습에서 apply()로 보정한 사본을 쓴다.
규칙: ① 반어 후기는 부정으로(반어로 쓰인 속성: 3분류 부정, 점수 −2)  ② 문제가 없다는 표현("물 빠짐은 없네요", "줄어들지 않았다")은 약한 만족(3분류 긍정, 점수 +1)
③ 어깨선·솔기가 뜯어졌다는 표현은 품질·내구성 (사이즈·핏 아님, R4).
반어 판정은 Gemini에 합성 텍스트와 속성 목록만 보내 받는다(결과는 absa_pilot/relabel/에 캐시)."""
import json
import re

from . import config as C
from .absa import OUT
from .translators import GeminiClient

CACHE = OUT / 'relabel'
PROMPT = (
    '다음은 의류 쇼핑몰 후기와, 이 후기가 평가한 속성 목록입니다. 후기에서 **반어**(칭찬처럼 쓰였지만 실제 뜻은 불만·비꼼)로 쓰인 속성만 골라 sarcastic 배열에 담으세요. '
    '예: "택배 상자가 터져서 왔는데 참 훌륭하네요"는 포장이 반어입니다. 반어가 아닌 진짜 칭찬·보통·불만은 담지 마세요. 반어가 없으면 빈 배열. 속성은 주어진 목록에서만 고르세요.\n'
    '출력: [{"id": 번호, "sarcastic": ["속성", ...]}] 형식의 JSON 배열만 출력하세요.\n\n입력:\n')
NO_PROBLEM = re.compile(r'줄어들지|줄지 ?않|줄진 ?않|줄어든 ?(것|게|곳)? ?(없|전혀)|물 ?빠짐[은이]? ?(전혀 )?없|물이 ?(전혀 )?안 ?빠|변형[은이]? ?(전혀 )?(없|안)|변형되지|늘어나지|구김[은이]? ?(전혀 )?없|보풀[이은]? ?(전혀 )?없|올이? ?(안|풀리지)')
GUESS = re.compile(r'것 ?같|듯|수도|할지|거 ?같|싶')   # 추측·희망 문장은 경험이 아니다 (R10)
NEUTRAL_W = re.compile(r'평범|보통|그저|그냥 그|무난|쏘쏘|그럭저럭')
TORN = re.compile(r'뜯어|뜯겨|뜯기|터져|터졌|솔기|박음질|바느질|실밥')
SIZE_W = re.compile(r'크[다고네게]|크긴|작[다고네아]|길[다고네어]|짧[다고네아]|넉넉|좁|넓|사이즈|기장|핏|품이|통이|소매 ?길|오버|타이트|헐렁|끼[네어]')


def _sentences(text):
    return [s for s in re.split(r'(?<=[.!?\n])\s+|[,，]', text) if s.strip()]


def sarcasm(data, gold, name):
    """반어 스타일로 만든 항목 중 Gemini가 반어로 본 속성: {idx: [속성]}. 캐시 사용."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'{name}.sarcasm.json'
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('n') == len(data):
            return {int(k): v for k, v in saved['flip'].items()}
    idx = [i for i, d in enumerate(data) if '반어' in d.get('style', '') and d.get('review')]
    gc = GeminiClient(C.LLM_JUDGE_MODEL)
    items = [{'id': i, 'review': data[i]['review'], 'aspects': list(gold[i])} for i in idx]
    flip = {}
    for s in range(0, len(items), 10):
        got = gc.call(PROMPT, items[s:s + 10], 'sarcastic')
        for it in items[s:s + 10]:
            v = got.get(it['id']) or []
            keep = [a for a in v if a in gold[it['id']]]
            if keep:
                flip[it['id']] = keep
    path.write_text(json.dumps(dict(n=len(data), flip=flip), ensure_ascii=False), encoding='utf-8')
    return flip


def apply(data, gold, kind, name):
    """gold(리뷰별 {속성: 감성|점수})를 보정한 사본과 변경 기록을 반환. kind: '3class' | 'score'."""
    NEG, POS, ZERO = ('부정', '긍정', '중립') if kind == '3class' else (-2, 1, 0)
    new = [dict(g) for g in gold]
    log = []
    for i, asps in sarcasm(data, gold, name).items():
        for a in asps:
            if new[i].get(a) != NEG:
                log.append((i, '반어→부정', a, new[i][a], NEG)); new[i][a] = NEG
    for i, d in enumerate(data):
        text = d['review']
        for a in ('세탁·관리',):   # 세탁 후 변형·물빠짐이 없다는 경험 (이염·물빠짐은 R4상 품질이지만 이 규칙은 세탁·관리 정답에만 적용)
            if new[i].get(a) == ZERO:
                for m in NO_PROBLEM.finditer(text):
                    ctx = text[max(0, m.start() - 12): m.end() + 8]   # 같은 절 주변만 본다 (다른 속성의 '평범'이 섞여도 영향 없게)
                    if not NEUTRAL_W.search(ctx) and not GUESS.search(ctx):
                        log.append((i, '문제없음→약한만족', a, ZERO, POS)); new[i][a] = POS
                        break
        sz = new[i].get('사이즈·핏')
        if sz == (NEG if kind == '3class' else -2) or (kind == 'score' and isinstance(sz, int) and sz < 0):
            for s in _sentences(text):
                if TORN.search(s) and not SIZE_W.search(text):   # 후기 어디에도 크기·핏 표현이 없을 때만
                    val = new[i].pop('사이즈·핏')
                    new[i].setdefault('품질·내구성', val)
                    log.append((i, '뜯어짐→품질', '사이즈·핏→품질·내구성', val, new[i]['품질·내구성']))
                    break
    return new, log


def train_view(data, gold, pred, clean, kind, name):
    """학습용 보정: (보정된 gold, clean 인덱스). clean은 원래 정답과 Gemini 재추출이 일치한 항목이다.
    반어로 바뀐 항목은 재추출이 문장을 그대로 읽어 원래 정답과 달랐을 수 있으므로, 속성 집합이 같으면 clean에 포함시킨다."""
    new, _ = apply(data, gold, kind, name)
    flip = sarcasm(data, gold, name)
    keep = set(clean)
    for i in flip:
        if set(pred[i]) == set(gold[i]):
            keep.add(i)
    # 보정 후 정답이 다시 원래 정답과 같지 않은 항목은 재추출 일치 여부와 무관하게 보정 정답을 쓰므로 그대로 유지한다
    return new, sorted(keep)
