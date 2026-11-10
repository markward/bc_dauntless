"""Chain of command for a wing. Pure: no App imports."""
from typing import Callable, Optional


def chain_size(n_mobile: int) -> int:
    return max(1, n_mobile // 5)


def build_chain(members: list, player: Optional[str]) -> list:
    """members: (name, rated_power) in group order, player excluded."""
    n = chain_size(len(members) + (1 if player else 0))
    ranked = sorted(members, key=lambda m: -m[1])  # stable on ties
    names = [m[0] for m in ranked]
    out = [player] if player else []
    return (out + names)[:n]


def current_commander(chain: list,
                      is_alive: Callable[[str], bool]) -> Optional[str]:
    for name in chain:
        if is_alive(name):
            return name
    return None
