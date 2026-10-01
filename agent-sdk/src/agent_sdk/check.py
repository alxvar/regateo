"""The submission check: what an agent version's code may import and call (docs/06-agent-contract.md §5).

An agent runs inside the engine's process, next to its opponents and the referee, so isolation can't rest
on the files a builder session was shown alone. This static check rejects code that could reach outside
the agent: imports beyond the SDK, a short standard-library list and its own architecture; file, network
and process access; and the dynamic tricks that get around a static check (eval, `__import__`, dunder
attributes, getattr with a computed name). It reads the code, it doesn't run it, so it is a strong
filter, not a sandbox: running each agent in its own process is the step after it (docs/06 §5).

The engine runs it on every agent version before building it; a builder can run it first:
`regateo-agent check agents/<architecture>/<version>`.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# Standard library and third-party modules an agent may import. Anything else is refused.
ALLOWED_MODULES = {
    "__future__", "abc", "asyncio", "bisect", "collections", "copy", "dataclasses", "decimal", "enum",
    "fractions", "functools", "hashlib", "heapq", "itertools", "json", "math", "operator", "pathlib",
    "random", "re", "secrets", "statistics", "string", "textwrap", "typing", "pydantic",
}
TEST_MODULES = {"pytest"}
# SDK modules only tests and tooling may use: loading other packages, or the offline stand-ins.
SDK_TOOLING = {"agent_sdk.packages", "agent_sdk.check", "agent_sdk.cli"}
SDK_TEST_ONLY = {"agent_sdk.testing"}

FORBIDDEN_CALLS = {
    "open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "breakpoint", "input",
    "memoryview", "setattr", "delattr",
}
# Methods that touch the file system (on pathlib paths); allowed paths only build names, e.g. for PromptDir.
FILE_METHODS = {
    "read_text", "read_bytes", "write_text", "write_bytes", "open", "iterdir", "glob", "rglob", "unlink",
    "mkdir", "rmdir", "rename", "touch", "symlink_to", "hardlink_to", "exists", "stat", "lstat", "is_file",
    "is_dir", "chmod", "owner", "expanduser", "home", "cwd", "walk",
}
ALLOWED_DUNDERS = {"__name__", "__init__", "__post_init__", "__file__", "__all__", "__repr__", "__str__",
                   "__eq__", "__hash__", "__lt__", "__le__", "__gt__", "__ge__", "__len__", "__iter__",
                   "__contains__", "__getitem__", "__call__", "__enter__", "__exit__", "__aenter__", "__aexit__",
                   "__future__", "__doc__", "__slots__", "__bool__", "__add__", "__sub__"}
FORBIDDEN_NAMES = {"true_rules", "__builtins__", "__loader__", "__spec__"}
# Attributes that reach forbidden modules through allowed ones (typing.sys, pydantic.main.sys), frames, or
# processes and sockets through asyncio.
FORBIDDEN_ATTRS = {
    "sys", "os", "builtins", "importlib", "subprocess", "inspect", "gc", "io", "socket", "shutil", "ctypes",
    "modules", "_getframe", "f_globals", "f_locals", "f_back", "f_builtins", "gi_frame", "cr_frame", "tb_frame",
    "create_subprocess_exec", "create_subprocess_shell", "open_connection", "open_unix_connection", "start_server",
    "start_unix_server", "to_thread", "get_event_loop", "get_running_loop", "new_event_loop", "run_in_executor",
    "parse_file", "fromfile",
}


@dataclass(frozen=True)
class Problem:
    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.message}"


def check_version(version_dir: str | Path) -> list[Problem]:
    """Every problem in an agent version (`agents/<arch>/<version>`) and its architecture's `lib/`."""
    version_dir = Path(version_dir).resolve()
    arch_dir = version_dir.parent
    problems: list[Problem] = []
    for base in (version_dir, arch_dir / "lib"):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            is_test = "tests" in path.relative_to(base).parts
            problems += check_file(path, arch_dir, is_test=is_test)
    return problems


def check_file(path: Path, arch_dir: Path, *, is_test: bool = False) -> list[Problem]:
    rel = _rel(path, arch_dir)
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as e:
        return [Problem(rel, e.lineno or 0, f"syntax error: {e.msg}")]
    return _Checker(rel, path, arch_dir, is_test).run(tree)


def _rel(path: Path, arch_dir: Path) -> str:
    try:
        return path.relative_to(arch_dir.parent).as_posix()
    except ValueError:
        return str(path)


