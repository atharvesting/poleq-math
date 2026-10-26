"""The strict contract shared by the browser, CLI and coding agents."""
from typing import Annotated, Literal
from uuid import UUID
from datetime import datetime
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40_000)]
Formula = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
Kind = Literal["property", "proof", "equivalence", "note"]


def title_words(value):
    return re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Domain(StrictModel):
    name: Name
    aliases: list[Name] = Field(default_factory=list, max_length=30)


class Concept(Domain):
    definition: Text
    latex: Formula
    domain_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("domain_ids")
    @classmethod
    def unique_domains(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Select each domain only once")
        return values


class Entry(StrictModel):
    title: Name
    kind: Kind = "property"
    body: Text
    latex: Formula
    concept_ids: list[UUID] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_title(self):
        if title_words(self.title) == title_words(self.body):
            raise ValueError("Use a descriptive title instead of repeating the English description")
        return self

    @field_validator("concept_ids")
    @classmethod
    def unique_concepts(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Select each concept only once")
        return values


class Record(StrictModel):
    id: UUID
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def valid_times(self):
        created, updated = datetime.fromisoformat(self.created_at), datetime.fromisoformat(self.updated_at)
        if created.tzinfo is None or updated.tzinfo is None:
            raise ValueError("Record timestamps must include a timezone")
        if updated < created:
            raise ValueError("Updated time cannot precede creation time")
        return self


class DomainRecord(Domain, Record):
    pass


class ConceptRecord(Concept, Record):
    pass


class EntryRecord(Entry, Record):
    pass


class Archive(StrictModel):
    format: Literal["poleq"]
    version: Literal[2]
    domains: list[DomainRecord] = Field(max_length=50_000)
    concepts: list[ConceptRecord] = Field(max_length=50_000)
    entries: list[EntryRecord] = Field(max_length=50_000)


class DraftRequest(StrictModel):
    text: Text
    kind: Kind = "property"
    concept_ids: list[UUID] = Field(min_length=1, max_length=100)


class ConceptDraftRequest(Domain):
    domain_ids: list[UUID] = Field(min_length=1, max_length=100)
    context: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40_000)] = ""

    @field_validator("domain_ids")
    @classmethod
    def unique_domains(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Select each domain only once")
        return values
