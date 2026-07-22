from memos.indexer.typescript import TypeScriptIndexer


def _I(language_override="javascript"):
    return TypeScriptIndexer(language_override=language_override)


def test_parse_function():
    src = "function add(a, b) {\n  return a + b;\n}\n"
    r = _I().parse(src, "test.js")
    assert len(r.symbols) == 1
    s = r.symbols[0]
    assert s.name == "add"
    assert s.kind == "function"
    assert s.exported is False
    assert s.start_line == 1
    assert s.end_line == 3


def test_parse_exported_function():
    src = "export function greet(name) { console.log(name); }\n"
    r = _I().parse(src, "test.js")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "greet"
    assert r.symbols[0].exported is True


def test_parse_class_with_method():
    src = "class MyClass {\n  method() { return 1; }\n}\n"
    r = _I().parse(src, "test.js")
    assert len(r.symbols) == 2
    cls = r.symbols[0]
    assert cls.name == "MyClass"
    assert cls.kind == "class"
    mtd = r.symbols[1]
    assert mtd.name == "method"
    assert mtd.kind == "method"
    assert mtd.parent_name == "MyClass"


def test_parse_const():
    src = "const PI = 3.14;\n"
    r = _I().parse(src, "test.js")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "PI"
    assert r.symbols[0].kind == "const"


def test_parse_arrow_function_const():
    src = "const fn = (x) => x + 1;\n"
    r = _I().parse(src, "test.js")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "fn"
    assert r.symbols[0].kind == "const"


def test_parse_calls():
    src = "function test() { foo(); bar(1, 2); }\n"
    r = _I().parse(src, "test.js")
    assert len(r.calls) == 2
    assert r.calls[0].callee_name == "foo"
    assert r.calls[0].caller_name == "test"
    assert r.calls[1].callee_name == "bar"
    assert r.calls[1].caller_name == "test"


def test_parse_imports():
    src = 'import { readFile } from "fs";\nimport * as path from "path";\n'
    r = _I().parse(src, "test.js")
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fs"
    assert r.imports[1].imported_path == "path"


def test_parse_commonjs_require():
    src = 'const fs = require("fs");\nconst path = require("path");\n'
    r = _I().parse(src, "test.js")
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fs"
    assert r.imports[1].imported_path == "path"
    assert len(r.calls) == 0


def test_content_hash_stable():
    src = "function foo() { return 1; }\n"
    r1 = _I().parse(src, "a.js")
    r2 = _I().parse(src, "b.js")
    assert r1.symbols[0].content_hash == r2.symbols[0].content_hash


def test_language_field_is_javascript_not_typescript():
    idx = TypeScriptIndexer(tsx=False, language_override="javascript")
    assert idx.language() == "javascript"

    idx_jsx = TypeScriptIndexer(tsx=True, language_override="jsx")
    assert idx_jsx.language() == "jsx"


def test_parse_realistic_file():
    src = """
import { readFile } from "fs";
import * as path from "path";

export function loadConfig(p) {
  const data = readFile(p);
  return JSON.parse(data);
}

function helper() {
  // internal
}
"""
    r = _I().parse(src, "config.js")
    symbols = {s.name: s for s in r.symbols}
    assert "loadConfig" in symbols
    assert symbols["loadConfig"].kind == "function"
    assert symbols["loadConfig"].exported is True
    assert "helper" in symbols
    assert symbols["helper"].kind == "function"
    assert symbols["helper"].exported is False
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fs"
    assert len(r.calls) >= 1
    assert r.calls[0].caller_name == "loadConfig"
