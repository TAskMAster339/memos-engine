from typing import Any

from pydantic import BaseModel


class ContextResponse(BaseModel):
    symbol: dict[str, Any]
    callers: list[dict[str, Any]]
    callees: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    summary: dict[str, Any] | None = None
    generation_context: dict[str, Any] | None = None


class RenameImpactResponse(BaseModel):
    symbol: dict[str, Any]
    callers: list[dict[str, Any]]
    type_references: list[dict[str, Any]]
    import_references: list[dict[str, Any]]
    warning: str


class DependencyGraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class ImportCyclesResponse(BaseModel):
    cycles: list[list[str]]


class UnusedSymbolsResponse(BaseModel):
    symbols: list[dict[str, Any]]


class DeadImportsResponse(BaseModel):
    imports: list[dict[str, Any]]


class DiffImpactResponse(BaseModel):
    file: dict[str, Any]
    exported_symbols: list[dict[str, Any]]


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


class SemanticSearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[dict[str, Any]]


class MemorySearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[dict[str, Any]]


class MemoryPruneResponse(BaseModel):
    count: int
    dry_run: bool


class MemoryPruneRequest(BaseModel):
    older_than_days: int | None = None
    kind: str | None = None
    apply: bool = False


class MemoryEntryResponse(BaseModel):
    id: int
    project_id: int
    scope_type: str
    scope_id: int | None = None
    kind: str
    content: str
    source: str
    source_hash: str | None = None
    created_at: str


class MemoryCreateRequest(BaseModel):
    content: str
    scope_type: str = "project"
    scope_id: int | None = None
    kind: str = "note"
    source: str = "agent"
