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

# Spec §4.2 describes a tension as a *cross-system* disagreement ("tension:
# astrology suggests X; Human Design suggests Y") and calls it the thing "a
# single-system app cannot produce". One system disagreeing with itself is a
# property of that system's KB entries, not a cross-system signal, so it must
# not be reported as a tension.
MIN_TENSION_SYSTEMS = 2


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

    # Spec §4.2: "Convergence score per facet = share of *applicable* systems
    # agreeing in direction." Applicable means the system actually ran and
    # produced a usable result — confidence > 0. A system excluded by
    # degradation (e.g. Human Design with no birth time, confidence 0.0) is
    # not applicable and must not sit in the denominator; but a system that
    # ran and simply had nothing to say about *this* facet is applicable, and
    # its silence is exactly what stops a lone contributor from claiming full
    # agreement. Using the contributing systems as the denominator instead
    # would make every single-source facet score 1.0, which is no information
    # at all.
    applicable = {system for system, conf in confidences.items() if conf > 0.0}

    # Determinism must be structural, not an artifact of rounding: sort tags into
    # a single canonical order before any accumulation, so every facet's weight
    # summation happens in the same order regardless of the order the caller
    # passed tags in. This also gives provenance entries a stable tertiary order
    # (same system + element ties break on direction, then weight) instead of
    # falling back to whatever order the caller happened to supply.
    ordered_tags = sorted(tags, key=lambda t: (t.facet, t.system, t.element, t.direction, t.weight))

    accumulators: dict[str, _FacetAccumulator] = defaultdict(_FacetAccumulator)
    for tag in ordered_tags:
        if not tax.has(tag.facet):
            continue  # KB validation already rejects these; belt and braces at runtime
        if tag.system not in confidences:
            raise ValueError(
                f"synthesize: no confidence supplied for system {tag.system!r} "
                "(every system contributing a tag must have an explicit confidence entry)"
            )
        confidence = confidences[tag.system]
        if confidence <= 0.0:
            continue
        accumulators[tag.facet].add(tag, confidence)

    # Facets are collected per dimension as (emitted_dict, dominant_weight)
    # pairs. `dominant_weight` (the confidence-scaled accumulated weight of
    # the dominant direction, i.e. `acc.weights[dominant]`) drives the
    # ranking below but is deliberately not part of `emitted_dict` -- the
    # public response shape (spec §5.1) has no field for it.
    by_dimension: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    tensions_by_dimension: dict[str, list[dict]] = defaultdict(list)

    for facet_id, acc in accumulators.items():
        total = acc.weights["high"] + acc.weights["low"]
        if total <= 0.0:
            continue
        score = {d: acc.weights[d] / total for d in ("high", "low")}
        dominant = "high" if score["high"] >= score["low"] else "low"
        dominant_weight = acc.weights[dominant]

        # Numerator: distinct systems with at least one tag in the dominant
        # direction. Denominator: applicable systems (see above). `applicable`
        # is non-empty here by construction — a facet only accumulates from a
        # system whose confidence cleared the > 0 guard.
        convergence = len(acc.systems[dominant]) / len(applicable)

        facet = tax.get(facet_id)
        by_dimension[facet.dimension].append(
            (
                {
                    "facet": facet_id,
                    "label": facet.label,
                    "score": round(score[dominant], ROUND),
                    "direction": facet.label_for(dominant),
                    "convergence": round(convergence, ROUND),
                    "provenance": sorted(acc.provenance, key=lambda p: (p["system"], p["element"])),
                },
                dominant_weight,
            )
        )

        high_systems = sorted(acc.systems["high"])
        low_systems = sorted(acc.systems["low"])
        is_cross_system = len(acc.systems["high"] | acc.systems["low"]) >= MIN_TENSION_SYSTEMS
        if score["high"] >= threshold and score["low"] >= threshold and is_cross_system:
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

    def _rank_key(pair: tuple[dict, float]) -> tuple[float, float, str]:
        # Rank by purity-times-agreement first; a lone-source facet with all
        # its tags pointing one way scores exactly 1.0 regardless of how much
        # weight backs it, so `score * convergence` alone collapses to a
        # constant across most facets in a dimension (the knowledge-base
        # weight cancels out of `score`, and within one profile every
        # single-source facet shares the same convergence). Break that tie
        # with the accumulated dominant weight -- the evidential mass `score`
        # normalises away -- before falling back to `facet_id` as the final,
        # fully deterministic tiebreaker.
        emitted, dominant_weight = pair
        return (-(emitted["score"] * emitted["convergence"]), -dominant_weight, emitted["facet"])

    dimensions: dict[str, dict] = {}
    for dim_id in sorted(by_dimension, key=lambda d: tax.dimensions[d].order):
        ranked = sorted(by_dimension[dim_id], key=_rank_key)
        facets = [emitted for emitted, _dominant_weight in ranked]
        dimensions[dim_id] = {
            "label": tax.dimensions[dim_id].label,
            "summary_tags": [f["direction"] for f in facets[:SUMMARY_TAG_COUNT]],
            "facets": facets,
            "tensions": sorted(tensions_by_dimension[dim_id], key=lambda t: t["facet"]),
        }

    return {"dimensions": dimensions}
