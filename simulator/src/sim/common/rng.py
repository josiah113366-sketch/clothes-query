"""시드 고정 난수 도구. 회원 모듈은 전역 random, 시드 없는 Faker()를 쓰지 않고 이것만 쓴다."""

import hashlib
import random
from collections.abc import Sequence

from faker import Faker


def derive_seed(seed: int, *names: object) -> int:
    """시드와 이름들로 다른 줄기의 시드를 만든다 (SHA-256 기반, 같은 입력이면 항상 같은 값)."""
    material = "\x1f".join([str(seed), *(str(name) for name in names)]).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


class SimRandom:
    """random.Random과 Faker("ko_KR")를 같은 시드로 묶은 클래스."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.random = random.Random(seed)
        self.faker = Faker("ko_KR")
        self.faker.seed_instance(seed)

    def reseed(self, seed: int) -> None:
        """난수열을 처음부터 다시 시작한다. SimRandom(seed)를 새로 만든 것과 같은 결과가 나온다."""
        self.seed = seed
        self.random.seed(seed)
        self.faker.seed_instance(seed)

    def randint(self, low: int, high: int) -> int:
        """low 이상 high 이하의 정수 (양끝 포함)."""
        return self.random.randint(low, high)

    def randrange(self, stop: int) -> int:
        return self.random.randrange(stop)

    def chance(self, probability: float) -> bool:
        return self.random.random() < probability

    def weighted_choice[T](self, items: Sequence[T], cum_weights: Sequence[float]) -> T:
        """누적 가중치(cum_weights)로 하나를 고른다."""
        return self.random.choices(items, cum_weights=cum_weights, k=1)[0]

    def random_string(self, alphabet: str, length: int) -> str:
        return "".join(self.random.choices(alphabet, k=length))

    def uuid4(self) -> str:
        return self.faker.uuid4()

    def name(self, gender: str) -> str:
        return self.faker.name_female() if gender == "F" else self.faker.name_male()
