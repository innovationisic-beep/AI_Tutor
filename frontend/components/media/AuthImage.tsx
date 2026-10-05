"use client";

import { useEffect, useRef, useState } from "react";
import { AuthImageResource, loadAuthImageSrc } from "@/components/media/authImageResource";

const TOKEN_KEY = "ai_tutor_token";

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Renders an image from an endpoint that requires a bearer token.
 *
 * A plain `<img src>` cannot send Authorization headers, so the bytes are
 * fetched and handed to the element as a blob URL. Avoids putting tokens in
 * URLs, which would leak them into browser history and server logs.
 *
 * The fetch follows `src` only. A new `onLoadError` identity must not refetch
 * or drop the current blob. A real src change keeps the previous image until
 * the next blob is ready, then revokes the old URL after that paint.
 */
export function AuthImage({
  src,
  alt,
  className,
  onLoadError,
  onDecoded,
}: {
  src: string;
  alt: string;
  className?: string;
  onLoadError?: () => void;
  /** Fires when the decoded `<img>` has natural dimensions. */
  onDecoded?: (img: HTMLImageElement) => void;
}) {
  const resourceRef = useRef<AuthImageResource | null>(null);
  if (resourceRef.current == null) {
    resourceRef.current = new AuthImageResource({
      createObjectURL: (blob) => URL.createObjectURL(blob),
      revokeObjectURL: (url) => URL.revokeObjectURL(url),
    });
  }
  const onLoadErrorRef = useRef(onLoadError);
  onLoadErrorRef.current = onLoadError;
  resourceRef.current.setOnLoadError(() => onLoadErrorRef.current?.());

  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const pendingReleaseRef = useRef<string | null>(null);

  useEffect(() => {
    const resource = resourceRef.current!;
    let active = true;
    const token = readToken();
    const generation = resource.start(token);
    if (!token) {
      setObjectUrl(resource.objectUrl);
      setFailed(resource.failed);
      return;
    }

    void loadAuthImageSrc({
      src,
      token,
      generation,
      resource,
      isActive: () => active,
      fetchBlob: async (url, bearer) => {
        const res = await fetch(url, { headers: { Authorization: `Bearer ${bearer}` } });
        if (!res.ok) throw new Error(String(res.status));
        return res.blob();
      },
    }).then((result) => {
      if (!active) {
        if (result.kind === "shown") resource.release(result.swap.nextUrl);
        return;
      }
      if (result.kind === "shown") {
        if (result.swap.previousUrl) pendingReleaseRef.current = result.swap.previousUrl;
        setObjectUrl(result.swap.nextUrl);
        setFailed(false);
        return;
      }
      if (result.kind === "failed") {
        setObjectUrl(resource.objectUrl);
        setFailed(true);
      }
    });

    return () => {
      active = false;
    };
    // Callback identity is held on onLoadErrorRef. Reloading here would blank the image.
  }, [src]);

  useEffect(() => {
    const pending = pendingReleaseRef.current;
    if (!pending) return;
    pendingReleaseRef.current = null;
    resourceRef.current?.release(pending);
  }, [objectUrl]);

  useEffect(() => {
    const resource = resourceRef.current;
    const pendingRelease = pendingReleaseRef;
    return () => {
      const queued = pendingRelease.current;
      pendingRelease.current = null;
      if (queued) resource?.release(queued);
      resource?.dispose();
    };
  }, []);

  if (failed) return null;
  if (!objectUrl) {
    return (
      <div
        className={className}
        aria-hidden
        style={{ background: "rgba(100,116,139,0.15)" }}
      />
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src={objectUrl}
      alt={alt}
      className={className}
      draggable={false}
      onDragStart={(e) => e.preventDefault()}
      onLoad={(e) => onDecoded?.(e.currentTarget)}
    />
  );
}
