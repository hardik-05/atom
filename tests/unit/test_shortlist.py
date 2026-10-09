from decimal import Decimal as D

from atom.strategy.shortlist import pick

SYMBOLS = {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD", 5: "EEE"}


def test_top_n_by_average_volume_with_a_full_window_and_the_floor() -> None:
    volumes = {
        1: (D("5000"), 100),
        2: (D("9000"), 100),
        3: (D("9000"), 100),  # ties break on symbol
        4: (D("50"), 100),  # under the floor
        5: (D("99999"), 40),  # not enough volume history
    }
    chosen = pick(volumes, SYMBOLS, size=2, window=100, threshold=D("1000"))
    assert [(iid, rank) for iid, rank, _, _ in chosen] == [(2, 1), (3, 2)]


def test_fewer_qualifying_than_asked_gives_a_shorter_list() -> None:
    chosen = pick({1: (D("5000"), 10)}, SYMBOLS, size=50, window=10, threshold=D("0"))
    assert len(chosen) == 1
