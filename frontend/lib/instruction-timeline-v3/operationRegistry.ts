import { buildAnnotationEntity, supersedeAnnotationsForNewOp } from "@/lib/instruction-timeline-v3/annotationLifecycle";
import { buildHighlightEntity, retireActiveHighlights } from "@/lib/instruction-timeline-v3/highlightLifecycle";
import type {
  AnnotateEntityOp,
  HighlightEntityOp,
  RuntimeValidationError,
  SceneOperation,
} from "@/lib/instruction-timeline-v3/types";
import { SceneStore } from "@/lib/instruction-timeline-v3/sceneStore";

export interface OperationContext {
  sceneStore: SceneStore;
  committedOps: Set<string>;
}

export interface OperationHandler<T extends SceneOperation = SceneOperation> {
  type: T["op_type"];
  validate(op: T, context: OperationContext): RuntimeValidationError[];
  execute(op: T, context: OperationContext): RuntimeValidationError[];
  postValidate(op: T, context: OperationContext): RuntimeValidationError[];
}

function err(
  code: RuntimeValidationError["code"],
  message: string,
  details?: Record<string, unknown>,
): RuntimeValidationError {
  return { code, message, details };
}

const addEntityHandler: OperationHandler<Extract<SceneOperation, { op_type: "add_entity" }>> = {
  type: "add_entity",
  validate(op, ctx) {
    if (ctx.sceneStore.has(op.payload.entity.entity_id)) {
      return [err("PRECONDITION_FAILED", "Entity already exists", { entity_id: op.payload.entity.entity_id })];
    }
    return [];
  },
  execute(op, ctx) {
    ctx.sceneStore.apply((draft) => {
      draft.entities_by_id[op.payload.entity.entity_id] = op.payload.entity;
      if (!draft.root_order.includes(op.payload.entity.entity_id)) {
        draft.root_order.push(op.payload.entity.entity_id);
        draft.root_order.sort();
      }
    });
    return [];
  },
  postValidate(op, ctx) {
    return ctx.sceneStore.has(op.payload.entity.entity_id)
      ? []
      : [err("POSTCONDITION_FAILED", "Entity was not created", { entity_id: op.payload.entity.entity_id })];
  },
};

const removeEntityHandler: OperationHandler<
  Extract<SceneOperation, { op_type: "remove_entity" }>
> = {
  type: "remove_entity",
  validate(op, ctx) {
    if (!ctx.sceneStore.has(op.payload.entity_id)) {
      return [err("PRECONDITION_FAILED", "Entity does not exist", { entity_id: op.payload.entity_id })];
    }
    return [];
  },
  execute(op, ctx) {
    ctx.sceneStore.apply((draft) => {
      const existing = draft.entities_by_id[op.payload.entity_id];
      if (!existing) return;
      draft.entities_by_id[op.payload.entity_id] = {
        ...existing,
        lifecycle: {
          ...existing.lifecycle,
          state: "inactive",
          deleted_by_op: op.operation_id,
        },
      };
    });
    return [];
  },
  postValidate(op, ctx) {
    const entity = ctx.sceneStore.get(op.payload.entity_id);
    return entity?.lifecycle.state === "inactive"
      ? []
      : [err("POSTCONDITION_FAILED", "Entity was not deactivated", { entity_id: op.payload.entity_id })];
  },
};

const connectEntitiesHandler: OperationHandler<
  Extract<SceneOperation, { op_type: "connect_entities" }>
> = {
  type: "connect_entities",
  validate(op, ctx) {
    const errors: RuntimeValidationError[] = [];
    if (!ctx.sceneStore.has(op.payload.from_id)) {
      errors.push(err("PRECONDITION_FAILED", "from_id is missing", { from_id: op.payload.from_id }));
    }
    if (!ctx.sceneStore.has(op.payload.to_id)) {
      errors.push(err("PRECONDITION_FAILED", "to_id is missing", { to_id: op.payload.to_id }));
    }
    if (ctx.sceneStore.has(op.payload.edge_id)) {
      errors.push(err("PRECONDITION_FAILED", "edge_id already exists", { edge_id: op.payload.edge_id }));
    }
    return errors;
  },
  execute(op, ctx) {
    const from = ctx.sceneStore.get(op.payload.from_id);
    const to = ctx.sceneStore.get(op.payload.to_id);
    if (!from || !to) {
      return [err("EXECUTION_FAILED", "Cannot execute connect_entities due to missing endpoint")];
    }

    const relation =
      typeof op.payload.relation === "string" && op.payload.relation.length > 0
        ? op.payload.relation
        : "leads_to";
    ctx.sceneStore.apply((draft) => {
      draft.entities_by_id[op.payload.edge_id] = {
        entity_id: op.payload.edge_id,
        entity_type: "Edge",
        kind: "primitive",
        version: 1,
        spatial: {
          x: 0,
          y: 0,
          w: 0,
          h: 0,
        },
        semantic: {
          role: relation,
          payload: {
            edge_source: op.payload.edge_source ?? "synthesized",
          },
        },
        render: { layer: 1, style_token: op.payload.style_token },
        lifecycle: {
          state: "active",
          created_by_op: op.operation_id,
        },
        from_id: op.payload.from_id,
        to_id: op.payload.to_id,
      };
      draft.root_order.push(op.payload.edge_id);
      draft.root_order.sort();
    });
    return [];
  },
  postValidate(op, ctx) {
    const edge = ctx.sceneStore.get(op.payload.edge_id);
    return edge?.entity_type === "Edge"
      ? []
      : [err("POSTCONDITION_FAILED", "Edge was not created", { edge_id: op.payload.edge_id })];
  },
};

