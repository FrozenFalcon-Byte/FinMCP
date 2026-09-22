/* Passkeys in the browser.

   WebAuthn speaks ArrayBuffers and the wire speaks base64url, so most of this file is that translation. The rest
   is two ceremonies: ask the API for options, hand them to the authenticator, send back what it signs.

   `supported()` is deliberately a capability check rather than a browser sniff — a desktop with no authenticator
   and no phone to hand should not be shown a button that cannot work. */
import { api } from "./api";
import type { AuthUser } from "./auth";

export interface PasskeyRow { id: number; credential_id: string; label: string | null; transports: string | null; created_at: string; last_used_at: string | null }

const b64 = {
  toBytes(v: string): Uint8Array {
    const s = v.replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(s + "=".repeat((4 - (s.length % 4)) % 4));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  },
  fromBuffer(b: ArrayBuffer): string {
    let s = "";
    for (const byte of new Uint8Array(b)) s += String.fromCharCode(byte);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  },
};

export function supported(): boolean {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;
}

/** Whether this device itself can make one (Touch ID, Windows Hello, an Android screen lock). A `false` here
    still leaves the phone-as-a-key route open, so it only softens the wording, never hides the button. */
export async function builtIn(): Promise<boolean> {
  try {
    return supported() && (await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable());
  } catch { return false; }
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function revive(options: any): any {
  const o = { ...options, challenge: b64.toBytes(options.challenge) };
  if (o.user?.id) o.user = { ...o.user, id: b64.toBytes(o.user.id) };
  for (const list of ["allowCredentials", "excludeCredentials"] as const) {
    if (Array.isArray(o[list])) o[list] = o[list].map((c: any) => ({ ...c, id: b64.toBytes(c.id) }));
  }
  return o;
}

function wire(cred: PublicKeyCredential): any {
  const r = cred.response as AuthenticatorAttestationResponse & AuthenticatorAssertionResponse;
  const out: any = {
    id: cred.id,
    rawId: b64.fromBuffer(cred.rawId),
    type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: { clientDataJSON: b64.fromBuffer(r.clientDataJSON) },
  };
  if (r.attestationObject) {
    out.response.attestationObject = b64.fromBuffer(r.attestationObject);
    out.response.transports = typeof r.getTransports === "function" ? r.getTransports() : [];
  } else {
    out.response.authenticatorData = b64.fromBuffer(r.authenticatorData);
    out.response.signature = b64.fromBuffer(r.signature);
    out.response.userHandle = r.userHandle ? b64.fromBuffer(r.userHandle) : null;
  }
  return out;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

/** A friendlier reading of what the browser threw. A cancelled prompt is not an error worth shouting about. */
export function readError(e: unknown): string | null {
  const err = e as DOMException;
  if (err?.name === "NotAllowedError" || err?.name === "AbortError") return null;   // cancelled, or timed out
  if (err?.name === "InvalidStateError") return "This device already has a passkey for your account.";
  if (err?.name === "SecurityError") return "Passkeys need the site to be on https with its own domain.";
  return e instanceof Error ? e.message : String(e);
}

/** Enrol the device you are on. Needs a signed-in session. */
export async function addPasskey(label?: string): Promise<PasskeyRow> {
  const start = await api.post<{ handle: string; options: unknown }>("/auth/passkeys/register/options", {});
  const cred = (await navigator.credentials.create({ publicKey: revive(start.options) })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was created.");
  const done = await api.post<{ passkey: PasskeyRow }>("/auth/passkeys/register/verify", { handle: start.handle, credential: wire(cred), label });
  return done.passkey;
}

export async function listPasskeys(): Promise<PasskeyRow[]> {
  return (await api.get<{ passkeys: PasskeyRow[] }>("/auth/passkeys")).passkeys;
}

export async function removePasskey(id: number): Promise<void> {
  await api.del(`/auth/passkeys/${id}`);
}

/** Sign in. No email is typed first: the browser offers whichever passkey it holds for this site, and the one it
    returns says whose account it is. */
export async function signInWithPasskey(): Promise<{ access_token: string; expires_in: number; user: AuthUser }> {
  const start = await api.post<{ handle: string; options: unknown }>("/auth/passkeys/login/options", {});
  const cred = (await navigator.credentials.get({ publicKey: revive(start.options) })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was offered.");
  return api.post("/auth/passkeys/login/verify", { handle: start.handle, credential: wire(cred) });
}
