from typing import Optional
from pydantic import BaseModel, ConfigDict


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    root_path: str
    name: Optional[str] = None
    created_at: str


class File(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    project_id: int
    path: str
    language: str
    content_hash: str
    mtime: Optional[float] = None
    last_indexed_at: Optional[str] = None


class Symbol(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    file_id: int
    parent_symbol_id: Optional[int] = None
    name: str
    kind: str
    signature: Optional[str] = None
    start_line: int
    end_line: int
    exported: bool = False
    content_hash: str


class CallEdge(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    caller_symbol_id: int
    callee_name: str
    callee_symbol_id: Optional[int] = None
    line: int


class Import(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    file_id: int
    imported_path: str
    resolved_file_id: Optional[int] = None


class MemoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    project_id: int
    scope_type: str
    scope_id: Optional[int] = None
    kind: str
    content: str
    source: str
    source_hash: Optional[str] = None
    created_at: str
