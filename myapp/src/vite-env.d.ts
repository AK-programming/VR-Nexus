/// <reference types="vite/client" />

/**
 * Declares the environment variables this app reads, so `VITE_API_BASE_URL` is
 * typed as `string | undefined` rather than `any`.
 *
 * This interface merges with the one from vite/client, which carries an
 * `[key: string]: any` index signature — so a misspelled variable still
 * compiles. The value here is the documentation and the correct type on the keys
 * we do declare, not exhaustive checking.
 *
 * Vite only exposes variables prefixed with VITE_ to client code.
 */
interface ImportMetaEnv {
  /** Empty in development — requests go through the Vite proxy. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
