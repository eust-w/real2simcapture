from __future__ import annotations

import re
from typing import Any


_PRIOR_BY_CATEGORY = {
    "bottle": "container_plastic_or_glass",
    "cup": "container_ceramic_plastic_or_glass",
    "container": "container_material_unknown",
    "box": "container_cardboard_plastic_or_wood",
    "crate": "container_wood_plastic_or_metal",
    "table": "furniture_composite",
    "desk": "furniture_composite",
    "shelf": "furniture_composite",
    "cabinet": "furniture_composite",
    "chair": "furniture_composite",
    "floor": "architectural_floor_surface",
    "wall": "architectural_wall_surface",
    "ceiling": "architectural_ceiling_surface",
    "door": "architectural_door_surface",
    "window": "glass",
}

_TOKEN_PRIORS = [
    ("steel", "metal"),
    ("metal", "metal"),
    ("aluminum", "metal"),
    ("wood", "wood"),
    ("plastic", "plastic"),
    ("glass", "glass"),
    ("ceramic", "ceramic"),
    ("rubber", "rubber"),
    ("fabric", "fabric"),
    ("cloth", "fabric"),
    ("paper", "paper"),
    ("cardboard", "cardboard"),
    ("concrete", "concrete"),
]

_GENERATED_SOURCES = {"category_prior", "not_provided"}
_MATERIAL_KEYS = ("material_category", "material_class", "material_type", "material")


def resolve_material_metadata(category: str | None, source: dict[str, Any] | None = None) -> dict[str, str]:
    material_category = provided_material_category(source)
    source_name = str(source.get("material_category_source") or "") if isinstance(source, dict) else ""
    if material_category and source_name not in _GENERATED_SOURCES:
        return {"material_category": material_category, "material_category_source": "provided"}

    category_key = normalize_material_category(category)
    if category_key:
        if category_key in _PRIOR_BY_CATEGORY:
            return {"material_category": _PRIOR_BY_CATEGORY[category_key], "material_category_source": "category_prior"}
        for token, material in _TOKEN_PRIORS:
            if token in category_key:
                return {"material_category": material, "material_category_source": "category_prior"}
    return {"material_category": "unknown", "material_category_source": "not_provided"}


def provided_material_category(source: dict[str, Any] | None) -> str | None:
    if not isinstance(source, dict):
        return None
    for key in _MATERIAL_KEYS:
        value = normalize_material_category(source.get(key))
        if value:
            return value
    return None


def normalize_material_category(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in _MATERIAL_KEYS:
            normalized = normalize_material_category(value.get(key))
            if normalized:
                return normalized
        return None
    if value is None:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip()).strip("_").lower()
    return normalized or None
