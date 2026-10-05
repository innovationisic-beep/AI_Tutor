"use client";

import { useMemo, useRef, useState } from "react";
import { apiMediaUrl } from "@/lib/api/curriculumStructure";
import { VisualTeachingStage } from "@/lib/visual-teaching/VisualTeachingStage";
import type { VisualTeachingRegion } from "@/lib/visual-teaching/types";
import {
  resolveVtseHighlight,
  type VtseBeatVisual,
} from "@/lib/vtse-visuals/playback";

type TimelineBeat = {
  beat_id?: string;
  narration?: { segments?: Array<{ text?: string }> };
  metadata?: { vtse_visual?: VtseBeatVisual };
};

type PackageImage = {
  asset_key?: string;
  image_path?: string;
  natural_width?: number;
  natural_height?: number;
  regions?: VisualTeachingRegion[];
  anchors?: [];
  connections?: [];
};

type Props = {
  timeline: {
    beats?: TimelineBeat[];
    metadata?: { vtse_visual_package?: { images?: PackageImage[] } | null };
  };
  beatId: string | null;
  wordIndex: number;
  enabled: boolean;
  /** split: beside the board. stack: full width above it. */
  frame?: "split" | "stack";
  onUnavailable?: () => void;
};

export function VtseVisualCompanion({
  timeline,
  beatId,
  wordIndex,
  enabled,
  frame = "split",
  onUnavailable,
}: Props) {
  const [hidden, setHidden] = useState(false);
  const logged = useRef(false);
  const packageImages = timeline.metadata?.vtse_visual_package?.images;
  const view = useMemo(() => {
    if (!enabled || !packageImages?.length) return null;
    const resolved = resolveVtseHighlight({
      beats: timeline.beats || [],
      images: packageImages,
      beatId,
      narrationWordIndex: wordIndex,
    });
    if (!resolved) return null;
    const image =
      packageImages.find((item) => item.asset_key === resolved.assetKey) || packageImages[0];
    if (!image?.image_path) return null;
    if (process.env.NEXT_PUBLIC_V3_DEBUG === "1") {
      console.info("[VTSE_VISUAL] highlight", {
        beatId,
        wordIndex,
        cueIndex: resolved.cueIndex,
        regionIds: resolved.regionIds,
      });
    }
    return { image, regionIds: resolved.regionIds };
  }, [beatId, enabled, packageImages, timeline.beats, wordIndex]);

  if (!view || hidden || !view.image.image_path) return null;
  return (
    <div
      className="pointer-events-none relative z-[1] w-full min-w-0 overflow-hidden rounded-lg border border-slate-200/80 bg-white shadow-sm dark:border-white/10 dark:bg-zinc-900"
      data-testid="vtse-visual-companion"
    >
      <VisualTeachingStage
        imageUrl={apiMediaUrl(view.image.image_path)}
        naturalWidth={view.image.natural_width}
        naturalHeight={view.image.natural_height}
        regions={view.image.regions || []}
        anchors={view.image.anchors || []}
        connections={view.image.connections || []}
        className="h-auto w-full bg-transparent"
        imageClassName={
          frame === "stack"
            ? "!block !h-auto !max-h-[42vh] !w-full !object-contain"
            : "!block !h-auto !max-h-[70vh] !w-full !object-contain"
        }
        visualState={{
          highlights: view.regionIds,
          pointer: null,
          labels_visible: [],
          dim_others: false,
          zoom: null,
          arrows: [],
        }}
        onImageError={() => {
          if (!logged.current) {
            logged.current = true;
            console.warn("[VTSE_VISUAL] image_unavailable");
          }
          setHidden(true);
          onUnavailable?.();
        }}
      />
    </div>
  );
}
