from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParsedSymbol:
    name: str
    kind: str
    signature: str | None
    start_line: int
    end_line: int
    exported: bool
    content_hash: str
    parent_name: str | None = None


@dataclass
class ParsedCall:
    caller_name: str | None
    callee_name: str
    line: int


@dataclass
class ParsedImport:
    imported_path: str


@dataclass
class ParseResult:
    symbols: list[ParsedSymbol] = field(default_factory=list)
    calls: list[ParsedCall] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)


class LanguageIndexer(ABC):
    @abstractmethod
    def language(self) -> str: ...

    @abstractmethod
    def parse(self, source: str, file_path: str) -> ParseResult: ...
