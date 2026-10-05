/**
 * Letterboxed object-fit:contain content rect inside a container.
 * Returns the image content box in container coordinates.
 */
export type FitBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export function fitImageBox(
  containerW: number,
  containerH: number,
  naturalW: number,
  naturalH: number
): FitBox {
  const cw = Math.max(0, containerW);
  const ch = Math.max(0, containerH);
  const nw = Math.max(0, naturalW);
  const nh = Math.max(0, naturalH);
  if (cw <= 0 || ch <= 0 || nw <= 0 || nh <= 0) {
    return { x: 0, y: 0, width: cw, height: ch };
  }
  const scale = Math.min(cw / nw, ch / nh);
  const width = nw * scale;
  const height = nh * scale;
  return {
    x: (cw - width) / 2,
    y: (ch - height) / 2,
    width,
    height,
  };
}
