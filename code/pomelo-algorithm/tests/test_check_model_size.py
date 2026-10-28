import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_check(file: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_model_size.py"),
         "--file", file, *extra],
        capture_output=True, text=True)


class TestCheckModelSize(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pomelo_size_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make(self, name: str, size: int) -> str:
        p = self.tmp / name
        p.write_bytes(b"\0" * size)
        return str(p)

    def test_quant_within_limit(self):
        f = self._make("yolov5s_pomelo_quant.ms", 1024)
        proc = run_check(f)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("通过", proc.stdout)

    def test_quant_over_limit_exit_nonzero(self):
        f = self._make("yolov5s_pomelo_quant.ms", 8 * 1024 * 1024)
        proc = run_check(f)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("超限", proc.stdout)

    def test_fp32_within_limit(self):
        f = self._make("yolov5s_pomelo.ms", 1024)
        proc = run_check(f)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_fp32_over_limit(self):
        f = self._make("yolov5s_pomelo.ms", 21 * 1024 * 1024)
        proc = run_check(f)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("超限", proc.stdout)

    def test_explicit_limit_mb_override(self):
        f = self._make("yolov5s_pomelo_quant.ms", 1024)
        proc = run_check(f, "--limit-mb", "0.0001")
        self.assertNotEqual(proc.returncode, 0)
        proc = run_check(f, "--limit-mb", "1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_unknown_type_error(self):
        f = self._make("unknown_model.bin", 1024)
        proc = run_check(f)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("无法判定", proc.stdout)

    def test_missing_file_error(self):
        proc = run_check(str(self.tmp / "not_exist.ms"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("不存在", proc.stdout)


if __name__ == "__main__":
    unittest.main()