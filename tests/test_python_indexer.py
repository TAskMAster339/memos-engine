from memos.indexer.python import PythonIndexer


def _I():
    return PythonIndexer()


def test_parse_function():
    src = "def foo():\n    return 1\n"
    r = _I().parse(src, "mod.py")
    assert len(r.symbols) == 1
    s = r.symbols[0]
    assert s.name == "foo"
    assert s.kind == "function"
    assert s.exported is True
    assert s.start_line == 1
    assert s.end_line == 2


def test_parse_private_function():
    src = "def _helper():\n    return 1\n"
    r = _I().parse(src, "mod.py")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "_helper"
    assert r.symbols[0].exported is False


def test_parse_public_function():
    src = "def greet():\n    pass\n"
    r = _I().parse(src, "mod.py")
    assert r.symbols[0].exported is True


def test_parse_method():
    src = "class User:\n    def get_name(self):\n        return self.name\n"
    r = _I().parse(src, "mod.py")
    methods = [s for s in r.symbols if s.kind == "method"]
    assert len(methods) == 1
    s = methods[0]
    assert s.name == "get_name"
    assert s.parent_name == "User"


def test_parse_class():
    src = "class User:\n    pass\n"
    r = _I().parse(src, "mod.py")
    assert len(r.symbols) == 1
    s = r.symbols[0]
    assert s.name == "User"
    assert s.kind == "class"
    assert s.exported is True


def test_parse_decorated_function():
    src = "@staticmethod\ndef foo():\n    pass\n"
    r = _I().parse(src, "mod.py")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "foo"
    assert r.symbols[0].kind == "function"


def test_parse_module_const():
    src = "X = 1\n"
    r = _I().parse(src, "mod.py")
    consts = [s for s in r.symbols if s.kind == "const"]
    assert len(consts) == 1
    assert consts[0].name == "X"
    assert consts[0].exported is True


def test_parse_module_var():
    src = "x = 1\n"
    r = _I().parse(src, "mod.py")
    var_syms = [s for s in r.symbols if s.kind == "variable"]
    assert len(var_syms) == 1
    assert var_syms[0].name == "x"
    assert var_syms[0].exported is True


def test_parse_calls():
    src = "def f():\n    foo()\n"
    r = _I().parse(src, "mod.py")
    assert len(r.calls) == 1
    assert r.calls[0].callee_name == "foo"
    assert r.calls[0].caller_name == "f"
    assert r.calls[0].line == 2


def test_parse_method_call():
    src = "class C:\n    def m(self):\n        self.foo()\n"
    r = _I().parse(src, "mod.py")
    calls = [c for c in r.calls if c.callee_name == "self.foo"]
    assert len(calls) == 1
    assert calls[0].caller_name == "C.m"


def test_parse_import_simple():
    src = "import os\n"
    r = _I().parse(src, "mod.py")
    assert len(r.imports) == 1
    assert r.imports[0].imported_path == "os"


def test_parse_import_as():
    src = "import os as o\n"
    r = _I().parse(src, "mod.py")
    assert len(r.imports) == 1
    assert r.imports[0].imported_path == "os"


def test_parse_from_import():
    src = "from os import path\n"
    r = _I().parse(src, "mod.py")
    assert len(r.imports) == 1
    assert r.imports[0].imported_path == "os"


def test_parse_relative_import():
    src = "from .utils import helper\n"
    r = _I().parse(src, "mod.py")
    assert len(r.imports) == 1
    assert r.imports[0].imported_path == ".utils"


def test_parse_signature():
    src = 'def foo(x: int, y: str = "a") -> bool:\n    return True\n'
    r = _I().parse(src, "mod.py")
    sig = r.symbols[0].signature
    assert sig is not None
    assert sig.startswith("def foo")
    assert "x: int" in sig
    assert "bool" in sig
    assert "{" not in sig
    assert sig.endswith(":") or " -> bool:" in sig


def test_parse_async_function():
    src = "async def foo():\n    pass\n"
    r = _I().parse(src, "mod.py")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "foo"
    assert r.symbols[0].kind == "function"
    assert r.symbols[0].exported is True


def test_content_hash_differs():
    a = _I().parse("def foo():\n    return 1\n", "a.py")
    b = _I().parse("def foo():\n    return 2\n", "b.py")
    assert a.symbols[0].content_hash != b.symbols[0].content_hash


def test_parse_realistic_file():
    src = """
import sys
from os import path

PUBLIC_CONST = 42

class Config:
    port: int

    def get_port(self) -> int:
        return self.port

def greet(name: str) -> str:
    return f"hello {name}"

def main():
    cfg = Config()
    msg = greet("world")
    print(msg)
    sys.exit(0)
"""
    r = _I().parse(src, "main.py")
    symbols = {s.name: s for s in r.symbols}

    assert "Config" in symbols
    assert symbols["Config"].kind == "class"

    assert "get_port" in symbols
    assert symbols["get_port"].kind == "method"
    assert symbols["get_port"].parent_name == "Config"

    assert "greet" in symbols
    assert symbols["greet"].kind == "function"
    assert symbols["greet"].exported is True

    assert "main" in symbols
    assert symbols["main"].kind == "function"

    assert "PUBLIC_CONST" in symbols
    assert symbols["PUBLIC_CONST"].kind == "const"

    assert len(r.imports) == 2

    calls_by_callee = {c.callee_name: c for c in r.calls}
    assert "greet" in calls_by_callee
    assert "Config" in calls_by_callee
    assert "print" in calls_by_callee
    assert "sys.exit" in calls_by_callee
