/**
 * Blob-URL lifetime for AuthImage.
 *
 * A new error callback is not a new image. The visible blob stays until the
 * next src has bytes, then the previous URL is released by the caller after
 * paint. Stale loads neither replace the image nor invoke the error callback.
 */

export type AuthImageSwap = {
  nextUrl: string;
  previousUrl: string | null;
};

export type AuthImageLoadResult =
  | { kind: "shown"; swap: AuthImageSwap }
  | { kind: "failed" }
  | { kind: "stale" };

export class AuthImageResource {
  objectUrl: string | null = null;
  failed = false;
  private generation = 0;
  private onError: (() => void) | undefined;

  constructor(
    private readonly urls: {
      createObjectURL: (blob: Blob) => string;
      revokeObjectURL: (url: string) => void;
    }
  ) {}

  /** Latest failure callback. Replacing it does not touch the visible URL. */
  setOnLoadError(callback: (() => void) | undefined) {
    this.onError = callback;
  }

  /**
   * Open a load generation. A missing token fails immediately and still calls
   * the latest error callback. An existing blob is left in place when a token
   * is present so the caller can keep painting it.
   */
  start(token: string | null): number {
    const generation = ++this.generation;
    if (!token) this.fail(generation);
    return generation;
  }

  isCurrent(generation: number): boolean {
    return generation === this.generation;
  }

  /**
   * Publish a decoded blob for this generation.
   * Does not revoke the previous URL; the caller releases it after the new
   * image is committed.
   */
  succeed(generation: number, blob: Blob): AuthImageSwap | null {
    if (!this.isCurrent(generation)) return null;
    const nextUrl = this.urls.createObjectURL(blob);
    if (!this.isCurrent(generation)) {
      this.urls.revokeObjectURL(nextUrl);
      return null;
    }
    const previousUrl = this.objectUrl;
    this.objectUrl = nextUrl;
    this.failed = false;
    return { nextUrl, previousUrl };
  }

  /** Revoke a URL that is no longer the visible image. */
  release(url: string | null) {
    if (!url || url === this.objectUrl) return;
    this.urls.revokeObjectURL(url);
  }

  /** Hide the image and notify. Stale generations are ignored. */
  fail(generation: number): boolean {
    if (!this.isCurrent(generation)) return false;
    this.failed = true;
    const previous = this.objectUrl;
    this.objectUrl = null;
    if (previous) this.urls.revokeObjectURL(previous);
    this.onError?.();
    return true;
  }

  /** Unmount: invalidate in-flight loads and revoke the visible blob. */
  dispose() {
    this.generation += 1;
    const current = this.objectUrl;
    this.objectUrl = null;
    if (current) this.urls.revokeObjectURL(current);
  }
}

export async function loadAuthImageSrc(args: {
  src: string;
  token: string;
  generation: number;
  resource: AuthImageResource;
  isActive: () => boolean;
  fetchBlob: (src: string, token: string) => Promise<Blob>;
}): Promise<AuthImageLoadResult> {
  try {
    const blob = await args.fetchBlob(args.src, args.token);
    if (!args.isActive() || !args.resource.isCurrent(args.generation)) return { kind: "stale" };
    const swap = args.resource.succeed(args.generation, blob);
    if (!swap) return { kind: "stale" };
    return { kind: "shown", swap };
  } catch {
    if (!args.isActive() || !args.resource.isCurrent(args.generation)) return { kind: "stale" };
    args.resource.fail(args.generation);
    return { kind: "failed" };
  }
}
