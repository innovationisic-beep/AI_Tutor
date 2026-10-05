/**
 * AuthImage blob lifetime.
 * Run: npx tsx --test components/media/authImageResource.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { AuthImageResource, loadAuthImageSrc } from "./authImageResource";

const here = dirname(fileURLToPath(import.meta.url));

function harness() {
  const revoked: string[] = [];
  let seq = 0;
  const created: string[] = [];
  const resource = new AuthImageResource({
    createObjectURL: () => {
      const url = `blob:${++seq}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url) => {
      revoked.push(url);
    },
  });
  return { resource, revoked, created };
}

async function paint(
  resource: AuthImageResource,
  src: string,
  fetchBlob: (src: string, token: string) => Promise<Blob>,
  token: string | null = "token"
) {
  const generation = resource.start(token);
  if (!token) return { kind: "failed" as const, generation };
  const result = await loadAuthImageSrc({
    src,
    token,
    generation,
    resource,
    isActive: () => resource.isCurrent(generation),
    fetchBlob,
  });
  if (result.kind === "shown" && result.swap.previousUrl) {
    resource.release(result.swap.previousUrl);
  }
  return { ...result, generation };
}

test("same src + new callback does not fetch again or change the object URL", async () => {
  const { resource, created } = harness();
  let fetches = 0;
  const fetchBlob = async () => {
    fetches += 1;
    return new Blob(["a"]);
  };
  let boundSrc: string | null = null;
  const render = async (src: string, onError: () => void) => {
    resource.setOnLoadError(onError);
    if (boundSrc === src) return;
    boundSrc = src;
    await paint(resource, src, fetchBlob);
  };

  const first = () => {};
  const second = () => {};
  await render("/images/a", first);
  const url = resource.objectUrl;
  await render("/images/a", second);
  assert.equal(fetches, 1);
  assert.equal(created.length, 1);
  assert.equal(resource.objectUrl, url);
  assert.equal(resource.failed, false);
});

test("a parent rerender keeps the same object URL", async () => {
  const { resource } = harness();
  await paint(resource, "/images/a", async () => new Blob(["a"]));
  const url = resource.objectUrl;
  resource.setOnLoadError(() => {});
  resource.setOnLoadError(() => {});
  assert.equal(resource.objectUrl, url);
  assert.ok(url);
});

test("a new src fetches once and keeps the previous image until the swap", async () => {
  const { resource, revoked, created } = harness();
  let fetches = 0;
  const fetchBlob = async (src: string) => {
    fetches += 1;
    return new Blob([src]);
  };
  await paint(resource, "/images/a", fetchBlob);
  const firstUrl = resource.objectUrl;
  assert.equal(fetches, 1);
  assert.equal(revoked.length, 0);

  let releaseSecond: ((blob: Blob) => void) | null = null;
  const generation = resource.start("token");
  const pending = loadAuthImageSrc({
    src: "/images/b",
    token: "token",
    generation,
    resource,
    isActive: () => true,
    fetchBlob: () =>
      new Promise((resolve) => {
        fetches += 1;
        releaseSecond = resolve;
      }),
  });
  assert.equal(resource.objectUrl, firstUrl);
  assert.equal(fetches, 2);
  assert.equal(created.length, 1);

  releaseSecond!(new Blob(["b"]));
  const result = await pending;
  assert.equal(result.kind, "shown");
  if (result.kind !== "shown") return;
  assert.equal(result.swap.previousUrl, firstUrl);
  assert.equal(resource.objectUrl, result.swap.nextUrl);
  assert.notEqual(resource.objectUrl, firstUrl);
  assert.deepEqual(revoked, []);
  resource.release(result.swap.previousUrl);
  assert.deepEqual(revoked, [firstUrl]);
  assert.equal(created.length, 2);
});

test("unmount revokes the active blob", async () => {
  const { resource, revoked } = harness();
  await paint(resource, "/images/a", async () => new Blob(["a"]));
  const url = resource.objectUrl;
  assert.ok(url);
  resource.dispose();
  assert.equal(resource.objectUrl, null);
  assert.deepEqual(revoked, [url]);
});

test("a genuine load failure invokes the latest callback", async () => {
  const { resource, revoked } = harness();
  await paint(resource, "/images/a", async () => new Blob(["a"]));
  const shown = resource.objectUrl;
  const calls: string[] = [];
  resource.setOnLoadError(() => calls.push("old"));
  resource.setOnLoadError(() => calls.push("latest"));
  const generation = resource.start("token");
  const result = await loadAuthImageSrc({
    src: "/images/missing",
    token: "token",
    generation,
    resource,
    isActive: () => true,
    fetchBlob: async () => {
      throw new Error("404");
    },
  });
  assert.equal(result.kind, "failed");
  assert.deepEqual(calls, ["latest"]);
  assert.equal(resource.failed, true);
  assert.equal(resource.objectUrl, null);
  assert.deepEqual(revoked, [shown]);
});

test("a stale load does not replace the image or call the error callback", async () => {
  const { resource, created, revoked } = harness();
  await paint(resource, "/images/a", async () => new Blob(["a"]));
  const shown = resource.objectUrl;
  let calls = 0;
  resource.setOnLoadError(() => {
    calls += 1;
  });
  const stale = resource.start("token");
  const current = resource.start("token");
  const ignored = await loadAuthImageSrc({
    src: "/images/stale",
    token: "token",
    generation: stale,
    resource,
    isActive: () => false,
    fetchBlob: async () => new Blob(["stale"]),
  });
  const failed = resource.fail(stale);
  assert.equal(ignored.kind, "stale");
  assert.equal(failed, false);
  assert.equal(calls, 0);
  assert.equal(resource.objectUrl, shown);
  const shownNext = await loadAuthImageSrc({
    src: "/images/b",
    token: "token",
    generation: current,
    resource,
    isActive: () => true,
    fetchBlob: async () => new Blob(["b"]),
  });
  assert.equal(shownNext.kind, "shown");
  assert.equal(created.length, 2);
  assert.deepEqual(revoked, []);
  assert.notEqual(resource.objectUrl, shown);
});

test("a missing token calls the latest callback and does not invent a blob", () => {
  const { resource, created } = harness();
  const calls: string[] = [];
  resource.setOnLoadError(() => calls.push("latest"));
  resource.start(null);
  assert.deepEqual(calls, ["latest"]);
  assert.equal(resource.failed, true);
  assert.equal(created.length, 0);
});

test("AuthImage reloads only when src changes", () => {
  const source = readFileSync(join(here, "AuthImage.tsx"), "utf8");
  assert.match(source, /onLoadErrorRef\.current = onLoadError/);
  assert.match(source, /}, \[src\]\);/);
  assert.equal(source.includes("[src, onLoadError]"), false);
  assert.equal(source.includes("setObjectUrl(null)"), false);
  const companion = readFileSync(
    join(here, "../ai/timeline-v3/VtseVisualCompanion.tsx"),
    "utf8"
  );
  assert.match(companion, /onImageError=\{/);
  assert.match(companion, /highlights: view\.regionIds/);
});
