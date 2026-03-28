"""TypedDict hierarchies for reporting export formats.

Defines typed dictionaries matching the exact JSON schemas produced by
each export format: Stryker Dashboard, internal JSON, and SonarQube.
"""

from __future__ import annotations

from typing import (
    NotRequired,
    TypedDict,
)

# ── Stryker Dashboard format ──────────────────────────────────────────


class StrykerLocation(TypedDict):
    """A line/column position in a source file."""

    line: int
    column: int | None


class StrykerPosition(TypedDict):
    """Start and optional end location for a mutant.

    ``start`` is always present; ``end`` is only present when the
    AST node has ``end_lineno`` set.
    """

    start: StrykerLocation
    end: NotRequired[StrykerLocation]


class StrykerMutant(TypedDict):
    """A single mutant entry in the Stryker report.

    Required keys: id, mutatorName, location, status, description.
    Optional keys: killedBy, duration.
    """

    id: str
    mutatorName: str
    location: StrykerPosition
    status: str
    description: str
    killedBy: NotRequired[list[str]]
    duration: NotRequired[int]
    statusReason: NotRequired[str]


class StrykerFileResult(TypedDict):
    """Per-file results in the Stryker report."""

    language: str
    mutants: list[StrykerMutant]


class StrykerFramework(TypedDict):
    """Framework metadata in the Stryker report."""

    name: str
    version: str


class StrykerReport(TypedDict):
    """Top-level Stryker mutation-testing-report-schema structure."""

    schemaVersion: str
    thresholds: dict[str, int]
    files: dict[str, StrykerFileResult]
    framework: StrykerFramework


# ── Internal JSON report format ───────────────────────────────────────


class JsonSummary(TypedDict):
    """Summary section of the internal JSON report."""

    total: int
    zapped: int
    survived: int
    timeout: int
    error: int
    pardoned: int
    percentage: float


class JsonFileStats(TypedDict):
    """Per-file statistics in the internal JSON report."""

    total: int
    zapped: int
    survived: int
    percentage: float


class JsonResultEntry(TypedDict):
    """A single gremlin result in the internal JSON report."""

    gremlin_id: str
    file_path: str
    line_number: int
    status: str
    operator: str
    description: str
    killing_test: NotRequired[str]
    error_output: NotRequired[str]
    execution_time_ms: NotRequired[float]
    selected_tests: NotRequired[list[str]]


class JsonReport(TypedDict):
    """Top-level internal JSON report structure."""

    summary: JsonSummary
    files: dict[str, JsonFileStats]
    results: list[JsonResultEntry]


# ── SonarQube generic issue format ────────────────────────────────────


class SonarTextRange(TypedDict):
    """Text range for a SonarQube issue location."""

    startLine: int


class SonarPrimaryLocation(TypedDict):
    """Primary location of a SonarQube issue."""

    filePath: str
    textRange: SonarTextRange
    message: str


class SonarIssue(TypedDict):
    """A single external issue in SonarQube generic format."""

    engineId: str
    ruleId: str
    severity: str
    type: str
    effortMinutes: int
    primaryLocation: SonarPrimaryLocation


class SonarReport(TypedDict):
    """Top-level SonarQube generic issue report."""

    issues: list[SonarIssue]
