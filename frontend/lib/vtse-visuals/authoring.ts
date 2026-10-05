import type { VisualTeachingImageInput } from "@/lib/api/curriculumStructure";
import type { VtseVisualBinding, VtseVisuals } from "@/lib/types";
import type { VtseAuthorSlot } from "@/lib/vtse-visuals/slots";

/** Load a saved VTSE package into the shared annotation editor. */
export function vtsePackageToImages(
  pkg: VtseVisuals | null | undefined
): VisualTeachingImageInput[] {
  return (pkg?.images ?? []).map((image) => ({
    id: image.id,
    asset_key: image.asset_key,
    storage_key: image.storage_key,
    mime_type: image.mime_type,
    title: image.title ?? "",
    teaching_purpose: image.teaching_purpose ?? "",
    natural_width: image.natural_width,
    natural_height: image.natural_height,
    content_hash: image.content_hash,
    annotations_status: image.annotations_status === "stale" ? "stale" : "confirmed",
    regions: (image.regions ?? []).map((region) => ({
      region_id: region.region_id,
      label: region.label ?? "",
      teaching_purpose: region.teaching_purpose ?? "",
      shape: region.shape || "rect",
      geometry: region.geometry ?? {},
      focus_point: region.focus_point ?? null,
      label_box: region.label_box ?? null,
      highlight_color: region.highlight_color ?? null,
      label_bg_color: region.label_bg_color ?? null,
      label_text_color: region.label_text_color ?? null,
      bindings: region.bindings ?? [],
    })),
    anchors: image.anchors ?? [],
    connections: image.connections ?? [],
  }));
}

/** Persist editor images as a VTSE package. Labels are not rewritten from slots. */
export function imagesToVtsePackage(images: VisualTeachingImageInput[]): VtseVisuals {
  return {
    images: images.map((image) => ({
      id: image.id || image.asset_key,
      asset_key: image.asset_key,
      storage_key: image.storage_key,
      mime_type: image.mime_type,
      title: image.title ?? "",
      teaching_purpose: image.teaching_purpose ?? "",
      natural_width: image.natural_width,
      natural_height: image.natural_height,
      content_hash: image.content_hash,
      annotations_status: image.annotations_status === "stale" ? "stale" : "confirmed",
      regions: (image.regions ?? []).map((region) => ({
        region_id: region.region_id,
        label: region.label ?? "",
        teaching_purpose: region.teaching_purpose ?? "",
        shape: region.shape,
        geometry: region.geometry,
        focus_point: region.focus_point ?? null,
        label_box: region.label_box ?? null,
        highlight_color: region.highlight_color ?? null,
        label_bg_color: region.label_bg_color ?? null,
        label_text_color: region.label_text_color ?? null,
        bindings: (region.bindings ?? []) as VtseVisualBinding[],
      })),
      anchors: image.anchors ?? [],
      connections: image.connections ?? [],
    })),
  };
}

export function bindingFromSlot(slot: VtseAuthorSlot): VtseVisualBinding {
  return {
    slot_kind: slot.slot_kind,
    slot_key: slot.slot_key,
    slot_index: slot.slot_index,
    side: slot.side,
  };
}
