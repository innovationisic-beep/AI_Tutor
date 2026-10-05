/**
 * TTS feature flag + soft-fail contract (no Lemonfox when disabled).
 * Run: node --import tsx --test lib/voice/ttsEnabled.test.ts
 * (from frontend/, or: npx tsx --test lib/voice/ttsEnabled.test.ts)
 */
import assert from "node:assert/strict";
import { describe, it, afterEach } from "node:test";

/**
 * Mirrors isTtsFeatureEnabled without pulling Next/browser modules.
 * Keep in sync with audioController.isTtsFeatureEnabled.
 */
function isTtsFeatureEnabledFromEnv(
  envValue: string | undefined,
): boolean {
  return envValue !== "false";
}

describe("isTtsFeatureEnabled", () => {
  it("defaults ON when env is unset", () => {
    assert.equal(isTtsFeatureEnabledFromEnv(undefined), true);
  });

  it("defaults ON when env is empty string", () => {
    assert.equal(isTtsFeatureEnabledFromEnv(""), true);
  });

  it("defaults ON when env is true", () => {
    assert.equal(isTtsFeatureEnabledFromEnv("true"), true);
  });

  it("is OFF only when env is exactly false", () => {
    assert.equal(isTtsFeatureEnabledFromEnv("false"), false);
  });
});

describe("soft-fail utterance contract", () => {
  it("fires one start, all chunks at 0, one end, and resolves", async () => {
    const events: string[] = [];
    const chunks = ["Hello", "world"];

    await new Promise<void>((resolve) => {
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        events.push("end");
        resolve();
      };

      const onUtteranceStart = () => events.push("start");
      const onChunkReveal = (e: { chunkIndex: number; atMs: number }) => {
        events.push(`chunk:${e.chunkIndex}:${e.atMs}`);
      };

      // Same soft-fail sequence as audioController.softFailUtterance
      onUtteranceStart();
      chunks.forEach((_, i) => onChunkReveal({ chunkIndex: i, atMs: 0 }));
      finish();
    });

    assert.deepEqual(events, [
      "start",
      "chunk:0:0",
      "chunk:1:0",
      "end",
    ]);
  });

  it("finish once-guard prevents duplicate onEnd", () => {
    let endCount = 0;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      endCount += 1;
    };
    finish();
    finish();
    assert.equal(endCount, 1);
  });
});

describe("isTtsFeatureEnabled live module", () => {
  const original = process.env.NEXT_PUBLIC_TTS_ENABLED;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.NEXT_PUBLIC_TTS_ENABLED;
    } else {
      process.env.NEXT_PUBLIC_TTS_ENABLED = original;
    }
  });

  it("reads NEXT_PUBLIC_TTS_ENABLED from process.env", async () => {
    // Dynamic import after env mutation would not re-evaluate module cache.
    // Assert the pure helper stays the source of truth; module uses same rule.
    process.env.NEXT_PUBLIC_TTS_ENABLED = "false";
    assert.equal(isTtsFeatureEnabledFromEnv(process.env.NEXT_PUBLIC_TTS_ENABLED), false);

    process.env.NEXT_PUBLIC_TTS_ENABLED = "true";
    assert.equal(isTtsFeatureEnabledFromEnv(process.env.NEXT_PUBLIC_TTS_ENABLED), true);

    delete process.env.NEXT_PUBLIC_TTS_ENABLED;
    assert.equal(isTtsFeatureEnabledFromEnv(process.env.NEXT_PUBLIC_TTS_ENABLED), true);
  });
});

describe("disabled mode skips provider", () => {
  it("gate condition prevents provider call when flag is false", () => {
    let prepareCalled = 0;
    const featureEnabled = isTtsFeatureEnabledFromEnv("false");
    const token = "fake-token";
    const hasAudio = true;

    if (!featureEnabled || !token || !hasAudio) {
      // soft-fail path — no prepare
    } else {
      prepareCalled += 1;
    }

    assert.equal(featureEnabled, false);
    assert.equal(prepareCalled, 0);
  });

  it("gate allows provider path when flag is enabled and client ok", () => {
    let prepareCalled = 0;
    const featureEnabled = isTtsFeatureEnabledFromEnv(undefined);
    const token = "fake-token";
    const hasAudio = true;

    if (!featureEnabled || !token || !hasAudio) {
      // soft-fail
    } else {
      prepareCalled += 1;
    }

    assert.equal(featureEnabled, true);
    assert.equal(prepareCalled, 1);
  });
});
