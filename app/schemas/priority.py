from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Category, Level, Priority, RuleSignal


class PriorityEvaluateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    category: Optional[Category] = None  # if omitted, the engine infers it


class PriorityEvaluateResponse(BaseModel):
    category: Category
    category_confidence: float
    priority: Priority
    severity: Level
    impact: Level
    safety_risk: bool
    sla_hours: int
    needs_manual_review: bool
    matched_rules: list[str]
    source: str = "rule_based"
    confidence: float = 0.0


class PriorityMatrixEntryCreate(BaseModel):
    category: Category
    severity: Level
    impact: Level
    safety_risk: bool = False
    priority: Priority
    sla_hours: int = Field(gt=0)


class PriorityMatrixEntryRead(PriorityMatrixEntryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


class PriorityKeywordRuleCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=100)
    signal: RuleSignal
    weight: int = Field(default=1, ge=1, le=10)
    category: Optional[Category] = None


class PriorityKeywordRuleRead(PriorityKeywordRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
