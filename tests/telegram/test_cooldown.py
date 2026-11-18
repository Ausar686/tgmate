from tgmate.telegram.cooldown import Cooldown


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_key_is_ready_again_only_after_the_interval() -> None:
    clock = Clock()
    cooldown = Cooldown(10, clock)

    assert cooldown.ready("a")
    clock.now = 9.9
    assert not cooldown.ready("a")
    clock.now = 10
    assert cooldown.ready("a")


def test_keys_are_independent() -> None:
    cooldown = Cooldown(10, Clock())

    assert cooldown.ready("a")
    assert cooldown.ready("b")
    assert not cooldown.ready("a")
