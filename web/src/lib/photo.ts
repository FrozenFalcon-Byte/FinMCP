/** Turning whatever came off a phone into something a profile row can hold. */

export const PHOTO_SIZE = 256;

/** Decode a picked file into an image we can measure, show and draw. The object URL stays alive while the
    image is on screen — the caller releases it with `URL.revokeObjectURL(img.src)` when the cropper closes, so a
    cancelled crop does not hold the whole file for the life of the tab. */
export function loadImageFile(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file is not an image we can read.")); };
    img.src = url;
  });
}

/** The crop, as the person framed it. `frame` is the stage they dragged the picture around in — its side in CSS
    pixels, the offset from its centre, the on-screen size of the picture and how far it has been turned — so this
    is the same arithmetic the screen just did, at whatever output size we want.

    WebP where it exists, JPEG where it does not; either way a data URL, because the container's disk does not
    survive a deploy and a face that vanishes on restart is worse than a few kilobytes in the database. */
export function renderCrop(img: HTMLImageElement, frame: { stage: number; x: number; y: number; width: number; height: number; rotation: number }, size = PHOTO_SIZE): string {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot resize the image.");
  const px = size / frame.stage;  // stage pixels to output pixels
  ctx.imageSmoothingQuality = "high";
  ctx.translate(size / 2, size / 2);
  ctx.translate(frame.x * px, frame.y * px);
  ctx.rotate((frame.rotation * Math.PI) / 180);
  ctx.drawImage(img, (-frame.width * px) / 2, (-frame.height * px) / 2, frame.width * px, frame.height * px);
  const webp = canvas.toDataURL("image/webp", 0.82);
  return webp.startsWith("data:image/webp") ? webp : canvas.toDataURL("image/jpeg", 0.85);
}
