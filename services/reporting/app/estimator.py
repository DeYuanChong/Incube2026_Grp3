"""Deterministic, explainable ETA estimation (docs/04-ai-integration.md §2)."""

from . import config


def estimate(category: str, severity: str | None, open_count: int) -> tuple[float, str]:
    base = config.BASE_DAYS.get(category, 5.0)
    mult = config.SEVERITY_MULT.get(severity or "medium", 1.0)
    load_factor = 1 + min(open_count / config.CAPACITY_PER_DAY, 2.0)
    days = round(base * mult * load_factor, 1)
    pct = round((load_factor - 1) * 100)
    basis = (
        f"{category.replace('_', ' ').title()} defects typically take ~{base:g} days"
        f"{f' ({severity} severity)' if severity else ''}; "
        f"{open_count} issues currently open (+{pct}% backlog load)."
    )
    return days, basis
