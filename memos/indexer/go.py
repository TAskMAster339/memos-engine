import hashlib

import tree_sitter_go
from tree_sitter import Language, Parser

from memos.indexer.base import (
    LanguageIndexer,
    ParsedCall,
    ParsedImport,
    ParsedSymbol,
    ParseResult,
)

_GO_LANG = Language(tree_sitter_go.language())


class GoIndexer(LanguageIndexer):
    def __init__(self):
        self.parser = Parser()
        self.parser.language = _GO_LANG

    def language(self) -> str:
        return "go"

    def parse(self, source: str, file_path: str) -> ParseResult:
        source_bytes = bytes(source, "utf-8")
        tree = self.parser.parse(source_bytes)
        result = ParseResult()
        self._walk(tree.root_node, source_bytes, result)
        return result

    def _walk(self, node, source, result, scope=None):  # noqa: C901, PLR0911, PLR0912, PLR0915
        t = node.type

        if t == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = self._node_text(name_node, source) if name_node else None
            if name:
                self._add_symbol(node, source, result, "function", name)
                for child in node.children:
                    self._walk(child, source, result, scope=name)
            return

        if t == "method_declaration":
            name_node = node.child_by_field_name("name")
            name = self._node_text(name_node, source) if name_node else None
            if name:
                parent_name = self._receiver_type(node, source)
                self._add_symbol(
                    node,
                    source,
                    result,
                    "method",
                    name,
                    parent_name=parent_name,
                )
                full_scope = f"{parent_name}.{name}" if parent_name else name
                for child in node.children:
                    self._walk(child, source, result, scope=full_scope)
            return

        if t == "type_declaration":
            for child in node.children:
                if child.type == "type_spec":
                    self._walk(child, source, result, scope=scope)
            return

        if t == "type_spec":
            name_node = node.child_by_field_name("name")
            name = self._node_text(name_node, source) if name_node else None
            if name:
                type_node = node.child_by_field_name("type")
                kind = self._type_spec_kind(type_node) if type_node else "type"
                self._add_symbol(node, source, result, kind, name)
            return

        if t == "const_declaration":
            for child in node.children:
                if child.type == "const_spec":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        name = self._node_text(name_node, source)
                        self._add_symbol(child, source, result, "const", name)
                        for c in child.children:
                            self._walk(c, source, result, scope=scope)
            return

        if t == "var_declaration":
            for child in node.children:
                if child.type == "var_spec":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        name = self._node_text(name_node, source)
                        self._add_symbol(child, source, result, "var", name)
                        for c in child.children:
                            self._walk(c, source, result, scope=scope)
            return

        if t == "short_var_declaration":
            left = node.child_by_field_name("left")
            if left:
                for c in left.children:
                    if c.type == "identifier":
                        name = self._node_text(c, source)
                        self._add_symbol(c, source, result, "var", name)
            for child in node.children:
                self._walk(child, source, result, scope=scope)
            return

        if t == "call_expression":
            self._add_call(node, source, result, scope)
            for child in node.children:
                self._walk(child, source, result, scope=scope)
            return

        if t == "import_declaration":
            self._add_imports(node, source, result)
            return

        for child in node.children:
            self._walk(child, source, result, scope=scope)

    def _receiver_type(self, node, source) -> str | None:
        recv = node.child_by_field_name("receiver")
        if recv is None:
            return None
        for child in recv.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node is None:
                    continue
                # pointer_type wraps the actual type
                if type_node.type == "pointer_type":
                    for ptr_child in type_node.children:
                        if ptr_child.type == "type_identifier":
                            return self._node_text(ptr_child, source)
                elif type_node.type == "type_identifier":
                    return self._node_text(type_node, source)
        return None

    def _type_spec_kind(self, type_node) -> str:
        if type_node.type == "struct_type":
            return "struct"
        if type_node.type == "interface_type":
            return "interface"
        return "type"

    def _add_symbol(self, node, source, result, kind, name, parent_name=None):  # noqa: PLR0913
        text = source[node.start_byte : node.end_byte].decode("utf-8")
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        exported = name[0].isupper() if name else False

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
        func_node = node.child_by_field_name("function")
        if func_node is None:
            func_node = node.children[0] if node.children else None
        if func_node is None:
            return
        if func_node.type in ("identifier", "selector_expression"):
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

    def _add_imports(self, node, source, result):
        for child in node.children:
            if child.type == "import_spec":
                path_node = child.child_by_field_name("path")
                if path_node:
                    raw = self._node_text(path_node, source)
                    path = raw.strip('"')
                    result.imports.append(ParsedImport(imported_path=path))
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        path_node = spec.child_by_field_name("path")
                        if path_node:
                            raw = self._node_text(path_node, source)
                            path = raw.strip('"')
                            result.imports.append(ParsedImport(imported_path=path))

    @staticmethod
    def _node_text(node, source):
        return source[node.start_byte : node.end_byte].decode("utf-8")
