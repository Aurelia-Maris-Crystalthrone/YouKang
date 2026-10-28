import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from labelmap import CLASS_NAMES

IMG_BYTES = b"\x89PNG\r\n\x1a\nfakeimagebytes"


def make_img(path: Path) -> None:
    path.write_bytes(IMG_BYTES)


def run_prepare(src: Path, dst: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "prepare_dataset.py"),
         "--src", str(src), "--dst", str(dst)],
        capture_output=True, text=True)


class TestPrepareDataset(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pomelo_prep_"))
        self.src = self.tmp / "raw"
        self.dst = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_split_811_reproducible_pseudobox(self):
        for name in CLASS_NAMES:
            d = self.src / name
            d.mkdir(parents=True)
            for i in range(20):
                make_img(d / f"{i}.jpg")
        proc = run_prepare(self.src, self.dst)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        counts = {}
        for split in ("train", "val", "test"):
            imgs = list((self.dst / "images" / split).glob("*.jpg"))
            lbls = list((self.dst / "labels" / split).glob("*.txt"))
            counts[split] = len(imgs)
            self.assertEqual(len(imgs), len(lbls), f"{split}: txt 行数与图片数不一致")
        self.assertEqual(counts["train"], 64)
        self.assertEqual(counts["val"], 8)
        self.assertEqual(counts["test"], 8)

        lbl = sorted((self.dst / "labels" / "train").glob("*.txt"))[0]
        parts = lbl.read_text().strip().split()
        self.assertEqual(len(parts), 5)
        cls_id = int(parts[0])
        xc, yc, w, h = map(float, parts[1:])
        self.assertIn(cls_id, {0, 1, 2, 3})
        for v in (xc, yc, w, h):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)
        self.assertEqual((xc, yc, w, h), (0.5, 0.5, 1.0, 1.0))

        yaml_text = (self.dst / "citrus.yaml").read_text()
        self.assertIn("nc: 4", yaml_text)
        for n in CLASS_NAMES:
            self.assertIn(n, yaml_text)
        self.assertIn("<DATASET_ROOT>", yaml_text)

        stats = (self.dst / "dataset_stats.txt").read_text()
        for n in CLASS_NAMES:
            self.assertIn(n, stats)
        self.assertIn("train", stats)

        first_run = {s: sorted(p.name for p in (self.dst / "images" / s).iterdir())
                     for s in ("train", "val", "test")}
        proc2 = run_prepare(self.src, self.dst)
        self.assertEqual(proc2.returncode, 0, proc2.stdout + proc2.stderr)
        for s in ("train", "val", "test"):
            second = sorted(p.name for p in (self.dst / "images" / s).iterdir())
            self.assertEqual(first_run[s], second, f"种子 42 重复执行 split={s} 结果不一致")

    def test_unknown_class_dropped(self):
        # healthy 属负样本（应纳入，生成空标注），真正未知的类别才丢弃
        (self.src / "healthy").mkdir(parents=True)
        (self.src / "totally_unknown_thing").mkdir(parents=True)
        make_img(self.src / "healthy" / "h1.jpg")
        make_img(self.src / "totally_unknown_thing" / "g1.jpg")
        proc = run_prepare(self.src, self.dst)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        names = {p.name for p in (self.dst / "images" / "train").iterdir()}
        self.assertEqual(names, {"neg_h1.jpg"})
        # 负样本标注文件必须为空（无检测框）
        lbl = self.dst / "labels" / "train" / "neg_h1.txt"
        self.assertTrue(lbl.exists())
        self.assertEqual(lbl.read_text(encoding="utf-8"), "")
        stats = (self.dst / "dataset_stats.txt").read_text()
        self.assertNotIn("totally_unknown_thing", stats)

    def test_no_valid_class_error(self):
        (self.src / "totally_unknown_thing").mkdir(parents=True)
        make_img(self.src / "totally_unknown_thing" / "g1.jpg")
        proc = run_prepare(self.src, self.dst)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.dst.exists())

    def test_invalid_src_no_output(self):
        proc = run_prepare(self.tmp / "nonexistent", self.dst)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.dst.exists())

    def test_zero_sample_marked(self):
        (self.src / "healthy").mkdir(parents=True)
        for i in range(5):
            make_img(self.src / "healthy" / f"z{i}.jpg")
        proc = run_prepare(self.src, self.dst)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        stats = (self.dst / "dataset_stats.txt").read_text()
        # healthy 归入负样本桶，不再作为检测类出现在 0 样本告警里
        self.assertIn("[0 样本]", stats)
        self.assertIn("__negative__", stats)
        self.assertNotIn("healthy/val", stats)


if __name__ == "__main__":
    unittest.main()