/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute origin of the FinMCP API when the frontend is hosted apart from it (Vercel -> Hugging Face Space).
   *  Empty in dev and in the single-process build, where the API serves this app and /api is same-origin. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
