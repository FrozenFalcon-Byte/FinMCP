/* Session storage in first-party cookies (SameSite=Lax, Secure on https). Values larger than one cookie comfortably
   holds (a Supabase session with its user object) are split across `name.0`, `name.1`, ... and joined on read.
   Also serves as the supabase-js `storage` adapter. */
const CHUNK = 3000;
const DEFAULT_AGE = 60 * 60 * 24 * 30;

function jar(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of document.cookie ? document.cookie.split("; ") : []) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i)] = part.slice(i + 1);
  }
  return out;
}

function write(key: string, value: string, maxAge: number): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${key}=${value}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secure}`;
}

export function getCookie(name: string): string | null {
  const all = jar();
  let enc = all[name];
  if (enc === undefined) {
    enc = "";
    for (let i = 0; all[`${name}.${i}`] !== undefined; i++) enc += all[`${name}.${i}`];
    if (!enc) return null;
  }
  try { return decodeURIComponent(enc); } catch { return null; }
}

export function removeCookie(name: string): void {
  for (const key of Object.keys(jar())) if (key === name || key.startsWith(`${name}.`)) write(key, "", 0);
}

export function setCookie(name: string, value: string, maxAge = DEFAULT_AGE): void {
  removeCookie(name);
  const enc = encodeURIComponent(value);
  if (enc.length <= CHUNK) { write(name, enc, maxAge); return; }
  for (let i = 0, n = 0; i < enc.length; i += CHUNK, n++) write(`${name}.${n}`, enc.slice(i, i + CHUNK), maxAge);
}

export const cookieStorage = {
  getItem: (key: string) => getCookie(key),
  setItem: (key: string, value: string) => setCookie(key, value),
  removeItem: (key: string) => removeCookie(key),
};
