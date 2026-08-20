# engine/kb/facets.py
"""The fixed facet taxonomy (spec §4.1).

KB trait tags always use direction "high"/"low"; this taxonomy supplies the
human-readable label for each direction, which is what surfaces in the API
response (e.g. direction "gut" rather than "high").
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.kb.version import KB_ROOT


@dataclass(frozen=True)
class Facet:
    id: str
    dimension: str
    label: str
    high_label: str
    low_label: str

    def label_for(self, direction: str) -> str:
        return self.high_label if direction == "high" else self.low_label


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    order: int
    facets: dict[str, Facet]


@dataclass(frozen=True)
class Taxonomy:
    dimensions: dict[str, Dimension]
    facets: dict[str, Facet]
    tension_threshold: float

    def has(self, facet_id: str) -> bool:
        return facet_id in self.facets

    def get(self, facet_id: str) -> Facet:
        return self.facets[facet_id]

    def dimension_of(self, facet_id: str) -> Dimension:
        return self.dimensions[self.get(facet_id).dimension]


@functools.cache
def load_taxonomy(root: Path | None = None) -> Taxonomy:
    path = (root or KB_ROOT) / "facets.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "kb.facets.v1":
        raise ValueError(f"{path}: expected schema kb.facets.v1, got {doc.get('schema')!r}")
    if doc.get("reviewed") is not True:
        raise ValueError(f"{path}: reviewed must be true")

    dimensions: dict[str, Dimension] = {}
    flat: dict[str, Facet] = {}
    for dim_id, dim in doc["dimensions"].items():
        facets: dict[str, Facet] = {}
        for facet_id, spec in dim["facets"].items():
            full_id = f"{dim_id}.{facet_id}"
            facet = Facet(
                id=full_id,
                dimension=dim_id,
                label=spec["label"],
                high_label=spec["high"],
                low_label=spec["low"],
            )
            facets[full_id] = facet
            flat[full_id] = facet
        dimensions[dim_id] = Dimension(
            id=dim_id, label=dim["label"], order=int(dim["order"]), facets=facets
        )

    return Taxonomy(
        dimensions=dimensions,
        facets=flat,
        tension_threshold=float(doc["config"]["tension_threshold"]),
    )