const annotateEntityHandler: OperationHandler<AnnotateEntityOp> = {
  type: "annotate_entity",
  validate(op, ctx) {
    if (!ctx.sceneStore.has(op.payload.target_id)) {
      return [err("PRECONDITION_FAILED", "Annotation target missing", { target_id: op.payload.target_id })];
    }
    if (ctx.sceneStore.has(op.payload.annotation_id)) {
      return [err("PRECONDITION_FAILED", "annotation_id already exists", { annotation_id: op.payload.annotation_id })];
    }
    return [];
  },
  execute(op, ctx) {
    ctx.sceneStore.apply((draft) => {
      supersedeAnnotationsForNewOp(draft.entities_by_id, op.payload.target_id, op.operation_id);
      draft.entities_by_id[op.payload.annotation_id] = buildAnnotationEntity(op);
      if (!draft.root_order.includes(op.payload.annotation_id)) {
        draft.root_order.push(op.payload.annotation_id);
        draft.root_order.sort();
      }
    });
    return [];
  },
  postValidate(op, ctx) {
    const annotation = ctx.sceneStore.get(op.payload.annotation_id);
    return annotation?.entity_type === "Annotation"
      ? []
      : [err("POSTCONDITION_FAILED", "Annotation not created", { annotation_id: op.payload.annotation_id })];
  },
};

const highlightEntityHandler: OperationHandler<HighlightEntityOp> = {
  type: "highlight_entity",
  validate(op, ctx) {
    const missing = op.payload.target_ids.filter((targetId) => !ctx.sceneStore.has(targetId));
    if (missing.length > 0) {
      return [err("PRECONDITION_FAILED", "Highlight targets missing", { missing })];
    }
    if (ctx.sceneStore.has(op.payload.highlight_id)) {
      return [err("PRECONDITION_FAILED", "highlight_id already exists", { highlight_id: op.payload.highlight_id })];
    }
    return [];
  },
  execute(op, ctx) {
    ctx.sceneStore.apply((draft) => {
      retireActiveHighlights(draft.entities_by_id, op.operation_id);
      draft.entities_by_id[op.payload.highlight_id] = buildHighlightEntity(op);
      if (!draft.root_order.includes(op.payload.highlight_id)) {
        draft.root_order.push(op.payload.highlight_id);
        draft.root_order.sort();
      }
    });
    return [];
  },
  postValidate(op, ctx) {
    const highlight = ctx.sceneStore.get(op.payload.highlight_id);
    return highlight?.entity_type === "Highlight"
      ? []
      : [err("POSTCONDITION_FAILED", "Highlight not created", { highlight_id: op.payload.highlight_id })];
  },
};

export class OperationRegistry {
  private handlers = new Map<SceneOperation["op_type"], OperationHandler>();

  public register<T extends SceneOperation>(handler: OperationHandler<T>): void {
    this.handlers.set(handler.type, handler as OperationHandler);
  }

  public get<T extends SceneOperation["op_type"]>(
    type: T,
  ): OperationHandler<Extract<SceneOperation, { op_type: T }>> | undefined {
    return this.handlers.get(type) as OperationHandler<
      Extract<SceneOperation, { op_type: T }>
    > | undefined;
  }
}

export function createDefaultOperationRegistry(): OperationRegistry {
  const registry = new OperationRegistry();
  registry.register(addEntityHandler);
  registry.register(removeEntityHandler);
  registry.register(connectEntitiesHandler);
  registry.register(annotateEntityHandler);
  registry.register(highlightEntityHandler);
  return registry;
}
