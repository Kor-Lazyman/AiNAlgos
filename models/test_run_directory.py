from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from train import create_run_directory


class RunDirectoryTests(unittest.TestCase):
    def test_first_and_max_existing_number(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            self.assertEqual(create_run_directory(root).name, "train1")
            (root / "train3").mkdir()
            (root / "train99_backup").mkdir()
            (root / "train200").write_text("not a directory")
            self.assertEqual(create_run_directory(root).name, "train4")
            self.assertTrue((root / "train1").is_dir())

    def test_concurrent_runs_never_share_directory(self):
        with TemporaryDirectory() as temporary:
            with ThreadPoolExecutor(max_workers=4) as pool:
                runs = list(pool.map(lambda _: create_run_directory(temporary), range(8)))
            self.assertEqual(len(set(runs)), 8)
            self.assertEqual({p.name for p in runs}, {f"train{i}" for i in range(1, 9)})


if __name__ == "__main__":
    unittest.main()
