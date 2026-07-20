from memos.indexer.go import GoIndexer


def _I():
    return GoIndexer()


def test_parse_function():
    src = "func foo() { return 1 }\n"
    r = _I().parse(src, "main.go")
    assert len(r.symbols) == 1
    s = r.symbols[0]
    assert s.name == "foo"
    assert s.kind == "function"
    assert s.exported is False
    assert s.start_line == 1
    assert s.end_line == 1


def test_parse_exported_function():
    src = "func Foo() { return 1 }\n"
    r = _I().parse(src, "main.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "Foo"
    assert r.symbols[0].exported is True


def test_parse_unexported_function():
    src = "func bar() {}\n"
    r = _I().parse(src, "main.go")
    assert r.symbols[0].exported is False


def test_parse_method():
    src = "func (t T) Method() int { return 0 }\n"
    r = _I().parse(src, "main.go")
    assert len(r.symbols) == 1
    s = r.symbols[0]
    assert s.name == "Method"
    assert s.kind == "method"
    assert s.exported is True
    assert s.parent_name == "T"


def test_parse_method_pointer_receiver():
    src = "func (t *T) Method() int { return 0 }\n"
    r = _I().parse(src, "main.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].parent_name == "T"


def test_parse_struct():
    src = "type User struct {\n  Name string\n}\n"
    r = _I().parse(src, "types.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "User"
    assert r.symbols[0].kind == "struct"
    assert r.symbols[0].exported is True


def test_parse_unexported_struct():
    src = "type user struct {}\n"
    r = _I().parse(src, "types.go")
    assert r.symbols[0].exported is False


def test_parse_interface():
    src = "type Printer interface {\n  Print() error\n}\n"
    r = _I().parse(src, "types.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "Printer"
    assert r.symbols[0].kind == "interface"


def test_parse_type_alias():
    src = "type MyString string\n"
    r = _I().parse(src, "types.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "MyString"
    assert r.symbols[0].kind == "type"


def test_parse_const():
    src = "const X = 1\n"
    r = _I().parse(src, "main.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "X"
    assert r.symbols[0].kind == "const"
    assert r.symbols[0].exported is True


def test_parse_var():
    src = "var x = 1\n"
    r = _I().parse(src, "main.go")
    assert len(r.symbols) == 1
    assert r.symbols[0].name == "x"
    assert r.symbols[0].kind == "var"
    assert r.symbols[0].exported is False


def test_parse_short_var():
    src = "package p\nfunc f() { x := 1 }\n"
    r = _I().parse(src, "main.go")
    vars = [s for s in r.symbols if s.kind == "var" and s.name == "x"]
    assert len(vars) == 1
    assert vars[0].exported is False


def test_parse_calls():
    src = "package p\nfunc f() { foo(); pkg.Bar(1) }\n"
    r = _I().parse(src, "main.go")
    assert len(r.calls) == 2
    assert r.calls[0].callee_name == "foo"
    assert r.calls[0].caller_name == "f"
    assert r.calls[1].callee_name == "pkg.Bar"
    assert r.calls[1].caller_name == "f"


def test_parse_imports():
    src = 'import "fmt"\nimport "os"\n'
    r = _I().parse(src, "main.go")
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fmt"
    assert r.imports[1].imported_path == "os"


def test_parse_grouped_imports():
    src = 'import (\n\t"fmt"\n\t"os"\n)\n'
    r = _I().parse(src, "main.go")
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fmt"
    assert r.imports[1].imported_path == "os"


def test_parse_signature():
    src = "func add(a int, b int) int {\n  return a + b\n}\n"
    r = _I().parse(src, "main.go")
    sig = r.symbols[0].signature
    assert sig is not None
    assert "add" in sig
    assert "a int" in sig
    assert "{" not in sig


def test_content_hash_differs():
    a = _I().parse("func foo() { return 1 }\n", "a.go")
    b = _I().parse("func foo() { return 2 }\n", "b.go")
    assert a.symbols[0].content_hash != b.symbols[0].content_hash


def test_parse_realistic_file():
    src = """
package main

import (
\t"fmt"
\t"os"
)

const DefaultName = "world"

type Config struct {
\tPort int
}

func greet(name string) string {
\treturn fmt.Sprintf("hello %s", name)
}

func main() {
\tvar msg = greet("alice")
\tfmt.Println(msg)
\tos.Exit(0)
}
"""
    r = _I().parse(src, "main.go")
    symbols = {s.name: s for s in r.symbols}
    assert "DefaultName" in symbols
    assert symbols["DefaultName"].kind == "const"
    assert symbols["DefaultName"].exported is True
    assert "Config" in symbols
    assert symbols["Config"].kind == "struct"
    assert "greet" in symbols
    assert symbols["greet"].kind == "function"
    assert symbols["greet"].exported is False
    assert "main" in symbols
    assert symbols["main"].kind == "function"
    assert len(r.imports) == 2
    assert r.imports[0].imported_path == "fmt"

    calls_by_callee = {c.callee_name: c for c in r.calls}
    assert "fmt.Sprintf" in calls_by_callee
    assert "fmt.Println" in calls_by_callee
    assert "os.Exit" in calls_by_callee
