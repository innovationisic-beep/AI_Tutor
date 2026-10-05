import { computeSceneHash } from "@/lib/instruction-timeline-v3/hash";
import type { SceneEntity, SceneStoreSnapshot } from "@/lib/instruction-timeline-v3/types";

interface SceneStoreState {
  entities_by_id: Record<string, SceneEntity>;
  root_order: string[];
}

function cloneState(state: SceneStoreState): SceneStoreState {
  return structuredClone(state);
}

function buildIndexes(state: SceneStoreState): SceneStoreSnapshot["indexes"] {
  const edges_by_node: Record<string, string[]> = {};
  const children_by_parent: Record<string, string[]> = {};
  const by_type: Record<string, string[]> = {};

  Object.entries(state.entities_by_id)
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach(([id, entity]) => {
      if (!by_type[entity.entity_type]) by_type[entity.entity_type] = [];
      by_type[entity.entity_type].push(id);

      const parentId = entity.relations?.parent_id ?? null;
      if (parentId) {
        if (!children_by_parent[parentId]) children_by_parent[parentId] = [];
        children_by_parent[parentId].push(id);
      }

      if (entity.entity_type === "Edge") {
        const from = entity.from_id;
        const to = entity.to_id;
        if (!edges_by_node[from]) edges_by_node[from] = [];
        if (!edges_by_node[to]) edges_by_node[to] = [];
        edges_by_node[from].push(id);
        edges_by_node[to].push(id);
      }
    });

  Object.values(edges_by_node).forEach((ids) => ids.sort());
  Object.values(children_by_parent).forEach((ids) => ids.sort());
  Object.values(by_type).forEach((ids) => ids.sort());

  return {
    edges_by_node,
    children_by_parent,
    by_type,
  };
}

export class SceneStore {
  private state: SceneStoreState;

  public constructor(entities: Record<string, SceneEntity>, rootOrder: string[]) {
    this.state = {
      entities_by_id: { ...entities },
      root_order: [...rootOrder].sort(),
    };
  }

  public has(entityId: string): boolean {
    const entity = this.state.entities_by_id[entityId];
    return Boolean(entity && entity.lifecycle.state === "active");
  }

  public get(entityId: string): SceneEntity | undefined {
    return this.state.entities_by_id[entityId];
  }

  public apply(updater: (draft: SceneStoreState) => void): SceneStoreSnapshot {
    const draft = cloneState(this.state);
    updater(draft);
    this.state = draft;
    return this.snapshot();
  }

  public exportState(): SceneStoreState {
    return cloneState(this.state);
  }

  public restoreState(snapshot: SceneStoreState): SceneStoreSnapshot {
    this.state = cloneState(snapshot);
    return this.snapshot();
  }

  public snapshot(): SceneStoreSnapshot {
    const indexes = buildIndexes(this.state);
    const hash = computeSceneHash({
      entities_by_id: this.state.entities_by_id,
      root_order: this.state.root_order,
      indexes,
    });
    return {
      entities_by_id: { ...this.state.entities_by_id },
      root_order: [...this.state.root_order],
      indexes,
      scene_hash: hash,
    };
  }
}
