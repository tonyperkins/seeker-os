"""Profile and filter API routes — editable config via settings UI."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from seeker_os.api.schemas import (
    ProfileResponse, ProfileUpdate,
    FiltersResponse, FiltersUpdate,
    AccuracyRulesResponse, AccuracyRulesUpdate, AccuracyRule,
    MessageResponse,
)
from seeker_os.config import Settings, ProfileConfig, FiltersConfig, FilterConfig, TitleFilters, CONFIG_DIR
from seeker_os.config_writer import write_profile, write_filters, write_accuracy_rules
from seeker_os.validation import KNOWN_RULE_TYPES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["profile"])

_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile", response_model=ProfileResponse)
def get_profile():
    """Get the full profile configuration."""
    settings = Settings()
    if not settings.profile:
        raise HTTPException(status_code=404, detail="No profile.yml loaded")
    p = settings.profile
    return ProfileResponse(
        user=p.user.model_dump(),
        contact=p.contact.model_dump(),
        location=p.location.model_dump(),
        comp=p.comp.model_dump(),
        experience=p.experience.model_dump(),
        employment=p.employment.model_dump(),
        blacklist=p.blacklist,
        resume=p.resume.model_dump(),
        cross_reference=p.cross_reference.model_dump(),
        hard_rejects=[hr.model_dump() for hr in p.hard_rejects],
        instructions=p.instructions,
    )


@router.put("/profile", response_model=MessageResponse)
def update_profile(body: ProfileUpdate):
    """Update profile configuration. Writes back to profile.yml."""
    settings = Settings()
    if not settings.profile:
        raise HTTPException(status_code=404, detail="No profile.yml loaded")

    p = settings.profile
    data = p.model_dump()

    # Merge updates — only update fields that are provided (not None)
    if body.user is not None:
        data["user"] = body.user
    if body.contact is not None:
        data["contact"] = body.contact.model_dump()
    if body.location is not None:
        data["location"] = body.location
    if body.comp is not None:
        data["comp"] = body.comp
    if body.experience is not None:
        data["experience"] = body.experience
    if body.employment is not None:
        data["employment"] = body.employment
    if body.blacklist is not None:
        data["blacklist"] = body.blacklist
    if body.resume is not None:
        data["resume"] = body.resume
    if body.cross_reference is not None:
        data["cross_reference"] = body.cross_reference
    if body.hard_rejects is not None:
        data["hard_rejects"] = body.hard_rejects
    if body.instructions is not None:
        data["instructions"] = body.instructions

    try:
        new_profile = ProfileConfig(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")

    path = write_profile(new_profile)
    return MessageResponse(message=f"Profile saved to {path.name}")


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

@router.get("/filters", response_model=FiltersResponse)
def get_filters():
    """Get filter configuration + title filters."""
    settings = Settings()
    if not settings.filters:
        raise HTTPException(status_code=404, detail="No filters.yml loaded")
    return FiltersResponse(
        filters=settings.filters.filters.model_dump(),
        title_filters=settings.filters.title_filters.model_dump(),
    )


@router.put("/filters", response_model=MessageResponse)
def update_filters(body: FiltersUpdate):
    """Update filter configuration. Writes back to filters.yml."""
    settings = Settings()
    if not settings.filters:
        raise HTTPException(status_code=404, detail="No filters.yml loaded")

    f = settings.filters
    filters_data = f.filters.model_dump()
    title_data = f.title_filters.model_dump()

    if body.filters is not None:
        filters_data.update(body.filters)
    if body.title_filters is not None:
        title_data.update(body.title_filters)

    try:
        new_filter_config = FiltersConfig(
            filters=FilterConfig(**filters_data),
            title_filters=TitleFilters(**title_data),
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}")

    path = write_filters(new_filter_config)
    return MessageResponse(message=f"Filters saved to {path.name}")


# ---------------------------------------------------------------------------
# Accuracy Rules
# ---------------------------------------------------------------------------

@router.get("/accuracy-rules", response_model=AccuracyRulesResponse)
def get_accuracy_rules():
    """Get all accuracy rules from accuracy_rules.yml."""
    rules_path = CONFIG_DIR / "accuracy_rules.yml"
    if not rules_path.exists():
        return AccuracyRulesResponse(rules=[])
    with open(rules_path) as f:
        data = yaml.safe_load(f) or {}
    raw_rules = data.get("rules", [])
    rules = []
    for r in raw_rules:
        rules.append(AccuracyRule(
            id=r.get("id", "unknown"),
            description=r.get("description", ""),
            type=r.get("type", ""),
            severity=r.get("severity", "medium"),
            phrases=r.get("phrases"),
            technologies=r.get("technologies"),
            patterns=r.get("patterns"),
        ))
    return AccuracyRulesResponse(rules=rules)


@router.put("/accuracy-rules", response_model=MessageResponse)
def update_accuracy_rules(body: AccuracyRulesUpdate):
    """Replace all accuracy rules in accuracy_rules.yml."""
    # Validate rule types
    for rule in body.rules:
        if rule.type not in KNOWN_RULE_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid rule type '{rule.type}' for rule '{rule.id}'. Valid types: {', '.join(sorted(KNOWN_RULE_TYPES))}",
            )
        if rule.severity not in ("high", "medium"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid severity '{rule.severity}' for rule '{rule.id}'. Must be 'high' or 'medium'.",
            )

    # Convert to plain dicts for the writer
    rules_data = []
    for rule in body.rules:
        d = {"id": rule.id, "description": rule.description, "type": rule.type, "severity": rule.severity}
        if rule.phrases is not None:
            d["phrases"] = rule.phrases
        if rule.technologies is not None:
            d["technologies"] = rule.technologies
        if rule.patterns is not None:
            d["patterns"] = rule.patterns
        rules_data.append(d)

    path = write_accuracy_rules(rules_data)
    return MessageResponse(message=f"Accuracy rules saved to {path.name}")


# ---------------------------------------------------------------------------
# AI Rule Generation
# ---------------------------------------------------------------------------

class AIGenerateRulesRequest(BaseModel):
    """POST /api/accuracy-rules/ai-generate — generate rules from natural language."""
    description: str


class AIGenerateRulesResponse(BaseModel):
    """Response with AI-generated rules."""
    rules: list[AccuracyRule]


@router.post("/accuracy-rules/ai-generate", response_model=AIGenerateRulesResponse)
def ai_generate_rules(body: AIGenerateRulesRequest):
    """Generate accuracy rules from a natural language description using the LLM.

    The user describes what they want in plain English, and the LLM converts
    that into structured accuracy rules.
    """
    settings = Settings()
    if not settings.providers:
        raise HTTPException(status_code=400, detail="No LLM providers configured")

    system_prompt = (_PROMPTS_DIR / "ai_rule_generator_system.txt").read_text(encoding="utf-8")

    user_prompt = f"""Generate accuracy rules based on this description:

{body.description}

Output the JSON now:"""

    try:
        from seeker_os.llm.router import ModelRouter
        router = ModelRouter(settings)
        response = router.generate(
            task="accuracy_validation",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )
    except Exception:
        logger.exception("LLM call failed for AI rule generation")
        raise HTTPException(status_code=500, detail="LLM call failed — see server logs for details")

    # Parse the JSON response
    import json
    text = response.text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last line (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.exception("LLM returned invalid JSON for AI rule generation. Raw text: %s", text[:500])
        raise HTTPException(
            status_code=500,
            detail="LLM returned invalid JSON — see server logs for details",
        )

    raw_rules = data.get("rules", [])
    rules = []
    for r in raw_rules:
        rule_type = r.get("type", "")
        if rule_type not in KNOWN_RULE_TYPES:
            continue
        rules.append(AccuracyRule(
            id=r.get("id", f"rule_{len(rules)}"),
            description=r.get("description", ""),
            type=rule_type,
            severity=r.get("severity", "medium"),
            phrases=r.get("phrases"),
            technologies=r.get("technologies"),
            patterns=r.get("patterns"),
        ))

    return AIGenerateRulesResponse(rules=rules)
