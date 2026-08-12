from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    DRAFT = "draft"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class Trust(StrEnum):
    UNVERIFIED = "unverified"
    MACHINE_CONFIRMED = "machine-confirmed"
    HUMAN_REVIEWED = "human-reviewed"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ProposalState(StrEnum):
    CAPTURED = "captured"
    READY_FOR_REVIEW = "ready-for-review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    PROMOTED = "promoted"


@dataclass(frozen=True)
class Heading:
    level: int
    title: str


@dataclass(frozen=True)
class Link:
    target: str


@dataclass(frozen=True)
class Claim:
    id: str
    normalized_value: str


@dataclass(frozen=True)
class Concept:
    relative_file: str
    concept_type: str
    resource: str | None
    status: Status
    generated: bool
    trust: Trust
    freshness: Freshness
    headings: tuple[Heading, ...]
    body: str
    links: tuple[Link, ...]
    claims: tuple[Claim, ...]
    source_paths: tuple[str, ...]
    content_hash: str
    title: str = ""
    description: str = ""
    supersedes: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    project: str | None = None
    components: tuple[str, ...] = ()
    symptoms: tuple[str, ...] = ()
    verified: tuple[dict[str, object], ...] = ()
    source_revision: str | None = None
    stale_after: str | None = None

    @property
    def authoritative(self) -> bool:
        return (
            self.status is Status.STABLE
            and self.freshness is Freshness.FRESH
            and self.trust is Trust.HUMAN_REVIEWED
            and not self.generated
        )
