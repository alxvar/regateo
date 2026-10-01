from pathlib import Path

import pytest

from agent_sdk import packages
from agent_sdk.check import check_version
from agent_sdk.cli import main


def version(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        p = tmp_path / "arch" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path / "arch" / "v1"


GOOD = {
    "lib/__init__.py": "",
    "lib/util.py": "import re\nfrom agent_sdk.prices import fmt_price\n",
    "v1/__init__.py": "from pathlib import Path\n\nfrom agent_sdk import PromptDir\n\nfrom ..lib import util\n"
                      "PROMPTS = PromptDir(Path(__file__).parent / 'prompts')\n\n"
                      "def build(config, view, ctx):\n    return type(ctx).__name__\n",
    "v1/tests/test_it.py": "import pytest\nfrom agent_sdk.testing import FakeLLM\n"
                           "from regateo_agents.arch.v1 import build\n",
}


def test_clean_version_passes(tmp_path):
    assert check_version(version(tmp_path, GOOD)) == []


@pytest.mark.parametrize("code,why", [
    ("import os", "not allowed"),
    ("from subprocess import run", "not allowed"),
    ("import regateo.referee", "can't import the engine"),
    ("from regateo_agents.other.v1 import build", "relative imports"),
    ("from ...other.v1 import build", "may not leave its architecture"),
    ("from agent_sdk import packages", "not for agents"),
    ("from agent_sdk.testing import FakeLLM", "tests only"),
    ("x = open('/etc/passwd')", "open() is not allowed"),
    ("x = eval('1')", "eval() is not allowed"),
    ("x = __import__('os')", "__import__() is not allowed"),
    ("x = getattr(object, 'x' + 'y')", "literal attribute name"),
    ("x = getattr(object, '__subclasses__')", "not allowed"),
    ("x = ().__class__.__bases__", "attribute __class__ is not allowed"),
    ("x = __builtins__", "not available"),
    ("x = ctx.true_rules", "not available"),
    ("import typing\nx = typing.sys.modules", "attribute sys is not allowed"),
    ("import asyncio\nx = asyncio.create_subprocess_shell('ls')", "not allowed"),
    ("from pathlib import Path\nx = Path('/etc').read_text()", "file system"),
    ("from pathlib import Path\nfrom agent_sdk import PromptDir\nP = PromptDir(Path(__file__).parents[3])",
     "PromptDir"),
    ("from pathlib import Path\nfrom agent_sdk import PromptDir as D\nP = D(Path(__file__).parent / '..')",
     "PromptDir"),
    ("from agent_sdk import PromptDir\nP = PromptDir('/home/x/engine/prompts')", "PromptDir"),
])
def test_each_rule(tmp_path, code, why):
    problems = check_version(version(tmp_path, {**GOOD, "v1/bad.py": code + "\n"}))
    assert problems and all(p.file == "arch/v1/bad.py" for p in problems)
    assert any(why in p.message for p in problems), [str(p) for p in problems]


def test_cli(tmp_path, capsys):
    assert main(["check", str(version(tmp_path, GOOD))]) == 0
    assert main(["check", str(version(tmp_path, {**GOOD, "v1/bad.py": "import os\n"}))]) == 1
    assert "arch/v1/bad.py:1" in capsys.readouterr().out


def test_prompt_dir_stays_in_its_architecture(tmp_path):
    files = {**GOOD, "v1/__init__.py": "from pathlib import Path\n\nfrom agent_sdk import PromptDir\n\n"
                                       "def build(config, view, ctx):\n"
                                       "    return PromptDir(Path(__file__).parent.parent.parent / 'other')\n",
             "v1/prompts/x.v1.md": "hi"}
    root = version(tmp_path, files).parent.parent
    (root / "other").mkdir()
    packages.mount(root)
    with pytest.raises(PermissionError):
        packages.load("arch/v1").build(None, None, None)
