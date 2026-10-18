"""환경 점검: 큰 모델 시험에 필요한 패키지, 장치, 메모리, 디스크, 키 설정을 확인한다.
모델을 내려받거나 원격 코드를 실행하지 않는다. 실행: python check_env.py"""
import io
import os
import platform
import shutil
import sys
from importlib import metadata
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
ROOT = Path(__file__).resolve().parent
ok = True


def line(flag, text):
    global ok
    ok &= flag != '✗'
    print(f'[{flag}] {text}')


print(f'Python {sys.version.split()[0]} / {platform.platform()}')

# 1) 패키지와 버전
need = {'torch': None, 'transformers': ('4.51', '4.54'), 'accelerate': None, 'sentencepiece': None, 'protobuf': None,
        'safetensors': None, 'peft': None, 'huggingface_hub': None, 'pandas': None, 'scikit-learn': None, 'google-genai': None}
for name, rng in need.items():
    try:
        v = metadata.version(name)
    except metadata.PackageNotFoundError:
        line('✗', f'{name} 미설치 → pip install -r requirements-llm.txt')
        continue
    if rng:
        lo, hi = (tuple(int(x) for x in r.split('.')) for r in rng)
        cur = tuple(int(x) for x in v.split('.')[:2])
        if not (lo <= cur < hi):
            line('✗', f'{name} {v}: {rng[0]} 이상 {rng[1]} 미만이어야 합니다 (EXAONE 원격 코드 호환)')
            continue
    line('✓', f'{name} {v}')

# 2) 장치
try:
    import torch
    if torch.cuda.is_available():
        line('✓', f'GPU: {torch.cuda.get_device_name(0)} ({torch.cuda.get_device_properties(0).total_memory / 1e9:.0f}GB)')
    else:
        line('!', f'GPU 없음(CPU {os.cpu_count()}코어). 7B 이상은 매우 느리니 확인용 소량으로만, 학습은 Colab에서')
except ImportError:
    pass

# 3) 메모리와 디스크 (7~8B 모델 bf16은 약 16GB)
try:
    import ctypes

    class MEM(ctypes.Structure):
        _fields_ = [('l', ctypes.c_ulong), ('p', ctypes.c_ulong), ('tp', ctypes.c_ulonglong), ('ap', ctypes.c_ulonglong),
                    ('tpf', ctypes.c_ulonglong), ('apf', ctypes.c_ulonglong), ('tv', ctypes.c_ulonglong), ('av', ctypes.c_ulonglong),
                    ('ae', ctypes.c_ulonglong)]
    m = MEM(); m.l = ctypes.sizeof(MEM); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    gb, free = m.tp / 1e9, m.ap / 1e9
    line('✓' if free > 18 else '!', f'RAM 전체 {gb:.0f}GB, 지금 사용 가능 {free:.0f}GB (7~8B bf16 약 16GB, 2~3B 약 5~6GB)')
except Exception:
    line('!', 'RAM 확인 생략 (Windows 외 환경)')
hf_home = Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface'))
disk = shutil.disk_usage(hf_home.anchor or '.').free / 1e9
line('✓' if disk > 40 else '!', f'모델 캐시 위치 {hf_home} / 디스크 여유 {disk:.0f}GB (7~8B 모델 1개 약 16GB)')

# 4) 키와 폴더 (값은 출력하지 않는다)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:
    pass
line('✓' if os.environ.get('GEMINI_KEY') else '!', 'GEMINI_KEY ' + ('설정됨' if os.environ.get('GEMINI_KEY') else '없음 (Gemini 라벨링/비교는 불가)'))
line('✓' if os.environ.get('HF_TOKEN') else '!', 'HF_TOKEN ' + ('설정됨' if os.environ.get('HF_TOKEN') else '없음 (공개 모델은 없어도 되고, 게이트 모델만 필요)'))
line('✓' if (ROOT / 'private').exists() else '!', 'private/ ' + ('있음 (사람 평가셋은 이 PC 안에서만 사용)' if (ROOT / 'private').exists() else '없음'))

print('\n환경 점검 결과:', '모두 통과' if ok else '✗ 항목을 먼저 해결하세요')
sys.exit(0 if ok else 1)
