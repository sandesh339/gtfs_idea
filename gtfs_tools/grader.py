"""The oracle / grader — scores an edited feed on the five §5 dimensions.

  validity     feed still parses and passes the structural validator (global)
  correctness  the intended diff happened (per-scenario answer-key assertions)
  integrity    the scenario's invariants hold (contiguity, monotonic, refs)
  damage       NOTHING outside the sanctioned scope changed (collateral edits)
  cost         calls / repair rounds / tokens (recorded by the executor)

A Scenario carries the natural-language request, the human tool-fit hypothesis,
and callables that express its answer key. correctness/integrity callables take
(original, edited) and return a list of Check. damage_ok takes one EntityChange
and returns True if that change was sanctioned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .feed import Feed
from .integrity import validate_feed
from .diffing import entity_changes, EntityChange


# ---- check primitives ------------------------------------------------------
@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


class Checks:
    """Tiny accumulator so scenario answer-keys read declaratively."""

    def __init__(self) -> None:
        self.items: List[Check] = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.items.append(Check(name, bool(ok), detail))

    def eq(self, name: str, got, want) -> None:
        self.add(name, got == want, f"got {got!r}, want {want!r}")

    def true(self, name: str, ok: bool, detail: str = "") -> None:
        self.add(name, ok, detail)


CheckFn = Callable[[Feed, Feed], List[Check]]
DamageFn = Callable[[EntityChange, Feed, Feed], bool]


@dataclass
class Scenario:
    id: str
    group: str                       # "A" | "B" | "C"
    request: str
    tool_fit: str                    # "high" | "medium" | "low" | "ambiguous"
    correctness: CheckFn
    integrity: Optional[CheckFn] = None
    damage_ok: DamageFn = lambda c, o, e: False   # default: nothing may change
    note: str = ""                   # e.g. divergence from the PDF wording


# ---- grade report ----------------------------------------------------------
@dataclass
class DimensionResult:
    passed: bool
    checks: List[Check] = field(default_factory=list)
    detail: str = ""


@dataclass
class GradeReport:
    scenario_id: str
    tool_fit: str
    validity: DimensionResult
    correctness: DimensionResult
    integrity: DimensionResult
    damage: DimensionResult
    cost: dict
    note: str = ""

    @property
    def overall_pass(self) -> bool:
        return (self.validity.passed and self.correctness.passed
                and self.integrity.passed and self.damage.passed)

    def render(self) -> str:
        def mark(b): return "PASS" if b else "FAIL"
        lines = [f"[{self.scenario_id}] tool_fit={self.tool_fit}  "
                 f"OVERALL {mark(self.overall_pass)}"]
        for name, dim in (("validity", self.validity), ("correctness", self.correctness),
                          ("integrity", self.integrity), ("damage", self.damage)):
            lines.append(f"  {name:<12} {mark(dim.passed)}"
                         + (f"  {dim.detail}" if dim.detail else ""))
            for c in dim.checks:
                if not c.ok:
                    lines.append(f"      - {c.name}: {c.detail}")
        lines.append(f"  cost         calls={self.cost.get('calls')} "
                     f"repairs={self.cost.get('repairs')} "
                     f"struct_ok={self.cost.get('structural_success')}")
        if self.note:
            lines.append(f"  note: {self.note}")
        return "\n".join(lines)


def grade(scenario: Scenario, original: Feed, edited: Feed,
          cost: Optional[dict] = None,
          validator: Callable[[Feed], List[str]] = validate_feed) -> GradeReport:
    cost = cost or {}

    # validity
    verrors = validator(edited)
    validity = DimensionResult(passed=not verrors,
                               detail="" if not verrors else f"{len(verrors)} error(s)",
                               checks=[Check(e, False, "") for e in verrors])

    # correctness
    cchecks = scenario.correctness(original, edited)
    correctness = DimensionResult(passed=all(c.ok for c in cchecks), checks=cchecks)

    # integrity (optional; defaults to pass if not specified)
    if scenario.integrity is not None:
        ichecks = scenario.integrity(original, edited)
        integrity = DimensionResult(passed=all(c.ok for c in ichecks), checks=ichecks)
    else:
        integrity = DimensionResult(passed=True, detail="(none specified)")

    # damage
    unsanctioned = [c for c in entity_changes(original, edited)
                    if not scenario.damage_ok(c, original, edited)]
    damage = DimensionResult(
        passed=not unsanctioned,
        detail="" if not unsanctioned else f"{len(unsanctioned)} unsanctioned change(s)",
        checks=[Check(str(c), False, "") for c in unsanctioned])

    return GradeReport(
        scenario_id=scenario.id, tool_fit=scenario.tool_fit,
        validity=validity, correctness=correctness, integrity=integrity,
        damage=damage, cost=cost, note=scenario.note)
