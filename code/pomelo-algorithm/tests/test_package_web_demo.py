"""Web Demo 交付打包组件测试（tests/test_package_web_demo.py）。

覆盖 spec 5.8 的 9 个用例，红绿契约（spec 5.8.3-1）：
- 用例 1/2/5/6 依赖前置任务 A/F/G 落地（prescribe_prompt.py / sqlite_store.py /
  web_demo/ 三件套）；前置未落地时这些用例**预期红**——红色报错信息即
  5.1 的中文缺失清单，直接指引"先做前置任务"。
  处置约定：完成前置任务后再验收本组件，禁止为让测试变绿而
  放宽硬校验或删用例。
- 用例 3/4/7/8/9 与"完整打包成功"解耦（design 决策 D11），前置未落地时恒绿。

全部用例零外网、零仓库写：out 目录与 zip 一律落 tempfile 临时目录，
build_package 的 project_root 参数注入临时目录（否则会写真实 .gitignore）。
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.package_web_demo import (  # noqa: E402
    MissingPrerequisiteError,
    build_package,
    is_excluded,
    select_sample_images,
    write_launchers,
)

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parent.parent
VAL_DIR = PROJECT_ROOT / "dataset" / "pomelo_yolo" / "images" / "val"


class TestPackageWebDemo(unittest.TestCase):
    """打包组件 9 用例（红绿契约见模块 docstring）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pkg_demo_"))
        # out 目录命名刻意带 web-demo：zip 内容根 = 目录名（6.6-3），
        # 这样 zip 断言能直接命中 "web-demo/data/.keep" 形态。
        self.out = self.tmp / "web-demo"
        # 假项目根：让 update_gitignore 落 tmp，绝不污染仓库真实 .gitignore。
        self.project = self.tmp / "fake_project"
        self.project.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- 用例 1：防漏拷守护（依赖前置 A/F/G 落地） ----------

    def test_copy_whitelist_guards_core_modules(self):
        """用例 1：app/ 必含 agent/orchestrator.py 与 agent/prescribe_prompt.py。

        守护语义：故意从 PACKAGE_ITEMS 剔除任一清单文件时，本用例必红
        （防漏拷）；前置任务 A（prescribe_prompt）未落地时同样红——
        报错信息即缺失清单，指引先完成前置实现。
        """
        rc = build_package(ROOT, self.out, VAL_DIR, self.project, None)
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "app" / "agent" / "orchestrator.py").is_file())
        self.assertTrue((self.out / "app" / "agent" / "prescribe_prompt.py").is_file())

    # ---------- 用例 2：交付包自包含 import（依赖前置落地） ----------

    def test_delivered_app_imports_agent_orchestrator(self):
        """用例 2：把拷出的 app/ 加入 sys.path 后 import agent.orchestrator 不报错。

        必须用子进程隔离——orchestrator 模块加载时会向 sys.path 自注入
        源码根路径，直接 import 会污染 pytest 进程的模块查找顺序。
        """
        rc = build_package(ROOT, self.out, VAL_DIR, self.project, None)
        self.assertEqual(rc, 0)
        app_dir = self.out / "app"
        code = f"import sys; sys.path.insert(0, r'{app_dir}'); import agent.orchestrator"
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    # ---------- 用例 3：start.bat GBK 解码（不依赖前置，恒绿） ----------

    def test_start_bat_is_gbk_decodable_with_chinese(self):
        """用例 3：start.bat 可被 GBK 解码且中文提示完整（cmd 代码页 936 下不乱码）。"""
        write_launchers(self.tmp)
        # 关键点：read_text(encoding="gbk") 不抛 UnicodeDecodeError 本身就是断言。
        text = (self.tmp / "start.bat").read_text(encoding="gbk")
        self.assertIn("启动", text)
        self.assertIn("7860", text)
        self.assertTrue((self.tmp / "start.ps1").is_file())

    # ---------- 用例 4：requirements 合法性（不依赖前置，恒绿） ----------

    def test_requirements_lines_are_valid_package_names(self):
        """用例 4：requirements.txt 恰 5 行，每行合法包名（非空、无注释、无空格）。"""
        write_launchers(self.tmp)
        lines = (self.tmp / "requirements.txt").read_text(encoding="ascii").splitlines()
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertTrue(line, "不允许空行污染")
            self.assertNotIn("#", line, "不允许注释行")
            self.assertNotIn(" ", line, "不允许行内空格")
        # uvicorn[standard] 的 extras 语法合法，同样不含空格与注释。
        self.assertIn("uvicorn[standard]", lines)

    # ---------- 用例 5：zip 完整性（依赖前置落地） ----------

    def test_zip_excludes_sensitive_and_keeps_empty_dirs(self):
        """用例 5：zip 可打开，无敏感/临时文件，data 与 uploads 的 .keep 在名单内。

        zip_path 刻意指向 tmp 内——绝不写项目根（测试污染防护）。
        """
        zip_path = self.tmp / "web-demo-test.zip"
        rc = build_package(ROOT, self.out, VAL_DIR, self.project, zip_path)
        self.assertEqual(rc, 0)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        for name in names:
            self.assertNotIn("__pycache__", name, name)
            self.assertNotIn("token_usage.jsonl", name, name)
            self.assertNotIn(".env", name, name)
            self.assertFalse(Path(name).match("eval_*.json"), name)
        self.assertTrue(any(n.endswith("data/.keep") for n in names), "data/.keep 应在 zip 内")
        self.assertTrue(any(n.endswith("uploads/.keep") for n in names), "uploads/.keep 应在 zip 内")

    # ---------- 用例 6：README 关键字（依赖前置落地） ----------

    def test_readme_mentions_start_bat_and_api_key(self):
        """用例 6：README 含 start.bat 与 MAAS_API_KEY 两个关键字。"""
        rc = build_package(ROOT, self.out, VAL_DIR, self.project, None)
        self.assertEqual(rc, 0)
        readme = (self.out / "README.md").read_text(encoding="utf-8")
        self.assertIn("start.bat", readme)
        self.assertIn("MAAS_API_KEY", readme)
        # Key 只允许以环境变量名形式出现在设置说明语境，不允许出现真实值形态。
        self.assertIn("setx", readme)

    # ---------- 用例 7：缺文件报错（不依赖前置，恒绿——5.1 核心行为固化） ----------

    def test_missing_prerequisites_error_and_no_partial_output(self):
        """用例 7：残缺源树触发缺文件报错（中文清单 + 前置任务提示 + 无半成品）。

        与用例 1 互补：1 守护"齐了别漏拷"，7 守护"缺了必报错"。
        Arrange 只造清单外的零散文件（顶层两个占位 + 空目录），
        使缺失清单恰为 5 个前置产物路径。
        """
        fake_src = self.tmp / "fake_src"
        (fake_src / "agent").mkdir(parents=True)
        (fake_src / "prescription").mkdir(parents=True)
        (fake_src / "expert_knowledge.py").write_text("# 占位", encoding="utf-8")
        (fake_src / "labelmap.py").write_text("# 占位", encoding="utf-8")
        out = self.tmp / "should_not_exist"
        with self.assertRaises(MissingPrerequisiteError) as ctx:
            build_package(fake_src, out, self.tmp, self.project, None)
        message = str(ctx.exception)
        for path in ("prescribe_prompt.py", "sqlite_store.py", "web_demo/server.py",
                     "web_demo/offline_client.py", "web_demo/static"):
            self.assertIn(path, message)
        self.assertIn("前置任务", message, "报错须带前置任务提示（修复指引）")
        # 校验先于一切写盘动作：报错退出时不产生半成品 out 目录。
        self.assertFalse(out.exists())

    # ---------- 用例 8：样例图前缀（不依赖前置，恒绿） ----------

    def test_select_sample_images_prefix_hits_and_soft_warning(self):
        """用例 8：五前缀各命中 1 张且文件名保留原前缀；假目录走软警告口径。"""
        result = select_sample_images(VAL_DIR)
        self.assertEqual(len(result.picked), 5)
        self.assertEqual(result.missing, ())
        from tools.package_web_demo import SAMPLE_IMAGE_SPECS  # noqa: PLC0415
        for spec in SAMPLE_IMAGE_SPECS:
            self.assertIn(spec.prefix, result.picked)
            self.assertTrue(
                result.picked[spec.prefix].name.startswith(spec.prefix),
                "文件名保留红线：拷贝前源文件名必须以类别前缀开头",
            )
        # val 目录整体缺失：picked 为空 + 全五前缀进 missing（软警告，非异常）。
        empty = select_sample_images(self.tmp / "no_such_dir")
        self.assertEqual(empty.picked, {})
        self.assertEqual(len(empty.missing), 5)

    # ---------- 用例 9：排除规则（谓词级直测，恒绿；前置落地后可升级） ----------

    def test_exclude_predicate_blocks_sensitive_and_cache(self):
        """用例 9：排除谓词对敏感/临时路径全排除，正常源码不误伤。

        当前为谓词级直测（不依赖前置 G 落地）。升级路径：web_demo/static
        落地后，可升级为完整打包 + zip 双路验证（交付目录与 namelist
        均无 .pyc / .env）。
        """
        # 正例：目录类 / 文件类 / 密钥类 / 评估残留，逐一必须被排除。
        self.assertTrue(is_excluded(PurePosixPath("agent/__pycache__/x.pyc")))
        self.assertTrue(is_excluded(PurePosixPath("web_demo/static/__pycache__/app.pyc")))
        self.assertTrue(is_excluded(PurePosixPath(".env")))
        self.assertTrue(is_excluded(PurePosixPath("config/.env.production")))
        self.assertTrue(is_excluded(PurePosixPath("token_usage.jsonl")))
        self.assertTrue(is_excluded(PurePosixPath("agent/eval_report.json")))
        self.assertTrue(is_excluded(PurePosixPath("secret_dir/anything.py")))
        self.assertTrue(is_excluded(PurePosixPath("weights/best.pt")))
        # 反例：17 项清单内的正常文件，一律不得误伤。
        self.assertFalse(is_excluded(PurePosixPath("agent/orchestrator.py")))
        self.assertFalse(is_excluded(PurePosixPath("agent/prescribe_prompt.py")))
        self.assertFalse(is_excluded(PurePosixPath("prescription/sqlite_store.py")))
        self.assertFalse(is_excluded(PurePosixPath("web_demo/server.py")))
        self.assertFalse(is_excluded(PurePosixPath("web_demo/static/app.js")))
        self.assertFalse(is_excluded(PurePosixPath("labelmap.py")))


if __name__ == "__main__":
    unittest.main()