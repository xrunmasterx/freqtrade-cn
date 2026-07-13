from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DATABASES = (
    Path("ft_userdata/runtime/freqtrade/trades.sqlite"),
    Path("ft_userdata/runtime/freqtrade-futures/trades.sqlite"),
)


def create_empty_state_databases(root: Path = REPO_ROOT) -> None:
    from freqtrade.persistence import Trade, init_db

    destinations = [root.resolve() / relative for relative in STATE_DATABASES]
    if any(path.exists() for path in destinations):
        raise FileExistsError("empty state database destination already exists")

    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
        init_db(f"sqlite:///{path.as_posix()}")
        session = Trade.session
        engine = session.bind
        session.remove()
        if engine is not None:
            engine.dispose()


def main() -> int:
    create_empty_state_databases()
    print("empty state fixtures: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
