import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import { createPortal } from "react-dom";
import { loadImageFile, renderCrop } from "../lib/photo";
import { Icon, Spinner } from "./ui";

const MAX_ZOOM = 4;
const EASE = [0.22, 1, 0.36, 1] as const;

type Frame = { scale: number; x: number; y: number; rotation: number };
const START: Frame = { scale: 1, x: 0, y: 0, rotation: 0 };

/** Frame your own face.

    The picture sits on a square stage and everything is measured in that stage's pixels: how far it has been
    dragged from the middle, how much bigger than the stage it is drawn, which way up it is. That means the canvas
    at the end repeats exactly the arithmetic the screen just did, so what you saved is what you framed.

    The stage itself has no fixed size — it is a square of whatever width the sheet gets — so this works the same
    on a phone as on a desktop, and the one rule enforced throughout is that the picture always covers the stage:
    you can never drag a corner of nothing into your own avatar. */
export function PhotoCrop({ file, onCancel, onSave, busy }: { file: File | null; onCancel: () => void; onSave: (dataUrl: string) => void; busy?: boolean }) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [f, setF] = useState<Frame>(START);
  const [grabbing, setGrabbing] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState(0);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; scale: number } | null>(null);

  useEffect(() => {
    if (!file) { setImg(null); setError(null); setF(START); return; }
    let live = true;
    setImg(null); setError(null); setF(START);
    let url = "";
    loadImageFile(file).then((i) => { url = i.src; if (live) setImg(i); else URL.revokeObjectURL(url); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [file]);

  // The stage is square and fluid, so its side is whatever the sheet gave it this render.
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setStage(entry.contentRect.width));
    ro.observe(el);
    setStage(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, [file]);

  useEffect(() => {
    if (!file) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [file, onCancel]);

  // What the picture is drawn at: big enough to cover the stage at scale 1, turned by whole quarter turns.
  const turned = f.rotation % 180 !== 0;
  const nw = img ? (turned ? img.height : img.width) : 1;
  const nh = img ? (turned ? img.width : img.height) : 1;
  const cover = stage ? Math.max(stage / nw, stage / nh) : 0;
  const w = img ? img.width * cover * f.scale : 0;
  const h = img ? img.height * cover * f.scale : 0;
  const vw = turned ? h : w;
  const vh = turned ? w : h;

  const clamp = useCallback((next: Frame): Frame => {
    if (!img || !stage) return next;
    const t = next.rotation % 180 !== 0;
    const c = Math.max(stage / (t ? img.height : img.width), stage / (t ? img.width : img.height));
    const W = img.width * c * next.scale, H = img.height * c * next.scale;
    const mx = Math.max(0, ((t ? H : W) - stage) / 2), my = Math.max(0, ((t ? W : H) - stage) / 2);
    return { ...next, x: Math.min(mx, Math.max(-mx, next.x)), y: Math.min(my, Math.max(-my, next.y)) };
  }, [img, stage]);

  const zoomTo = useCallback((scale: number) => setF((p) => clamp({ ...p, scale: Math.min(MAX_ZOOM, Math.max(1, scale)) })), [clamp]);

  const down = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!img) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { dist: Math.hypot(a.x - b.x, a.y - b.y), scale: f.scale };
    }
    setGrabbing(true);
  };
  const move = (e: ReactPointerEvent<HTMLDivElement>) => {
    const prev = pointers.current.get(e.pointerId);
    if (!prev || !img) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size >= 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch.current.dist > 0) zoomTo((pinch.current.scale * dist) / pinch.current.dist);
      return;
    }
    setF((p) => clamp({ ...p, x: p.x + (e.clientX - prev.x), y: p.y + (e.clientY - prev.y) }));
  };
  const up = (e: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    if (!pointers.current.size) setGrabbing(false);
  };
  const wheel = (e: ReactWheelEvent<HTMLDivElement>) => { if (img) zoomTo(f.scale * (e.deltaY < 0 ? 1.08 : 1 / 1.08)); };
  const turn = () => setF((p) => clamp({ ...p, rotation: (p.rotation + 90) % 360 }));

  const save = () => {
    if (!img || !stage) return;
    onSave(renderCrop(img, { stage, x: f.x, y: f.y, width: w, height: h, rotation: f.rotation }));
  };

  const style = { width: w || 1, height: h || 1, transform: `translate(-50%, -50%) translate(${f.x}px, ${f.y}px) rotate(${f.rotation}deg)` };

  return createPortal(
    <AnimatePresence>
      {file ? (
        <motion.div key="crop" className="sheet-backdrop crop-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
          <motion.div className="sheet crop-sheet" role="dialog" aria-modal="true" aria-label="Frame your photo"
            initial={{ opacity: 0, y: 28, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 34, mass: 0.8 }}>
            <button type="button" className="sheet-x" onClick={onCancel} aria-label="Close"><Icon name="x" /></button>
            <h2>Frame your photo</h2>
            <div className="sub">Drag it about, pinch or scroll to zoom. What is inside the circle is what people see.</div>

            <div className={`crop-stage ${grabbing ? "grabbing" : ""}`} ref={stageRef}
              onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onWheel={wheel}
              onDoubleClick={() => setF(START)}>
              {img ? (
                <motion.img src={img.src} alt="" className="crop-img" draggable={false} style={style}
                  initial={{ opacity: 0, filter: "blur(8px)" }} animate={{ opacity: 1, filter: "blur(0px)" }} transition={{ duration: 0.4, ease: EASE }} />
              ) : error ? <div className="crop-msg">{error}</div> : <div className="crop-msg"><Spinner /></div>}
              <span className="crop-mask" aria-hidden="true" />
              <motion.span className="crop-ring" aria-hidden="true" animate={{ scale: grabbing ? 1.02 : 1, opacity: grabbing ? 1 : 0.85 }} transition={{ type: "spring", stiffness: 400, damping: 26 }} />
              {/* The corner marks make the circle read as a viewfinder rather than a decoration. */}
              <span className="crop-corners" aria-hidden="true"><i /><i /><i /><i /></span>
            </div>

            <div className="crop-tools">
              <button type="button" className="btn icon sm" onClick={() => zoomTo(f.scale / 1.25)} disabled={!img || f.scale <= 1} aria-label="Zoom out"><Icon name="zoomOut" /></button>
              <input className="crop-range" type="range" min={1} max={MAX_ZOOM} step={0.01} value={f.scale} disabled={!img}
                onChange={(e) => zoomTo(Number(e.target.value))} aria-label="Zoom" />
              <button type="button" className="btn icon sm" onClick={() => zoomTo(f.scale * 1.25)} disabled={!img || f.scale >= MAX_ZOOM} aria-label="Zoom in"><Icon name="zoomIn" /></button>
              <button type="button" className="btn icon sm" onClick={turn} disabled={!img} aria-label="Turn a quarter turn"><Icon name="rotate" /></button>
            </div>

            <div className="crop-foot">
              <Preview img={img} f={f} stage={stage} w={w} h={h} vw={vw} vh={vh} />
              <div className="crop-acts">
                <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
                <button type="button" className="btn primary" onClick={save} disabled={!img || busy}>{busy ? <Spinner /> : <><Icon name="check" />Use this</>}</button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

/** Two live copies of the crop, at the sizes it is actually worn: beside your name, and in the sidebar. They are
    the same picture under the same transform, scaled down — so there is no guessing how it will land. */
function Preview({ img, f, stage, w, h, vw, vh }: { img: HTMLImageElement | null; f: Frame; stage: number; w: number; h: number; vw: number; vh: number }) {
  if (!img || !stage) return <div className="crop-previews" />;
  const shot = (side: number) => {
    const k = side / stage;
    return (
      <span className="crop-shot" style={{ width: side, height: side }} key={side}>
        <img src={img.src} alt="" draggable={false}
          style={{ width: w * k, height: h * k, transform: `translate(-50%, -50%) translate(${f.x * k}px, ${f.y * k}px) rotate(${f.rotation}deg)` }} />
      </span>
    );
  };
  return <div className="crop-previews" aria-hidden="true" title={`${Math.round(vw)}×${Math.round(vh)}`}>{shot(48)}{shot(30)}</div>;
}