class _Checker(ast.NodeVisitor):
    def __init__(self, rel: str, path: Path, arch_dir: Path, is_test: bool):
        self.rel, self.path, self.arch_dir, self.is_test = rel, path, arch_dir, is_test
        self.problems: list[Problem] = []
        self.prompt_dir_names = {"PromptDir"}

    def run(self, tree: ast.AST) -> list[Problem]:
        self.visit(tree)
        return self.problems

    def bad(self, node: ast.AST, message: str) -> None:
        self.problems.append(Problem(self.rel, getattr(node, "lineno", 0), message))

    # Imports

    def _module_ok(self, module: str) -> str | None:
        """Why `module` may not be imported, or None."""
        top = module.split(".")[0]
        if module in SDK_TEST_ONLY or any(module.startswith(m + ".") for m in SDK_TEST_ONLY):
            return None if self.is_test else f"{module} is for tests only"
        if module in SDK_TOOLING:
            return f"{module} is tooling, not for agents"
        if top == "agent_sdk":
            return None
        if top == "regateo_agents":
            own = f"regateo_agents.{self.arch_dir.name}"
            if self.is_test and (module == own or module.startswith(own + ".")):
                return None
            return "import your own architecture with relative imports (from ..lib import x)"
        if top in ALLOWED_MODULES or (self.is_test and top in TEST_MODULES):
            return None
        if top == "regateo":
            return "agents can't import the engine"
        return f"module {module!r} is not allowed (allowed: agent_sdk, your architecture, {sorted(ALLOWED_MODULES)})"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if why := self._module_ok(alias.name):
                self.bad(node, why)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            # A relative import may reach the architecture's folder (from ..lib import x), not above it.
            target = self.path.parent
            for _ in range(node.level - 1):
                target = target.parent
            try:
                target.resolve().relative_to(self.arch_dir.resolve())
            except ValueError:
                self.bad(node, "a relative import may not leave its architecture")
            return
        module = node.module or ""
        if why := self._module_ok(module):
            self.bad(node, why)
            return
        for alias in node.names:
            if alias.name == "PromptDir" and alias.asname:
                self.prompt_dir_names.add(alias.asname)
        if module == "agent_sdk":
            for alias in node.names:
                if f"agent_sdk.{alias.name}" in SDK_TOOLING or (
                        f"agent_sdk.{alias.name}" in SDK_TEST_ONLY and not self.is_test):
                    self.bad(node, f"agent_sdk.{alias.name} is not for agents")

    # Calls, names and attributes

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        if isinstance(f, ast.Name) and f.id in FORBIDDEN_CALLS:
            self.bad(node, f"{f.id}() is not allowed")
        if isinstance(f, ast.Name) and f.id == "getattr" and len(node.args) >= 2:
            name = node.args[1]
            if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                self.bad(node, "getattr() needs a literal attribute name")
            elif _dunder(name.value) and name.value not in ALLOWED_DUNDERS:
                self.bad(node, f"getattr(..., {name.value!r}) is not allowed")
        if isinstance(f, ast.Attribute) and f.attr in FILE_METHODS:
            self.bad(node, f".{f.attr}() touches the file system; agents may not")
        if (isinstance(f, ast.Name) and f.id in self.prompt_dir_names) or (
                isinstance(f, ast.Attribute) and f.attr == "PromptDir"):
            self._prompt_dir(node)
        self.generic_visit(node)

    def _prompt_dir(self, node: ast.Call) -> None:
        """A version's prompts live next to its code: exactly PromptDir(Path(__file__).parent / "prompts")
        (more plain folder names may follow). Any other folder could be another agent's, or the engine's."""
        args = [*node.args, *(k.value for k in node.keywords)]
        if len(args) != 1 or not _beside_file(args[0]):
            self.bad(node, 'PromptDir must be PromptDir(Path(__file__).parent / "<folder>")')

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _dunder(node.attr) and node.attr not in ALLOWED_DUNDERS:
            self.bad(node, f"attribute {node.attr} is not allowed")
        if node.attr in FORBIDDEN_NAMES:
            self.bad(node, f"{node.attr} is not available to agents")
        elif node.attr in FORBIDDEN_ATTRS:
            self.bad(node, f"attribute {node.attr} is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES:
            self.bad(node, f"{node.id} is not available to agents")
        elif _dunder(node.id) and node.id not in ALLOWED_DUNDERS:
            self.bad(node, f"name {node.id} is not allowed")


def _beside_file(node: ast.expr) -> bool:
    """`Path(__file__).parent / "a" / "b"`, with plain folder names."""
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        r = node.right
        if not (isinstance(r, ast.Constant) and isinstance(r.value, str) and r.value
                and not any(c in r.value for c in "/\\") and r.value not in (".", "..")):
            return False
        node = node.left
    return (isinstance(node, ast.Attribute) and node.attr == "parent" and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name) and node.value.func.id == "Path"
            and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "__file__")


def _dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def main(argv: list[str] | None = None) -> int:
    folders = argv if argv is not None else sys.argv[1:]
    if not folders:
        print("usage: regateo-agent check agents/<architecture>/<version> [...]", file=sys.stderr)
        return 2
    failed = False
    for folder in folders:
        problems = check_version(folder)
        for p in problems:
            print(p)
        print(f"{folder}: {'ok' if not problems else f'{len(problems)} problem(s)'}")
        failed |= bool(problems)
    return 1 if failed else 0
