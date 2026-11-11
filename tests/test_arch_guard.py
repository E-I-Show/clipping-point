"""層の分離の検査（tools/arch_check.py）そのもののテスト。

持ち込む書き方を文字列で与え、検査が拾うことを確かめる。出荷するコードがいま違反していないことも見る。
"""
import pytest

import arch_check
from conftest import ROOT

# cp_core に、エンジン、ブラウザ、上の層、乱数、実時間を持ち込む書き方。どれも1件以上拾われること。
CORE_VIOLATIONS = {
    "top_level_import": "import pyxel\n",
    "import_as": "import pyxel as px\n",
    "import_among_others": "import math, pyxel\n",
    "from_import": "from pyxel import btn\n",
    "submodule_import": "import pyxel.cube\n",
    "lazy_import_in_uncalled_function": "def debug_draw():\n    import pyxel\n    pyxel.cls(0)\n",
    "guarded_optional_import": "try:\n    import pyxel\nexcept ImportError:\n    pyxel = None\n",
    "importlib": "import importlib\npx = importlib.import_module('pyxel')\n",
    "dunder_import_with_built_name": "px = __import__('py' + 'xel')\n",
    "dunder_import_through_alias": "load = __import__\npx = load('pyxel')\n",
    "exec_string": "exec('import pyxel')\n",
    "eval_string": "px = eval('__imp' + 'ort__')('pyxel')\n",
    "getattr_builtins_in_uncalled_function": (
        "def sneak():\n    import builtins\n    return getattr(builtins, '__imp' + 'ort__')('pyxel')\n"
    ),
    "builtins_dict": "px = __builtins__['__import__']('pyxel')\n",
    "sys_modules": "import sys\npx = sys.modules.get('pyxel')\n",
    "browser_js": "import js\n",
    "browser_pyodide": "from pyodide.ffi import create_proxy\n",
    "adapter_layer": "from cp_app.canvas_pyxel import execute\n",
    "ui_layer_from_core": "from cp_ui.canvas import Canvas\n",
    "relative_import_out_of_the_layer": "from ..cp_app import app\n",
    "stdlib_random": "import random\n",
    "stdlib_random_from": "from random import random\n",
    "stdlib_time": "import time\n",
    "stdlib_time_from": "from time import perf_counter\n",
    "stdlib_datetime": "import datetime\n",
    "builtin_hash": "BAD = hash('x')\n",
    "module_not_on_the_list": "import socket\n",
}

# 許される書き方。1件も拾われないこと（何でも落とす検査になっていないことの確かめ）。
CORE_CLEAN = {
    "empty": "",
    "allowed_stdlib": "import math\nimport json\nfrom dataclasses import dataclass\n",
    "own_package_absolute": "from cp_core.fixed_loop import RenderGate\n",
    "own_package_relative": "from . import fixed_loop\nfrom .sim import Sim\n",
    "words_in_strings_and_comments": "# import pyxel\nNOTE = 'import pyxel, random, time'\n",
    "attribute_named_like_a_banned_name": "import hashlib\nDIGEST = hashlib.sha256(b'x').hexdigest()\n",
}


@pytest.mark.parametrize("name", sorted(CORE_VIOLATIONS))
def test_arch_detects_each_way_of_breaking_the_core_layer(name):
    problems = arch_check.check_source(CORE_VIOLATIONS[name], "cp_core", "cp_core/planted.py")
    assert problems, f"拾えなかった書き方：{name}"
    assert all(problem.startswith("cp_core/planted.py:") for problem in problems)


@pytest.mark.parametrize("name", sorted(CORE_CLEAN))
def test_arch_accepts_allowed_code_in_the_core_layer(name):
    assert arch_check.check_source(CORE_CLEAN[name], "cp_core") == []


def test_arch_ui_layer_may_call_core_but_not_the_adapter_or_the_engine():
    assert arch_check.check_source("from cp_core.sim import Sim\nfrom cp_ui import canvas\n", "cp_ui") == []
    assert arch_check.check_source("from cp_app import canvas_pyxel\n", "cp_ui")
    assert arch_check.check_source("import pyxel\n", "cp_ui")
    assert arch_check.check_source("import time\n", "cp_ui")


def test_arch_relative_import_inside_a_subpackage_stays_in_the_layer():
    # cp_core/vehicle/model.py から見た「..」は cp_core。層の中なので許す。
    assert arch_check.check_source("from ..sim import Sim\n", "cp_core", "cp_core/vehicle/model.py", ("vehicle",)) == []
    # 「...」は cp_core の外へ出る。
    assert arch_check.check_source("from ...cp_app import app\n", "cp_core", "cp_core/vehicle/model.py", ("vehicle",))


def test_arch_reports_the_line_of_each_violation_in_order():
    source = "import math\nimport pyxel\n\n\ndef late():\n    import random\n"
    problems = arch_check.check_source(source, "cp_core", "cp_core/x.py")
    assert [problem.split(":")[1] for problem in problems] == ["2", "6"]


def test_arch_reports_a_syntax_error_as_a_problem():
    assert arch_check.check_source("def broken(:\n", "cp_core")


def test_arch_rejects_an_unknown_layer_name():
    with pytest.raises(ValueError):
        arch_check.check_source("", "cp_app")


def test_arch_tree_check_finds_a_module_nobody_imports(tmp_path):
    # まだ誰も読み込んでいないモジュールは、実行時の見張りでは見えない。ソースの検査なら見える。
    for package in ("cp_core", "cp_ui"):
        (tmp_path / package).mkdir()
        (tmp_path / package / "__init__.py").write_text("", encoding="utf-8")
    assert arch_check.check_tree(tmp_path) == (2, [])
    (tmp_path / "cp_core" / "debug_overlay.py").write_text("import pyxel\n", encoding="utf-8")
    files, problems = arch_check.check_tree(tmp_path)
    assert files == 3
    assert len(problems) == 1 and problems[0].startswith("cp_core/debug_overlay.py:1:")


def test_arch_tree_check_counts_zero_files_when_the_layers_are_missing(tmp_path):
    assert arch_check.check_tree(tmp_path) == (0, [])


def test_arch_shipped_code_has_no_violation():
    files, problems = arch_check.check_tree(ROOT / "clipping_point")
    assert files >= 5
    assert problems == []
