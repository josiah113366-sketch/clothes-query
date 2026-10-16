"""번역 입력 정리와 번역 실패 판정."""
import html
import re

from . import config as C

HANGUL = re.compile(r'[가-힣]')
LATIN = re.compile(r'[A-Za-z]')
# 한자(CJK 통합 한자)와 일본어 가나. Qwen이 번역 중간에 중국어를 섞는 경우를 잡는다.
HAN = re.compile(r'[㐀-䶿一-鿿豈-﫿]')
KANA = re.compile(r'[぀-ヿ]')
REPEAT = re.compile(r'(\S{2,}(?:\s+\S+){0,2}?)(?:\s+\1){3,}')   # 같은 1~3단어가 4번 넘게 연속


def clean_source(text):
    """번역 입력용으로 원문을 정리한다: HTML 제거, 공백 정리, 길이 제한."""
    t = html.unescape(str(text))
    t = re.sub(r'<br\s*/?>', ' ', t, flags=re.I)
    t = re.sub(r'<[^>]{1,40}>', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    if len(t) > C.MAX_SRC_CHARS:
        cut = max(t.rfind(p, 0, C.MAX_SRC_CHARS) for p in '.!?')
        t = t[:cut + 1] if cut > C.MAX_SRC_CHARS // 2 else t[:C.MAX_SRC_CHARS]
    return t


def split_chunks(text, max_chars=None):
    """문장 단위로 나눈 뒤 max_chars 이하가 되게 이어 붙인 덩어리 목록을 돌려준다."""
    max_chars = max_chars or C.MAX_CHUNK_CHARS
    sents = re.split(r'(?<=[.!?…])\s+', text.strip())
    chunks, cur = [], ''
    for s in sents:
        while len(s) > max_chars:
            cut = s.rfind(' ', 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if cur:
                chunks.append(cur); cur = ''
            chunks.append(s[:cut].strip()); s = s[cut:].strip()
        if not s:
            continue
        if cur and len(cur) + 1 + len(s) > max_chars:
            chunks.append(cur); cur = s
        else:
            cur = f'{cur} {s}'.strip()
    if cur:
        chunks.append(cur)
    return chunks or ['']


def failure_reason(src, ko):
    """번역 실패로 볼 만한 이유를 돌려준다. 문제 없으면 ''.
    한자·가나 검사는 한글 비율 검사보다 먼저 한다. 중국어가 조금 섞인 번역은 한글 비율이 높아 비율 검사를 통과하기 때문.
    원문에 한자가 있으면(드문 경우) 이 검사는 건너뛴다."""
    if not ko.strip():
        return '빈 번역'
    if not HAN.search(src) and (HAN.search(ko) or KANA.search(ko)):
        return '한자·가나 혼입'
    h, l = len(HANGUL.findall(ko)), len(LATIN.findall(ko))
    if h / max(1, h + l) < 0.5:
        return '한글 비율 낮음'
    if REPEAT.search(ko):
        return '반복'
    ratio = len(ko) / max(1, len(src))
    if ratio < 0.15 or ratio > 1.5:
        return '길이 비정상'
    return ''
