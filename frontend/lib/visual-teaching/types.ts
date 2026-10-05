/** Visual Teaching types — mirror backend authored + runtime VisualState. */

export type AnnotationsStatus = "confirmed" | "stale";
export type RegionShape = "point" | "rect" | "ellipse" | "polygon";
export type ConnectionKind = "flow" | "compare" | "generic";

export type NormPoint = { x: number; y: number };

export type PointGeometry = { x: number; y: number };
export type RectGeometry = { x: number; y: number; w: number; h: number };
export type EllipseGeometry = { cx: number; cy: number; rx: number; ry: number };
export type PolygonGeometry = { points: NormPoint[] };

export type RegionGeometry =
  | PointGeometry
  | RectGeometry
  | EllipseGeometry
  | PolygonGeometry;

export type VisualState = {
  highlights: string[];
  pointer: string | null;
  labels_visible: string[];
  dim_others: boolean;
  zoom: { region_id: string } | null;
  arrows: string[];
};

export type VisualStatePatch = {
  highlights?: string[] | null;
  pointer?: string | null;
  labels_visible?: string[] | null;
  dim_others?: boolean;
  zoom?: { region_id: string } | null;
  arrows?: string[] | null;
};

export type VisualTeachingRegion = {
  region_id: string;
  label: string;
  teaching_purpose: string;
  sort_order: number;
  shape: RegionShape;
  geometry: RegionGeometry;
  focus_point?: NormPoint | null;
  /** Normalized label chrome box (drag/resize in authoring). Optional. */
  label_box?: RectGeometry | null;
  /** Hex colors for highlight / label chrome (optional; defaults applied at render). */
  highlight_color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
};

export type VisualTeachingAnchor = {
  anchor_id: string;
  label: string;
  point: NormPoint;
};

export type VisualTeachingConnection = {
  connection_id: string;
  from_anchor: string;
  to_anchor: string;
  label: string;
  teaching_purpose?: string;
  /** Internal compatibility default `flow` — not shown in authoring UI. */
  kind: ConnectionKind;
  color?: string | null;
  label_bg_color?: string | null;
  label_text_color?: string | null;
  label_box?: RectGeometry | null;
};

export type VisualTeachingImage = {
  id: string;
  asset_key: string;
  storage_key: string;
  mime_type: string;
  sort_order: number;
  title: string;
  teaching_purpose: string;
  natural_width: number;
  natural_height: number;
  content_hash: string;
  annotations_status: AnnotationsStatus;
  regions: VisualTeachingRegion[];
  anchors: VisualTeachingAnchor[];
  connections: VisualTeachingConnection[];
};

export type ConceptVisualTeaching = {
  images: VisualTeachingImage[];
};

export type SentenceVisualEvent = {
  sentence_index: number;
  patch: VisualStatePatch;
};

export type BoardWriteRuntime = {
  sentence_index: number;
  text: string;
};

/** Runtime board visual payload (`type: concept_visual_teaching`). */
export type ConceptVisualTeachingRuntime = {
  type: "concept_visual_teaching";
  done?: boolean;
  concept_id?: string;
  scene_index?: number;
  beat_index?: number;
  sentence_index?: number;
  scene_count?: number;
  beat_count?: number;
  asset_key?: string;
  image_path?: string;
  image?: {
    asset_key?: string;
    mime_type?: string;
    natural_width?: number;
    natural_height?: number;
    title?: string;
  };
  regions?: VisualTeachingRegion[];
  anchors?: VisualTeachingAnchor[];
  connections?: VisualTeachingConnection[];
  visual_state?: VisualState;
  enter_effects?: Array<{ type: string }>;
  speak?: string;
  writes?: BoardWriteRuntime[];
  sentence_events?: SentenceVisualEvent[];
  capabilities_used?: string[];
};

export const SVG_VIEWBOX = 1000;

export function emptyVisualState(): VisualState {
  return {
    highlights: [],
    pointer: null,
    labels_visible: [],
    dim_others: false,
    zoom: null,
    arrows: [],
  };
}
