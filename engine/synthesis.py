"""The synthesis layer (spec §4.2).

Convergence and tension are the product differentiator: where systems agree we
say so and raise confidence; where they disagree we report the disagreement
instead of averaging it into mush.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from engine.kb.facets import Taxonomy, load_taxonomy
from engine.types import TraitTag

ROUND = 6
SUMMARY_TAG_COUNT = 3


@dataclass
class _FacetAccumulator:
    weights: dict[str, float] = field(default_factory=lambda: {"high": 0.0, "low": 0.0})
    systems: dict[str, set[str]] = field(default_factory=lambda: {"high": set(), "low": set()})
    provenance: list[dict] = field(default_factory=list)

    def add(self, tag: TraitTag, confidence: float) -> None:
        self.weights[tag.direction] += tag.weight * confidence
        self.systems[tag.direction].add(tag.system)
        self.provenance.append({"system": tag.system, "element": tag.element, "weight": tag.weight})


def synthesize(
    tags: list[TraitTag],
    confidences: dict[str, float],
    taxonomy: Taxonomy | None = None,
) -> dict:
    tax = taxonomy or load_taxonomy()
    threshold = tax.tension_threshold

    accumulators: dict[str, _FacetAccumulator] = defaultdict(_FacetAccumulator)
    for tag in tags:
        if not tax.has(tag.facet):
            continue  # KB validation already rejects these; belt and braces at runtime
        confidence = confidences.get(tag.system, 1.0)
        if confidence <= 0.0:
            continue
        accumulators[tag.facet].add(tag, confidence)

    by_dimension: dict[str, list[dict]] = defaultdict(list)
    tensions_by_dimension: dict[str, list[dict]] = defaultdict(list)

    for facet_id, acc in accumulators.items():
        total = acc.weights["high"] + acc.weights["low"]
        if total <= 0.0:
            continue
        score = {d: acc.weights[d] / total for d in ("high", "low")}
        dominant = "high" if score["high"] >= score["low"] else "low"

        contributing = acc.systems["high"] | acc.systems["low"]
        convergence = len(acc.systems[dominant]) / len(contributing)

        facet = tax.get(facet_id)
        by_dimension[facet.dimension].append(
            {
                "facet": facet_id,
                "label": facet.label,
                "score": round(score[dominant], ROUND),
                "direction": facet.label_for(dominant),
                "convergence": round(convergence, ROUND),
                "provenance": sorted(acc.provenance, key=lambda p: (p["system"], p["element"])),
            }
        )

        if score["high"] >= threshold and score["low"] >= threshold:
            high_systems = sorted(acc.systems["high"])
            low_systems = sorted(acc.systems["low"])
            tensions_by_dimension[facet.dimension].append(
                {
                    "facet": facet_id,
                    "high": {"direction": facet.high_label, "systems": high_systems},
                    "low": {"direction": facet.low_label, "systems": low_systems},
                    "text": (
                        f"tension: {', '.join(high_systems)} suggests {facet.high_label}; "
                        f"{', '.join(low_systems)} suggests {facet.low_label}"
                    ),
                }
            )

    dimensions: dict[str, dict] = {}
    for dim_id in sorted(by_dimension, key=lambda d: tax.dimensions[d].order):
        facets = sorted(
            by_dimension[dim_id],
            key=lambda f: (-(f["score"] * f["convergence"]), f["facet"]),
        )
        dimensions[dim_id] = {
            "label": tax.dimensions[dim_id].label,
            "summary_tags": [f["direction"] for f in facets[:SUMMARY_TAG_COUNT]],
            "facets": facets,
            "tensions": sorted(tensions_by_dimension[dim_id], key=lambda t: t["facet"]),
        }

    return {"dimensions": dimensions}
