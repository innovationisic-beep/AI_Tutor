import type { ConceptVtseTemplate, VtseVisualBinding } from "@/lib/types";

export type VtseAuthorSlot = {
  slot_kind: VtseVisualBinding["slot_kind"];
  slot_key: string;
  slot_index: number;
  side: VtseVisualBinding["side"];
  label: string;
};

function slotToken(text: string): string {
  return text.trim().split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

export function listVtseAuthorSlots(
  template: ConceptVtseTemplate | null | undefined,
  conceptName: string
): VtseAuthorSlot[] {
  const strategy = String(template?.strategy_id || "");
  const payload = template?.payload || {};
  if (strategy === "comparison_contrast") {
    const slots: VtseAuthorSlot[] = [
      {
        slot_kind: "column",
        slot_key: `column:${slotToken(String(payload.left_label || "Left"))}`,
        slot_index: 0,
        side: "left",
        label: String(payload.left_label || "Left"),
      },
      {
        slot_kind: "column",
        slot_key: `column:${slotToken(String(payload.right_label || "Right"))}`,
        slot_index: 1,
        side: "right",
        label: String(payload.right_label || "Right"),
      },
    ];
    (payload.rows || []).forEach((row, index) => {
      const dimension = String(row.dimension || `Row ${index + 1}`);
      const key = `row:${slotToken(dimension)}`;
      for (const side of ["left", "right", "both"] as const) {
        slots.push({
          slot_kind: "row",
          slot_key: key,
          slot_index: index,
          side,
          label: `${dimension} (${side})`,
        });
      }
    });
    return slots;
  }
  const steps = payload.steps || [];
  if (strategy === "hierarchy_concept_intro" || strategy === "clustered_trait_list") {
    const root = conceptName.trim() || "Concept";
    const slots: VtseAuthorSlot[] = [
      {
        slot_kind: "trait",
        slot_key: `trait:${slotToken(root)}`,
        slot_index: 0,
        side: "",
        label: root,
      },
    ];
    steps.forEach((step, index) => {
      const label = String(step.label || step.title || `Trait ${index + 1}`);
      slots.push({
        slot_kind: "trait",
        slot_key: `trait:${slotToken(label)}`,
        slot_index: index + 1,
        side: "",
        label,
      });
    });
    return slots;
  }
  if (strategy === "linear_process" || strategy === "cycle_process") {
    return steps.map((step, index) => {
      const label = String(step.label || step.title || `Step ${index + 1}`);
      return {
        slot_kind: "step" as const,
        slot_key: `step:${slotToken(label)}`,
        slot_index: index,
        side: "" as const,
        label,
      };
    });
  }
  return [];
}
