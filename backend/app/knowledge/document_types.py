from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class UnknownDocumentTypeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentTypeDefinition:
    name: str
    directory: str

    def path_for(self, document_id: str) -> str:
        if (
            not document_id.strip()
            or Path(document_id).name != document_id
            or PureWindowsPath(document_id).name != document_id
        ):
            raise ValueError("document_id must be a filename-safe identifier")
        return f"{self.directory}/{document_id}.md"


class DocumentTypeRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, DocumentTypeDefinition] = {}

    def register(self, definition: DocumentTypeDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"document type {definition.name!r} already exists")
        self._definitions[definition.name] = definition

    def resolve(self, document_type: str) -> DocumentTypeDefinition:
        try:
            return self._definitions[document_type]
        except KeyError as error:
            raise UnknownDocumentTypeError(document_type) from error


def create_document_type_registry() -> DocumentTypeRegistry:
    registry = DocumentTypeRegistry()
    for name, directory in (
        ("source", "00_inbox"),
        ("question", "10_question_bank"),
        ("session_report", "20_review_sessions"),
        ("mastery_report", "30_mastery"),
        ("concept", "40_concepts"),
    ):
        registry.register(DocumentTypeDefinition(name=name, directory=directory))
    return registry
