# VTSE — Visual Teaching Strategy Engine

Pedagogical planning layer above CIR and Timeline V3.

## Product path (always on)

Authored VTSE → TeachingPlan → VTSECompiler → CIR → TimelinePlannerV3 → ITV3 is the only supported Zone 1 visual teaching path. There are no env rollout kill-switches for this path.

On authoring failure (missing/invalid template, expand/compile error): **text-only** (no board). No generic CIR LLM fallback.

```
CurriculumConcept.vtse_template → DeepSeek expand → forced strategy → TeachingPlan → VTSECompiler → CIR → TimelinePlannerV3
```

Strategies are locked by the authored template (`forced_strategy_id` via `selectors/strategy_selector.py`). Automatic shape-based strategy selection is not used in production Zone 1.

## CIR shell (always on for non-authored CIR)

```
CIR (validated) → TeachingPlan (lift) → VTSECompiler → CIR → TimelinePlannerV3
```

## Frontend emergency / debug (optional)

- `NEXT_PUBLIC_TIMELINE_V3_KILL_SWITCH=1` — FE-only: force legacy prose even if ITV3 is present.
- `NEXT_PUBLIC_CIR_INSTRUCTION_DEBUG=1` — local console lifecycle traces (default off).

## TDSL version

`0.1` — see `app/vtse/models/plan.py`

## Strategies

Registered in `app/vtse/registry/strategy_registry.py`:

- `hierarchy_concept_intro`
- `clustered_trait_list`
- `comparison_contrast`
- `cycle_process`
- `linear_process`
