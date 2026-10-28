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

DATA_YAML = (
    "train: ../train/images\n"
    "val: ../valid/images\n"
    "\n"
    "nc: 4\n"
    "names: ['antracnose', 'canker', 'greasy_spot', 'greening']\n"
)


def make_img(path: Path) -> None:
    path.write_bytes(IMG_BYTES)


def run_cmd(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True)


class TestMergeRoboflow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pomelo_merge_"))
        self.src = self.tmp / "raw"
        self.dst = self.tmp / "out"
        self.rf = self.tmp / "rf"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _prepare_dst(self):
        (self.src / "healthy").mkdir(parents=True)
        for i in range(20):
            make_img(self.src / "healthy" / f"h{i}.jpg")
        proc = run_cmd(ROOT / "prepare_dataset.py", "--src", str(self.src),
                       "--dst", str(self.dst))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def _build_rf_dataset(self):
        (self.rf / "train" / "images").mkdir(parents=True)
        (self.rf / "train" / "labels").mkdir(parents=True)
        (self.rf / "valid" / "images").mkdir(parents=True)
        (self.rf / "valid" / "labels").mkdir(parents=True)
        (self.rf / "data.yaml").write_text(DATA_YAML, encoding="utf-8")
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            make_img(self.rf / "train" / "images" / name)
        make_img(self.rf / "valid" / "images" / "d.jpg")
        # a: segment 多边形（antracnose，拼写变体 id 0）→ 外接矩形
        (self.rf / "train" / "labels" / "a.txt").write_text(
            "0 0.1 0.1 0.5 0.3 0.7 0.6\n", encoding="utf-8")
        # b: 全部标注为不可映射类别 → 图片不纳入
        (self.rf / "train" / "labels" / "b.txt").write_text(
            "2 0.5 0.5 0.3 0.3\n", encoding="utf-8")
        # c: canker 保留（重映射 id 2）+ id 4 无映射丢弃
        (self.rf / "train" / "labels" / "c.txt").write_text(
            "1 0.3 0.3 0.2 0.2\n4 0.7 0.7 0.1 0.1\n", encoding="utf-8")
        # d: greening 直接映射 id 3
        (self.rf / "valid" / "labels" / "d.txt").write_text(
            "3 0.5 0.5 0.4 0.4\n", encoding="utf-8")

    def _snapshot(self, root: Path):
        return {str(p.relative_to(root)): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file()}

    def test_merge_polygon_to_bbox_and_remap(self):
        self._prepare_dst()
        self._build_rf_dataset()
        before = self._snapshot(self.rf)
        proc = run_cmd(ROOT / "merge_roboflow.py",
                       "--rf-src", str(self.rf), "--dst", str(self.dst))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        a = (self.dst / "labels" / "train" / "rf_a.txt").read_text().strip()
        parts = a.split()
        self.assertEqual(len(parts), 5)
        self.assertEqual(int(parts[0]), 1)
        xc, yc, w, h = map(float, parts[1:])
        self.assertAlmostEqual(xc, 0.4, places=5)
        self.assertAlmostEqual(yc, 0.35, places=5)
        self.assertAlmostEqual(w, 0.6, places=5)
        self.assertAlmostEqual(h, 0.5, places=5)

        c = (self.dst / "labels" / "train" / "rf_c.txt").read_text().strip().splitlines()
        self.assertEqual(len(c), 1)
        self.assertTrue(c[0].startswith("2 "))

        d = (self.dst / "labels" / "val" / "rf_d.txt").read_text().strip().split()
        self.assertEqual(len(d), 5)
        self.assertEqual(int(d[0]), 3)
        self.assertEqual(list(map(float, d[1:])), [0.5, 0.5, 0.4, 0.4])

        self.assertFalse((self.dst / "images" / "train" / "rf_b.jpg").exists())
        self.assertFalse((self.dst / "labels" / "train" / "rf_b.txt").exists())

        merged_imgs = list((self.dst / "images" / "train").glob("rf_*.jpg")) + \
            list((self.dst / "images" / "val").glob("rf_*.jpg"))
        for img in merged_imgs:
            self.assertTrue(img.name.startswith("rf_"))
            lbl = self.dst / "labels" / img.parent.name / (img.stem + ".txt")
            self.assertTrue(lbl.exists(), f"{img.name} 缺少同名标签")

        # 4 类体系之外无标注残留：所有 rf_ 标签行首值 ∈ 0-3 且为五值
        for lbl in list((self.dst / "labels").rglob("rf_*.txt")):
            for line in lbl.read_text().strip().splitlines():
                parts = line.split()
                self.assertEqual(len(parts), 5, f"{lbl.name}: {line}")
                self.assertIn(int(parts[0]), {0, 1, 2, 3})

        # 源目录只读
        after = self._snapshot(self.rf)
        self.assertEqual(before, after)

        # 统计报告重新输出，含 rf_ 来源计数
        stats = (self.dst / "dataset_stats.txt").read_text()
        self.assertIn("rf_ 来源计数", stats)
        self.assertIn("rf_total", stats)
        self.assertIn("本次合并: 3 张图片", proc.stdout)

    def test_missing_split_dir_skipped(self):
        self._prepare_dst()
        self._build_rf_dataset()
        proc = run_cmd(ROOT / "merge_roboflow.py",
                       "--rf-src", str(self.rf), "--dst", str(self.dst))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("[跳过]", proc.stdout)
        self.assertIn("test", proc.stdout)

    def test_invalid_rf_src_error(self):
        self._prepare_dst()
        proc = run_cmd(ROOT / "merge_roboflow.py",
                       "--rf-src", str(self.tmp / "no_dir"), "--dst", str(self.dst))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("rf-src", proc.stdout)

    def test_invalid_dst_structure_error(self):
        self._build_rf_dataset()
        bad_dst = self.tmp / "bad_dst"
        bad_dst.mkdir()
        before = self._snapshot(bad_dst)
        proc = run_cmd(ROOT / "merge_roboflow.py",
                       "--rf-src", str(self.rf), "--dst", str(bad_dst))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(before, self._snapshot(bad_dst))


if __name__ == "__main__":
    unittest.main()