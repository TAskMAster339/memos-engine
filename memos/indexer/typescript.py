import hashlib

import tree_sitter_typescript as tst
from tree_sitter import Language, Parser

from memos.indexer.base import (
    LanguageIndexer,
    ParsedCall,
    ParsedImport,
    ParsedSymbol,
    ParseResult,
)

_TS_LANG = Language(tst.language_typescript())
_TSX_LANG = Language(tst.language_tsx())


class TypeScriptIndexer(LanguageIndexer):
    def __init__(self, *, tsx: bool = False):
        self.parser = Parser()
        self.parser.language = _TSX_LANG if tsx else _TS_LANG
        self._tsx = tsx

    def language(self) -> str:
        return "tsx" if self._tsx else "typescript"

    def parse(self, source: str, file_path: str) -> ParseResult:
        source_bytes = bytes(source, "utf-8")
        tree = self.parser.parse(source_bytes)
        result = ParseResult()
        self._walk(tree.root_node, source_bytes, result)
        return result

    def _walk(self, node, source, result, *, exported=False, scope=None):  # noqa: C901, PLR0911, PLR0912
        t = node.type

        if t == "export_statement":
            for child in node.children:
                self._walk(child, source, result, exported=True, scope=scope)
            return

        if t == "function_declaration":
            name_node = node.child_by_field_name("name")
            fn_name = self._node_text(name_node, source) if name_node else None
            if fn_name:
                self._add_symbol(node, source, result, "function", exported)
                for child in node.children:
                    self._walk(child, source, result, exported=exported, scope=fn_name)
            return

        if t == "class_declaration":
            name_node = node.child_by_field_name("name")
            cls_name = self._node_text(name_node, source) if name_node else None
            if cls_name:
                self._add_symbol(node, source, result, "class", exported)
            for child in node.children:
                self._walk(child, source, result, exported=exported, scope=cls_name)
            return

        if t == "interface_declaration":
            self._add_symbol(node, source, result, "interface", exported)
            return

        if t == "type_alias_declaration":
            self._add_symbol(node, source, result, "type", exported)
            return

        if t == "method_definition":
            parent = node.parent
            if parent and parent.type == "class_body":
                class_node = parent.parent
                class_name = (
                    self._node_text(class_node.child_by_field_name("name"), source)
                    if class_node.child_by_field_name("name")
                    else None
                )
                method_name = (
                    self._node_text(node.child_by_field_name("name"), source)
                    if node.child_by_field_name("name")
                    else None
                )
                if method_name:
                    self._add_symbol(
                        node,
                        source,
                        result,
                        "method",
                        exported,
                        parent_name=class_name,
                    )
                    method_scope = (
                        f"{class_name}.{method_name}" if class_name else method_name
                    )
                    for child in node.children:
                        self._walk(
                            child,
                            source,
                            result,
                            exported=exported,
                            scope=method_scope,
                        )
            return

        if t == "lexical_declaration":
            keyword = node.children[0].type if node.children else "const"
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        name = self._node_text(name_node, source)
                        self._add_symbol(
                            child,
                            source,
                            result,
                            keyword,
                            exported,
                            name_override=name,
                        )
                for c in child.children:
                    self._walk(c, source, result, exported=exported, scope=scope)
            return

        if t == "call_expression":
            self._add_call(node, source, result, scope)
            for child in node.children:
                self._walk(child, source, result, exported=exported, scope=scope)
            return

        if t == "import_statement":
            self._add_import(node, source, result)
            return

        for child in node.children:
            self._walk(child, source, result, exported=exported, scope=scope)

    def _add_symbol(  # noqa: PLR0913
        self,
        node,
        source,
        result,
        kind,
        exported,
        parent_name=None,
        name_override=None,
    ):
        if name_override:
            name = name_override
        else:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return
            name = self._node_text(name_node, source)

        text = source[node.start_byte : node.end_byte].decode("utf-8")
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        sig = text
        brace = text.find("{")
        if brace != -1:
            sig = text[:brace].strip()
        sig = sig.strip() or None

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

    def _add_call(self, node, source, result, caller_name):
        func_node = node.children[0] if node.children else None
        if func_node is None:
            return
        if func_node.type in ("identifier", "member_expression"):
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
            if child.type == "string":
                raw = source[child.start_byte : child.end_byte].decode("utf-8")
                path = raw.strip("'\"")
                result.imports.append(ParsedImport(imported_path=path))
                return

    @staticmethod
    def _node_text(node, source):
        return source[node.start_byte : node.end_byte].decode("utf-8")
