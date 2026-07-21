import hashlib

import tree_sitter_python
from tree_sitter import Language, Parser

from memos.indexer.base import (
    LanguageIndexer,
    ParsedCall,
    ParsedImport,
    ParsedSymbol,
    ParseResult,
)

_PY_LANG = Language(tree_sitter_python.language())


class PythonIndexer(LanguageIndexer):
    def __init__(self):
        self.parser = Parser()
        self.parser.language = _PY_LANG

    def language(self) -> str:
        return "python"

    def parse(self, source: str, file_path: str) -> ParseResult:
        source_bytes = bytes(source, "utf-8")
        tree = self.parser.parse(source_bytes)
        result = ParseResult()
        self._walk(tree.root_node, source_bytes, result)
        return result

    def _walk(self, node, source, result, scope=None, class_name=None):  # noqa: C901, PLR0911, PLR0912
        t = node.type

        if t == "function_definition":
            name_node = node.child_by_field_name("name")
            name = self._node_text(name_node, source) if name_node else None
            if name:
                kind = "method" if class_name else "function"
                self._add_symbol(
                    node, source, result, kind, name, parent_name=class_name,
                )
                method_scope = f"{class_name}.{name}" if class_name else name
                for child in node.children:
                    self._walk(
                        child, source, result,
                        scope=method_scope, class_name=class_name,
                    )
            return

        if t == "class_definition":
            name_node = node.child_by_field_name("name")
            name = self._node_text(name_node, source) if name_node else None
            if name:
                self._add_symbol(node, source, result, "class", name)
                for child in node.children:
                    self._walk(child, source, result, scope=name, class_name=name)
            return

        if t == "decorated_definition":
            for child in node.children:
                self._walk(child, source, result, scope=scope, class_name=class_name)
            return

        if t == "expression_statement":
            if scope is None and class_name is None:
                for child in node.children:
                    if child.type == "assignment":
                        self._handle_assignment(child, source, result)
            for child in node.children:
                self._walk(child, source, result, scope=scope, class_name=class_name)
            return

        if t == "call":
            self._add_call(node, source, result, scope)
            for child in node.children:
                self._walk(child, source, result, scope=scope, class_name=class_name)
            return

        if t == "import_statement":
            self._add_import(node, source, result)
            return

        if t == "import_from_statement":
            self._add_from_import(node, source, result)
            return

        for child in node.children:
            self._walk(child, source, result, scope=scope, class_name=class_name)

    def _handle_assignment(self, node, source, result):
        left = node.child_by_field_name("left")
        if left and left.type == "identifier":
            name = self._node_text(left, source)
            kind = "const" if name.isupper() else "variable"
            text = source[node.start_byte : node.end_byte].decode("utf-8")
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            exported = not name.startswith("_")
            result.symbols.append(
                ParsedSymbol(
                    name=name,
                    kind=kind,
                    signature=text,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    exported=exported,
                    content_hash=content_hash,
                ),
            )

    def _add_symbol(self, node, source, result, kind, name, parent_name=None):  # noqa: PLR0913
        text = source[node.start_byte : node.end_byte].decode("utf-8")
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        exported = not name.startswith("_")

        if kind in ("function", "method"):
            sig = self._extract_signature(node, source, text)
        else:
            sig = text.split("{", 1)[0].strip() if "{" in text else text

        result.symbols.append(
            ParsedSymbol(
                name=name,
                kind=kind,
                signature=sig,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                exported=exported,
                content_hash=content_hash,
                parent_name=parent_name,
            ),
        )

    def _extract_signature(self, node, source, text):
        params = node.child_by_field_name("parameters")
        if params is None:
            return None
        params_end = params.end_byte - node.start_byte
        return_type = node.child_by_field_name("return_type")
        if return_type:
            params_end = return_type.end_byte - node.start_byte
        colon_idx = text.find(":", params_end)
        if colon_idx != -1:
            return text[: colon_idx + 1].strip()
        return text

    def _add_call(self, node, source, result, caller_name):
        func_node = node.child_by_field_name("function")
        if func_node is None:
            func_node = node.children[0] if node.children else None
        if func_node is None:
            return
        if func_node.type in ("identifier", "attribute"):
            name = self._node_text(func_node, source)
        else:
            return
        result.calls.append(
            ParsedCall(
                caller_name=caller_name,
                callee_name=name,
                line=node.start_point[0] + 1,
            ),
        )

    def _add_import(self, node, source, result):
        for child in node.children:
            if child.type == "dotted_name":
                path = self._node_text(child, source)
                result.imports.append(ParsedImport(imported_path=path))
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                if name_node:
                    path = self._node_text(name_node, source)
                    result.imports.append(ParsedImport(imported_path=path))

    def _add_from_import(self, node, source, result):
        module_node = node.child_by_field_name("module_name")
        if module_node:
            path = self._node_text(module_node, source)
            result.imports.append(ParsedImport(imported_path=path))

    @staticmethod
    def _node_text(node, source):
        return source[node.start_byte : node.end_byte].decode("utf-8")
