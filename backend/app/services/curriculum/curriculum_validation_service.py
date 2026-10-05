from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.services.curriculum.curriculum_tree_service import CurriculumTreeService
from app.services.curriculum.topic_context_service import TopicContext


@dataclass
class ValidationIssue:
    code: str
    message: str
    path: str = ""


@dataclass
class ValidationResult:
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def ready_to_publish(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "errors": [
                {"code": e.code, "message": e.message, "path": e.path}
                for e in self.errors
            ],
            "warnings": [
                {"code": w.code, "message": w.message, "path": w.path}
                for w in self.warnings
            ],
            "summary": self.summary,
            "ready_to_publish": self.ready_to_publish,
        }


class CurriculumValidationService:
    def __init__(self, tree_service: CurriculumTreeService | None = None) -> None:
        self._tree = tree_service or CurriculumTreeService()

    @staticmethod
    def _check_vtse_visuals(
        result: ValidationResult,
        *,
        concept: Dict[str, Any],
        concept_name: str,
        concept_path: str,
    ) -> None:
        raw = concept.get("vtse_visuals")
        images = (raw or {}).get("images") if isinstance(raw, dict) else None
        if not images:
            return
        from app.services.visual_teaching.authored import collect_raw_image_publish_errors
        from app.services.vtse_visuals.slots import iter_vtse_slots, resolve_binding

        slots = iter_vtse_slots(
            concept.get("vtse_template"),
            concept_name=str(concept.get("display_name") or concept_name),
        )
        seen_assets: set[str] = set()
        for image in images:
            if not isinstance(image, dict):
                continue
            asset = str(image.get("asset_key") or "").strip()
            if not str(image.get("storage_key") or "").strip():
                result.errors.append(
                    ValidationIssue(
                        "VTSE_VISUAL_MISSING_STORAGE",
                        f'Concept "{concept_name}" VTSE image "{asset or "?"}" has no file.',
                        f"{concept_path}/vtse_visuals",
                    )
                )
            if asset and asset in seen_assets:
                result.errors.append(
                    ValidationIssue(
                        "VTSE_VISUAL_DUPLICATE_ASSET",
                        f'Concept "{concept_name}" has duplicate VTSE image "{asset}".',
                        f"{concept_path}/vtse_visuals",
                    )
                )
            if asset:
                seen_assets.add(asset)
            regions = list(image.get("regions") or [])
            bound = False
            for region in regions:
                if not isinstance(region, dict):
                    continue
                for binding in region.get("bindings") or []:
                    if not isinstance(binding, dict):
                        continue
                    bound = True
                    matches = resolve_binding(binding, slots)
                    if len(matches) != 1:
                        result.errors.append(
                            ValidationIssue(
                                "VTSE_VISUAL_UNBOUND_SLOT",
                                (
                                    f'Concept "{concept_name}" region '
                                    f'"{region.get("region_id") or "?"}" does not match '
                                    "exactly one current VTSE template slot."
                                ),
                                f"{concept_path}/vtse_visuals",
                            )
                        )
            if not bound:
                result.warnings.append(
                    ValidationIssue(
                        "VTSE_VISUAL_IMAGE_NO_REGIONS",
                        (
                            f'Concept "{concept_name}" VTSE image "{asset or "?"}" '
                            "has no bound region."
                        ),
                        f"{concept_path}/vtse_visuals",
                    )
                )
            code_map = {
                "VISUAL_TEACHING_STALE_ANNOTATIONS": "VTSE_VISUAL_STALE_ANNOTATIONS",
                "VISUAL_TEACHING_INVALID_GEOMETRY": "VTSE_VISUAL_INVALID_GEOMETRY",
                "VISUAL_TEACHING_DUPLICATE_REGION_ID": "VTSE_VISUAL_DUPLICATE_REGION",
                "VISUAL_TEACHING_INVALID_FOCUS_POINT": "VTSE_VISUAL_INVALID_GEOMETRY",
            }
            for code, msg in collect_raw_image_publish_errors(image):
                result.errors.append(
                    ValidationIssue(
                        code_map.get(code, "VTSE_VISUAL_INVALID"),
                        f'Concept "{concept_name}" {msg}',
                        f"{concept_path}/vtse_visuals",
                    )
                )

    @staticmethod
    def _check_story_hook(
        result: ValidationResult,
        *,
        concept: Dict[str, Any],
        concept_name: str,
        concept_path: str,
    ) -> None:
        """
        The Story Hook stage is AI-planned from the authored seed, so publishing a
        concept that teaches a Story Hook without a seed would leave the planner
        with nothing to ground on. Visuals attached to an unsequenced hook are
        never shown, which is an authoring mistake worth surfacing.
        """
        hook = concept.get("story_hook") or {}
        sequenced = "story_hook" in [
            str(s).strip().lower() for s in (concept.get("teaching_sequence") or [])
        ]
        seed = str(hook.get("body") or "").strip()
        visuals = list(hook.get("visuals") or [])

        if sequenced and not seed:
            result.errors.append(
                ValidationIssue(
                    "STORY_HOOK_MISSING_SEED",
                    (
                        f'Concept "{concept_name}" teaches a Story Hook but has no '
                        "Story Hook seed text"
                    ),
                    f"{concept_path}/story_hook",
                )
            )

        if visuals and not sequenced:
            result.warnings.append(
                ValidationIssue(
                    "STORY_HOOK_VISUALS_UNUSED",
                    (
                        f'Concept "{concept_name}" has Story Hook visuals but the '
                        "Story Hook stage is not in its teaching sequence"
                    ),
                    f"{concept_path}/story_hook",
                )
            )

    @staticmethod
    def _check_visual_teaching(
        result: ValidationResult,
        *,
        concept: Dict[str, Any],
        concept_name: str,
        concept_path: str,
    ) -> None:
        from app.services.visual_teaching.authored import (
            collect_raw_image_publish_errors,
            normalize_visual_teaching,
        )

        raw_vt = concept.get("visual_teaching") or {}
        raw_images = list(raw_vt.get("images") or []) if isinstance(raw_vt, dict) else []
        pkg = normalize_visual_teaching(raw_vt)
        seq = [
            str(s).strip().lower() for s in (concept.get("teaching_sequence") or [])
        ]
        sequenced = "visual_teaching" in seq

        if sequenced:
            if pkg is None or not pkg.images:
                result.errors.append(
                    ValidationIssue(
                        "VISUAL_TEACHING_MISSING_IMAGES",
                        (
                            f'Concept "{concept_name}" teaches Visual Teaching but has '
                            "no images"
                        ),
                        f"{concept_path}/visual_teaching",
                    )
                )
                return

            asset_keys: set[str] = set()
            for img in pkg.images:
                if not img.storage_key:
                    result.errors.append(
                        ValidationIssue(
                            "VISUAL_TEACHING_MISSING_BINARY",
                            (
                                f'Concept "{concept_name}" image "{img.asset_key}" '
                                "has no storage_key"
                            ),
                            f"{concept_path}/visual_teaching",
                        )
                    )
                if img.asset_key in asset_keys:
                    result.errors.append(
                        ValidationIssue(
                            "VISUAL_TEACHING_DUPLICATE_ASSET_KEY",
                            (
                                f'Concept "{concept_name}" has duplicate asset_key '
                                f'"{img.asset_key}"'
                            ),
                            f"{concept_path}/visual_teaching",
                        )
                    )
                asset_keys.add(img.asset_key)
                if not str(img.teaching_purpose or "").strip():
                    result.errors.append(
                        ValidationIssue(
                            "VISUAL_TEACHING_MISSING_PURPOSE",
                            (
                                f'Concept "{concept_name}" image "{img.asset_key}" '
                                "is missing teaching_purpose"
                            ),
                            f"{concept_path}/visual_teaching",
                        )
                    )
                if not img.regions:
                    result.warnings.append(
                        ValidationIssue(
                            "VISUAL_TEACHING_IMAGE_NO_REGIONS",
                            (
                                f'Concept "{concept_name}" image "{img.asset_key}" '
                                "has zero regions"
                            ),
                            f"{concept_path}/visual_teaching",
                        )
                    )
                for code, msg in collect_raw_image_publish_errors(
                    next(
                        (
                            ri
                            for ri in raw_images
                            if str((ri or {}).get("asset_key") or "") == img.asset_key
                        ),
                        img.model_dump(),
                    )
                ):
                    result.errors.append(
                        ValidationIssue(
                            code,
                            f'Concept "{concept_name}" {msg}',
                            f"{concept_path}/visual_teaching",
                        )
                    )

        elif pkg is not None and pkg.images:
            result.warnings.append(
                ValidationIssue(
                    "VISUAL_TEACHING_IMAGES_UNUSED",
                    (
                        f'Concept "{concept_name}" has Visual Teaching images but the '
                        "visual_teaching stage is not in its teaching sequence"
                    ),
                    f"{concept_path}/visual_teaching",
                )
            )

    async def validate(self, ctx: TopicContext) -> ValidationResult:
        tree = await self._tree.get_tree(ctx)
        zones = tree.get("zones") or []
        result = ValidationResult()

        if not zones:
            result.errors.append(
                ValidationIssue("NO_ZONES", "Topic has no curriculum zones", "zones")
            )

        zone_numbers = [z.get("zone_number") for z in zones]
        if 1 not in zone_numbers:
            result.errors.append(
                ValidationIssue(
                    "MISSING_CURRICULUM_ZONE_1",
                    "Curriculum Zone 1 (core teaching) is required",
                    "zones",
                )
            )

        if len(zone_numbers) != len(set(zone_numbers)):
            result.errors.append(
                ValidationIssue(
                    "DUPLICATE_ZONE_NUMBER",
                    "Duplicate curriculum zone numbers detected",
                    "zones",
                )
            )

        cluster_count = 0
        concept_count = 0
        zone_1_concept_count = 0

        for z in zones:
            zn = z.get("zone_number")
            zpath = f"zones/{zn}"
            clusters = z.get("clusters") or []

            if zn == 0 and clusters:
                result.errors.append(
                    ValidationIssue(
                        "ZONE_0_NO_CLUSTERS",
                        "Curriculum Zone 0 (curiosity) must not contain clusters",
                        zpath,
                    )
                )

            if zn != 0 and not clusters:
                result.errors.append(
                    ValidationIssue(
                        "ZONE_WITHOUT_CLUSTERS",
                        f"Curriculum Zone {zn} has no clusters",
                        zpath,
                    )
                )

            if zn == 0 and not clusters:
                result.warnings.append(
                    ValidationIssue(
                        "ZONE_0_TOPIC_CURIOSITY",
                        "Curriculum Zone 0 holds topic curiosity content (no clusters required)",
                        zpath,
                    )
                )

            if zn in (2, 3, 4) and not clusters:
                result.warnings.append(
                    ValidationIssue(
                        "EXTENSION_ZONE_EMPTY",
                        f"Curriculum Zone {zn} has no clusters",
                        zpath,
                    )
                )

            cluster_numbers = [c.get("cluster_number") for c in clusters]
            if len(cluster_numbers) != len(set(cluster_numbers)):
                result.errors.append(
                    ValidationIssue(
                        "DUPLICATE_CLUSTER_NUMBER",
                        f"Duplicate cluster numbers in Zone {zn}",
                        zpath,
                    )
                )

            for cl in clusters:
                cluster_count += 1
                cpath = f"{zpath}/clusters/{cl.get('cluster_number')}"
                concepts = cl.get("concepts") or []
                if not concepts:
                    result.errors.append(
                        ValidationIssue(
                            "CLUSTER_WITHOUT_CONCEPTS",
                            f"Cluster '{cl.get('title')}' has no concepts",
                            cpath,
                        )
                    )
                slugs = [c.get("slug") for c in concepts]
                if len(slugs) != len(set(slugs)):
                    result.errors.append(
                        ValidationIssue(
                            "DUPLICATE_CONCEPT_SLUG",
                            f"Duplicate concept slugs in cluster '{cl.get('title')}'",
                            cpath,
                        )
                    )
                concept_count += len(concepts)
                if zn == 1:
                    zone_1_concept_count += len(concepts)

                # HARD RULE: every concept must have a selected/valid VTSE template.
                from app.services.curriculum.concept_vtse_context import (
                    soft_normalize_vtse_template,
                )

                for ci, concept in enumerate(concepts):
                    cname = str(
                        concept.get("display_name") or concept.get("slug") or "concept"
                    )
                    concept_path = f"{cpath}/concepts/{ci}"
                    tmpl = soft_normalize_vtse_template(concept.get("vtse_template"))
                    if tmpl is None:
                        result.errors.append(
                            ValidationIssue(
                                "MISSING_VTSE_TEMPLATE",
                                f'Concept "{cname}" has no VTSE template selected',
                                concept_path,
                            )
                        )

                    self._check_story_hook(
                        result,
                        concept=concept,
                        concept_name=cname,
                        concept_path=concept_path,
                    )
                    self._check_visual_teaching(
                        result,
                        concept=concept,
                        concept_name=cname,
                        concept_path=concept_path,
                    )
                    mode = str(concept.get("teaching_sequence_mode") or "manual").strip().lower()
                    auto_status = str(
                        concept.get("teaching_sequence_auto_status") or ""
                    ).strip().lower()
                    self._check_vtse_visuals(
                        result,
                        concept=concept,
                        concept_name=cname,
                        concept_path=concept_path,
                    )
                    if mode == "auto" and auto_status != "resolved":
                        result.warnings.append(
                            ValidationIssue(
                                "TEACHING_SEQUENCE_AUTO_FALLBACK",
                                (
                                    f'Concept "{cname}" is set to Auto, but students will '
                                    "follow the manual order until preview or publish "
                                    "resolves an order."
                                ),
                                concept_path,
                            )
                        )

        if zone_1_concept_count == 1:
            result.warnings.append(
                ValidationIssue(
                    "ZONE_1_SINGLE_CONCEPT",
                    "Curriculum Zone 1 has only one concept",
                    "zones/1",
                )
            )

        result.summary = {
            "zone_count": len(zones),
            "cluster_count": cluster_count,
            "concept_count": concept_count,
            "ready_to_publish": result.ready_to_publish,
        }
        return result
