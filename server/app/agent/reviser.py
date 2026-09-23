"""Local structured itinerary revision and bounded validation loop."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from typing import Any, Protocol

from app.agent.budget import AgentBudget
from app.agent.models import (
    CollectedInfo,
    Itinerary,
    TravelRequirement,
    ValidationIssue,
    ValidationResult,
)
from app.agent.validator import ItineraryValidator


MAX_VALIDATION_ROUNDS = 2


STRUCTURED_REVISER_SYSTEM_PROMPT = """
你是旅行 Agent 的局部行程修订器。

输入是当前 Itinerary、Validator 的 ValidationIssue、TravelRequirement 和相关 CollectedInfo。

规则：
- 只修改 ValidationIssue 指出的日期、POI 或时间段；
- 未出现问题的日期和行程项必须保持不变；
- 只能使用 CollectedInfo 中已有的 POI、路线、开放时间和预算事实；
- 只返回符合 Itinerary 的结构化数据，不要输出自然语言解释。
""".strip()


class StructuredRevisionClient(Protocol):
    """提供结构化行程修订结果的客户端。"""

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[Itinerary],
    ) -> Itinerary | dict[str, Any]:
        ...


class ItineraryReviser(Protocol):
    """局部行程修订器的最小接口。"""

    def revise(
        self,
        itinerary: Itinerary,
        issues: list[ValidationIssue],
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> Itinerary:
        ...


class LocalItineraryReviser:
    """调用结构化客户端，并拒绝超出问题范围的修改。"""

    def __init__(
        self,
        client: StructuredRevisionClient,
        budget: AgentBudget | None = None,
    ) -> None:
        self._client = client
        self._budget = budget

    def revise(
        self,
        itinerary: Itinerary,
        issues: list[ValidationIssue],
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> Itinerary:
        failures = [issue for issue in issues if issue.status == "fail"]
        if not failures:
            return itinerary.model_copy(deep=True)

        with (
            self._budget.stage("reviser")
            if self._budget
            else nullcontext()
        ):
            output = self._client.complete_structured(
                system_prompt=STRUCTURED_REVISER_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(
                    itinerary, issues, requirement, collected_info
                ),
                output_model=Itinerary,
            )
        revised = Itinerary.model_validate(output)
        self._validate_scope(itinerary, revised, failures)
        return revised

    @staticmethod
    def _build_user_prompt(
        itinerary: Itinerary,
        issues: list[ValidationIssue],
        requirement: TravelRequirement,
        collected_info: CollectedInfo,
    ) -> str:
        return (
            "Current Itinerary:\n"
            f"{itinerary.model_dump_json(indent=2)}\n\n"
            "Validation Issues:\n"
            f"{[issue.model_dump(mode='json') for issue in issues]}\n\n"
            "TravelRequirement:\n"
            f"{requirement.model_dump_json(indent=2)}\n\n"
            "Relevant CollectedInfo:\n"
            f"{collected_info.model_dump_json(indent=2)}"
        )

    @staticmethod
    def _validate_scope(
        original: Itinerary,
        revised: Itinerary,
        failures: list[ValidationIssue],
    ) -> None:
        if len(original.days) != len(revised.days):
            raise ValueError("Revision is out of scope: day count changed")

        global_issue = any(
            issue.day is None and not issue.related_poi_ids for issue in failures
        )
        for day_number, (old_day, new_day) in enumerate(
            zip(original.days, revised.days), start=1
        ):
            if old_day.date != new_day.date:
                raise ValueError("Revision is out of scope: day date changed")

            day_failures = [
                issue
                for issue in failures
                if issue.day is None or issue.day == day_number
            ]
            if global_issue:
                continue
            if not day_failures:
                if old_day != new_day:
                    raise ValueError(
                        f"Revision is out of scope: day {day_number} changed"
                    )
                continue

            unrestricted_day = any(
                not issue.related_poi_ids
                and (issue.day is None or issue.day == day_number)
                for issue in day_failures
            )
            if unrestricted_day:
                continue

            allowed_poi_ids = {
                poi_id
                for issue in day_failures
                for poi_id in issue.related_poi_ids
            }
            old_unaffected = [
                item for item in old_day.items if item.poi_id not in allowed_poi_ids
            ]
            new_unaffected = [
                item for item in new_day.items if item.poi_id not in allowed_poi_ids
            ]
            if old_unaffected != new_unaffected:
                raise ValueError(
                    f"Revision is out of scope: unaffected items in day {day_number} changed"
                )


@dataclass(frozen=True)
class ValidationLoopResult:
    """最终行程、最后一次校验结果和实际修订轮数。"""

    itinerary: Itinerary
    validation: ValidationResult
    revision_rounds: int


class ItineraryValidationLoop:
    """在有限轮次内执行 Validator → Reviser → Validator。"""

    def __init__(
        self,
        validator: ItineraryValidator,
        reviser: ItineraryReviser,
        *,
        max_rounds: int = MAX_VALIDATION_ROUNDS,
    ) -> None:
        if max_rounds < 0:
            raise ValueError("max_rounds must not be negative")
        self._validator = validator
        self._reviser = reviser
        self._max_rounds = max_rounds

    def run(
        self,
        requirement: TravelRequirement,
        itinerary: Itinerary,
        collected_info: CollectedInfo,
    ) -> ValidationLoopResult:
        current = itinerary.model_copy(deep=True)
        revision_rounds = 0

        while True:
            validation = self._validator.validate(
                requirement, current, collected_info
            )
            failures = [
                issue for issue in validation.issues if issue.status == "fail"
            ]
            if not failures or revision_rounds >= self._max_rounds:
                return ValidationLoopResult(
                    itinerary=current,
                    validation=validation,
                    revision_rounds=revision_rounds,
                )

            current = self._reviser.revise(
                current,
                validation.issues,
                requirement,
                collected_info,
            )
            revision_rounds += 1
