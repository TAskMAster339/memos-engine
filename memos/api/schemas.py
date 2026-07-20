from typing import Any

from pydantic import BaseModel


class SymbolResponse(BaseModel):
    id: int
    file_id: int
    parent_symbol_id: int | None = None
    name: str
    kind: str
    signature: str | None = None
    start_line: int
    end_line: int
    exported: int
    content_hash: str
    file_path: str
    file_language: str


class CallEdgeResponse(BaseModel):
    caller_name: str
    caller_kind: str
    caller_symbol_id: int
    callee_name: str
    line: int
    file: str
    file_id: int
    callee_resolved_name: str = ""


class ModuleResponse(BaseModel):
    file: dict[str, Any]
    symbols: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    imports: list[dict[str, Any]]
