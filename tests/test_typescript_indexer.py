from memos.indexer.typescript import TypeScriptIndexer


def _I():
    return TypeScriptIndexer()


def test_parse_function():
    src = "function add(a: number, b: number): number {\n  return a + b;\n}\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    s = r.symbols[0]
    assert s.name == "add"
    assert s.kind == "function"
    assert s.exported is False
    assert s.start_line == 1
    assert s.end_line == 3


def test_parse_exported_function():
    src = "export function greet(name: string): void { console.log(name); }\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "greet"
    assert r.symbols[0].exported is True


def test_parse_class_with_method():
    src = "class MyClass {\n  method() { return 1; }\n}\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 2
    cls = r.symbols[0]
    assert cls.name == "MyClass"
    assert cls.kind == "class"
    mtd = r.symbols[1]
    assert mtd.name == "method"
    assert mtd.kind == "method"
    assert mtd.parent_name == "MyClass"


def test_parse_interface():
    src = "interface User { name: string; age: number; }\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "User"
    assert r.symbols[0].kind == "interface"
    assert r.symbols[0].exported is False


def test_parse_exported_interface():
    src = "export interface User { name: string; }\n"
    r = _I().parse(src, "test.ts")
    assert r.symbols[0].exported is True


def test_parse_type_alias():
    src = "type Foo = string;\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "Foo"
    assert r.symbols[0].kind == "type"


def test_parse_const():
    src = "const PI = 3.14;\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "PI"
    assert r.symbols[0].kind == "const"


def test_parse_arrow_function_const():
    src = "const fn = (x: number) => x + 1;\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "fn"
    assert r.symbols[0].kind == "const"


def test_parse_calls():
    src = "function test() { foo(); bar(1, 2); }\n"
    r = _I().parse(src, "test.ts")
    assert len(r.calls) == 2
    assert r.calls[0].callee_name == "foo"
    assert r.calls[0].caller_name == "test"
    assert r.calls[1].callee_name == "bar"
    assert r.calls[1].caller_name == "test"


def test_parse_imports():
    src = 'import { readFile } from "fs";\nimport * as path from "path";\n'
    r = _I().parse(src, "test.ts")
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fs"
    assert r.imports[1].imported_path == "path"


def test_parse_signature():
    src = "function add(a: number, b: number): number {\n  return a + b;\n}\n"
    r = _I().parse(src, "test.ts")
    sig = r.symbols[0].signature
    assert sig is not None
    assert "add" in sig
    assert "a: number" in sig
    assert "{" not in sig


def test_content_hash_stable():
    src = "function foo() { return 1; }\n"
    r1 = _I().parse(src, "a.ts")
    r2 = _I().parse(src, "b.ts")
    assert r1.symbols[0].content_hash == r2.symbols[0].content_hash


def test_content_hash_differs():
    a = _I().parse("function foo() { return 1; }\n", "a.ts")
    b = _I().parse("function foo() { return 2; }\n", "b.ts")
    assert a.symbols[0].content_hash != b.symbols[0].content_hash


def test_export_class():
    src = "export class MyClass {}\n"
    r = _I().parse(src, "test.ts")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "MyClass"
    assert r.symbols[0].kind == "class"
    assert r.symbols[0].exported is True


def test_parse_realistic_file():
    src = """
import { readFile } from "fs";
import * as path from "path";

export interface Config {
  port: number;
}

export function loadConfig(p: string): Config {
  const data = readFile(p);
  return JSON.parse(data);
}

function helper(): void {
  // internal
}
"""
    r = _I().parse(src, "config.ts")
    symbols = {s.name: s for s in r.symbols}
    assert "Config" in symbols
    assert symbols["Config"].kind == "interface"
    assert symbols["Config"].exported is True
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


def test_parse_tsx_file():
    src = """
import { Component } from "react";

export interface Props {
  name: string;
}

export function Greeting(props: Props): JSX.Element {
  return <div>Hello {props.name}</div>;
}
"""
    indexer = TypeScriptIndexer(tsx=True)
    r = indexer.parse(src, "greeting.tsx")
    names = {s.name for s in r.symbols}
    assert "Props" in names
    assert "Greeting" in names
    assert any(s.kind == "interface" for s in r.symbols)
    assert any(s.kind == "function" for s in r.symbols)
