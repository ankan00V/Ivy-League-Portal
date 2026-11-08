"use client";

import { useEffect, useRef } from "react";

const HAND_SOURCE =
  "https://images.higgs.ai/?default=1&output=webp&url=https%3A%2F%2Fd8j0ntlcm91z4.cloudfront.net%2Fuser_38xzZboKViGWJOttwIXH07lWA1P%2Fhf_20261030_025250_100df7b8-31fd-4614-aa4a-c1b7d5b6b273.png&w=1600&q=85";

const SOURCE_RECTS = {
  leftA: [0, 0.06, 0.47, 0.4],
  rightA: [0.53, 0.06, 0.47, 0.4],
  leftB: [0, 0.55, 0.47, 0.4],
  rightB: [0.53, 0.55, 0.47, 0.4],
} as const;

const LOOP_SECONDS = 20;
const LEVELS = [0, 0.26, 0.52, 0.78, 1] as const;

declare global {
  interface Window {
    __render?: (timeSeconds: number) => void;
  }
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function fract(value: number) {
  return value - Math.floor(value);
}

function hash(a: number, b: number) {
  return fract(Math.sin(a * 127.1 + b * 311.7) * 43758.5453);
}

function smooth(minimum: number, maximum: number, value: number) {
  const normalized = clamp((value - minimum) / Math.max(0.0001, maximum - minimum), 0, 1);
  return normalized * normalized * (3 - 2 * normalized);
}

function mixAt(time: number, on: number, off: number, duration: number) {
  return smooth(on, on + duration, time) * (1 - smooth(off, off + duration, time));
}

function createTile(
  image: HTMLImageElement,
  rect: readonly [number, number, number, number],
) {
  const [x, y, width, height] = rect;
  const sourceWidth = image.naturalWidth * width;
  const sourceHeight = image.naturalHeight * height;
  const tile = document.createElement("canvas");
  tile.width = 420;
  tile.height = Math.max(1, Math.round((sourceHeight / sourceWidth) * tile.width));

  const context = tile.getContext("2d");
  if (!context) return tile;
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    image,
    image.naturalWidth * x,
    image.naturalHeight * y,
    sourceWidth,
    sourceHeight,
    0,
    0,
    tile.width,
    tile.height,
  );
  return tile;
}

