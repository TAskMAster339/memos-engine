from pydantic import BaseModel, ConfigDict


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    root_path: str
    name: str | None = None
    created_at: str


class File(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    project_id: int
    path: str
    language: str
    content_hash: str
    mtime: float | None = None
    last_indexed_at: str | None = None


class Symbol(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    file_id: int
    parent_symbol_id: int | None = None
    name: str
    kind: str
    signature: str | None = None
    start_line: int
    end_line: int
    exported: bool = False
    content_hash: str


class CallEdge(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    caller_symbol_id: int
    callee_name: str
    callee_symbol_id: int | None = None
    line: int


class Import(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    file_id: int
    imported_path: str
    resolved_file_id: int | None = None


class MemoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int | None = None
    project_id: int
    scope_type: str
    scope_id: int | None = None
    kind: str
    content: str
    source: str
    source_hash: str | None = None
    prompt_version: str | None = None
    created_at: str
