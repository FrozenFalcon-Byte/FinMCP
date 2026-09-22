/** Turning whatever came off a phone into something a profile row can hold. */

/** Crop to a centred square and shrink, so a 4MB photo becomes a few kilobytes. WebP where it exists, JPEG where
    it does not; either way a data URL, because the container's disk does not survive a deploy and a face that
    vanishes on restart is worse than a few kilobytes in the database. */
export function squarePhoto(file: File, size = 256): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const side = Math.min(img.width, img.height);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) return reject(new Error("This browser cannot resize the image."));
      ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size);
      const webp = canvas.toDataURL("image/webp", 0.82);
      resolve(webp.startsWith("data:image/webp") ? webp : canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file is not an image we can read.")); };
    img.src = url;
  });
}
