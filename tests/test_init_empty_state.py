from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class _Session:
    def __init__(self) -> None:
        self.remove_calls = 0
        self.bind = mock.Mock()

    def remove(self) -> None:
        self.remove_calls += 1


class InitEmptyStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def fake_persistence(self) -> tuple[types.ModuleType, list[Path], _Session]:
        paths: list[Path] = []
        session = _Session()

        def init_db(url: str) -> None:
            prefix = "sqlite:///"
            self.assertTrue(url.startswith(prefix))
            path = Path(url[len(prefix) :])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            paths.append(path)

        module = types.ModuleType("freqtrade.persistence")
        module.init_db = init_db
        module.Trade = types.SimpleNamespace(session=session)
        return module, paths, session

    def test_creates_only_two_empty_trading_state_databases(self) -> None:
        from tools import init_empty_state

        persistence, paths, session = self.fake_persistence()
        with mock.patch.dict(sys.modules, {"freqtrade.persistence": persistence}):
            init_empty_state.create_empty_state_databases(self.root)

        expected = [
            self.root / "ft_userdata/runtime/freqtrade/trades.sqlite",
            self.root / "ft_userdata/runtime/freqtrade-futures/trades.sqlite",
        ]
        self.assertEqual(paths, expected)
        self.assertTrue(all(path.is_file() for path in expected))
        self.assertEqual(session.remove_calls, 2)
        self.assertEqual(session.bind.dispose.call_count, 2)

    def test_refuses_all_creation_if_either_database_exists(self) -> None:
        from tools import init_empty_state

        existing = self.root / "ft_userdata/runtime/freqtrade-futures/trades.sqlite"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"preserve")
        persistence, paths, session = self.fake_persistence()
        with (
            mock.patch.dict(sys.modules, {"freqtrade.persistence": persistence}),
            self.assertRaises(FileExistsError),
        ):
            init_empty_state.create_empty_state_databases(self.root)

        self.assertEqual(paths, [])
        self.assertEqual(existing.read_bytes(), b"preserve")
        self.assertEqual(session.remove_calls, 0)


if __name__ == "__main__":
    unittest.main()