export default function DotMatrixHandsBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext("2d");
    if (!context) return;

    const fieldA = document.createElement("canvas");
    const fieldB = document.createElement("canvas");
    const fieldAContext = fieldA.getContext("2d", { willReadFrequently: true });
    const fieldBContext = fieldB.getContext("2d", { willReadFrequently: true });
    if (!fieldAContext || !fieldBContext) return;

    let width = 0;
    let height = 0;
    let columns = 0;
    let rows = 0;
    let step = 0;
    let rowStep = 0;
    let baseRadius = 0;
    let animationFrame = 0;
    let resizeFrame = 0;
    let disposed = false;
    let tiles: Record<keyof typeof SOURCE_RECTS, HTMLCanvasElement> | null = null;
    const startedAt = performance.now();
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      width = Math.max(1, bounds.width);
      height = Math.max(1, bounds.height);
      const pixelRatio = Math.min(2, window.devicePixelRatio || 1);

      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

      step = Math.max(5, width / 205);
      rowStep = step * 2.05;
      columns = Math.ceil(width / step);
      rows = Math.ceil(height / rowStep);
      baseRadius = step * 0.46;
      fieldA.width = columns;
      fieldA.height = rows;
      fieldB.width = columns;
      fieldB.height = rows;
    };

    const drawHand = (
      fieldContext: CanvasRenderingContext2D,
      tile: HTMLCanvasElement,
      left: boolean,
      time: number,
    ) => {
      const portrait = height > width;
      const angle = (Math.PI * 2 * time) / LOOP_SECONDS;
      const phase = left ? 0 : Math.PI;
      const handWidth = width * (portrait ? 0.66 : 0.53);
      const handHeight = handWidth * ((0.4 * 1520) / (0.47 * 2688));
      const centerY = height * 0.72;
      const reach =
        (0.035 * Math.sin(angle + phase) + 0.012 * Math.sin(2 * angle + 1.3 + phase)) * width;
      const scale = 1 + 0.07 * Math.sin(angle + 0.9 + phase);
      const rotation = (left ? 1 : -1) * 0.045 * Math.sin(angle + 2.1 + phase);
      const x = left
        ? reach - width * 0.045
        : width - handWidth + width * 0.045 - reach;
      const pivotX = left ? 0 : width;

      fieldContext.save();
      fieldContext.scale(columns / width, rows / height);
      fieldContext.translate(pivotX, centerY);
      fieldContext.rotate(rotation);
      fieldContext.scale(scale, scale);
      fieldContext.translate(-pivotX, -centerY);
      fieldContext.drawImage(tile, x, centerY - handHeight / 2, handWidth, handHeight);
      fieldContext.restore();
    };

    const render = (unwrappedTime: number) => {
      const time = ((unwrappedTime % LOOP_SECONDS) + LOOP_SECONDS) % LOOP_SECONDS;
      context.clearRect(0, 0, width, height);
      context.fillStyle = "#09090b";
      context.fillRect(0, 0, width, height);

      if (!tiles || columns <= 0 || rows <= 0) return;

      fieldAContext.setTransform(1, 0, 0, 1, 0, 0);
      fieldAContext.fillStyle = "#fff";
      fieldAContext.fillRect(0, 0, columns, rows);
      fieldBContext.setTransform(1, 0, 0, 1, 0, 0);
      fieldBContext.fillStyle = "#fff";
      fieldBContext.fillRect(0, 0, columns, rows);

      drawHand(fieldAContext, tiles.leftA, true, time);
      drawHand(fieldAContext, tiles.rightA, false, time);
      drawHand(fieldBContext, tiles.leftB, true, time);
      drawHand(fieldBContext, tiles.rightB, false, time);

      const poseA = fieldAContext.getImageData(0, 0, columns, rows).data;
      const poseB = fieldBContext.getImageData(0, 0, columns, rows).data;
      const leftMix = mixAt(time, 6.2, 14.6, 1.6);
      const rightMix = mixAt(time, 2.4, 10.4, 1.6);
      const tick = Math.floor(time * 7);
      context.fillStyle = "#f7f7f5";
      context.beginPath();

      for (let row = 0; row < rows; row += 1) {
        const rowShift = hash(row, tick) > 0.965
          ? Math.round((hash(tick, row) - 0.5) * 8)
          : 0;

        for (let column = 0; column < columns; column += 1) {
          const sampleColumn = clamp(column - rowShift, 0, columns - 1);
          const sampleIndex = (row * columns + sampleColumn) * 4;
          const seed = 0.55 * hash(column, row) + 0.45 * hash(row * 3.1, 7.7);
          const mix = column < columns / 2 ? leftMix : rightMix;
          const source = seed < mix ? poseB : poseA;
          const luminance = source[sampleIndex] / 255;
          let value = clamp((1 - luminance - 0.16) / 0.42, 0, 1);

          value *= 0.86 + 0.14 * Math.sin(time * 3.2 + seed * 40);

          const centerDistance = Math.abs((column + 0.5) / columns - 0.5);
          value *= smooth(0.035, 0.11, centerDistance);

          if (mix > 0.001 && mix < 0.999 && Math.abs(seed - mix) < 0.12) {
            value *= Math.abs(seed - mix) / 0.12;
            if (hash(column + tick, row) <= 0.4) value *= 0.3;
          }

          let level = 0;
          for (const candidate of LEVELS) {
            if (value >= candidate - 0.13) level = candidate;
          }
          if (level === 0) continue;

          const radius = baseRadius * (level === LEVELS[1] ? 0.38 : level);
          const x = (column + 0.5) * step;
          const y = (row + 0.5) * rowStep;
          context.moveTo(x + radius, y);
          context.arc(x, y, radius, 0, Math.PI * 2);
        }
      }

      context.fill();
    };

    const animate = (now: number) => {
      render((now - startedAt) / 1000);
      if (!reduceMotion.matches && !disposed) {
        animationFrame = window.requestAnimationFrame(animate);
      }
    };

    const start = () => {
      window.cancelAnimationFrame(animationFrame);
      if (reduceMotion.matches) {
        render(0);
      } else {
        animationFrame = window.requestAnimationFrame(animate);
      }
    };

    const handleResize = () => {
      window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(() => {
        resize();
        render((performance.now() - startedAt) / 1000);
      });
    };

    const image = new Image();
    image.crossOrigin = "anonymous";
    image.decoding = "async";
    image.onload = () => {
      if (disposed) return;
      tiles = {
        leftA: createTile(image, SOURCE_RECTS.leftA),
        rightA: createTile(image, SOURCE_RECTS.rightA),
        leftB: createTile(image, SOURCE_RECTS.leftB),
        rightB: createTile(image, SOURCE_RECTS.rightB),
      };
      start();
    };
    image.src = HAND_SOURCE;

    resize();
    render(0);
    window.__render = render;
    window.addEventListener("resize", handleResize, { passive: true });
    reduceMotion.addEventListener("change", start);

    return () => {
      disposed = true;
      window.cancelAnimationFrame(animationFrame);
      window.cancelAnimationFrame(resizeFrame);
      window.removeEventListener("resize", handleResize);
      reduceMotion.removeEventListener("change", start);
      if (window.__render === render) delete window.__render;
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        background: "#09090b",
      }}
    />
  );
}
