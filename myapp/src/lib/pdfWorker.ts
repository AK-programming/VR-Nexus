/**
 * react-pdf's one-time setup, in one place.
 *
 * pdf.js does its parsing in a Web Worker and will not start until it is told where
 * that worker file is. `new URL(..., import.meta.url)` is the form Vite understands: it
 * resolves the path at build time and emits the worker as its own asset, so this works
 * the same in `vite dev` and in a production build. A bare string path would 404 once
 * the app is served from anywhere other than the root.
 *
 * The version pairing matters, and it is the reason `pdfjs-dist` is pinned to an exact
 * version in package.json rather than carrying a caret. react-pdf depends on one exact
 * pdfjs-dist release — 5.4.296 for react-pdf 10.5 — and imports the pdf.js *API* from it.
 * The line below resolves the *worker* by bare specifier from this file, which lands on
 * whatever `node_modules/pdfjs-dist` npm hoisted. A caret range lets those two be
 * different releases: npm installs the newer one at the top level, nests react-pdf's
 * exact pin underneath it, and pdf.js then refuses to start with "The API version does
 * not match the Worker version". Matching the pin exactly collapses both to one hoisted
 * copy, so the API and the worker are the same build by construction.
 *
 * That pin has to move when react-pdf moves. `npm ls pdfjs-dist` printing two versions
 * is the symptom; the fix is to read react-pdf's `dependencies.pdfjs-dist` and copy it
 * here verbatim. Also note react-pdf 10 is built on pdf.js 5, where the worker is an ES
 * module (`pdf.worker.min.mjs`) — pdf.js 4 and earlier shipped `pdf.worker.min.js` and
 * the two are not interchangeable.
 *
 * The two stylesheets are what make text selectable and links clickable — without them
 * the text layer renders as invisibly positioned spans stacked in the top-left corner,
 * which looks like a rendering bug rather than a missing import. Their paths moved in
 * react-pdf 9: v7 and v8 served them from `react-pdf/dist/esm/Page/…`. If a build fails
 * with "Failed to resolve import", check the installed version and adjust here; the
 * loud failure is the reason this lives in its own module.
 *
 * Imported once, from the viewer page. Side-effect modules are usually worth avoiding,
 * but this genuinely is global state on the pdf.js singleton, and doing it inside a
 * component would reassign it on every mount.
 */

import { pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

/**
 * Passed to every `<Document>`, from module scope rather than inline.
 *
 * react-pdf compares `options` by identity and reloads the whole file when it changes,
 * so an object literal in the JSX would re-fetch and re-parse the PDF on every render.
 * A module constant is the fix, and it is the reason this is exported rather than
 * written at the call site.
 *
 * `isEvalSupported: false` turns off pdf.js's eval-based font shortcut. It costs a
 * little speed on font-heavy documents and means the viewer keeps working under a
 * Content-Security-Policy without `unsafe-eval`, which is the policy any deployment of
 * this app should be running.
 *
 * Deliberately no `cMapUrl` or `standardFontDataUrl`: both point at directories that
 * have to be copied out of `pdfjs-dist` into `public/`, and pointing at paths that do
 * not exist yet fails at fetch time for documents that need them while doing nothing
 * for documents that do not. They belong here the day a document actually needs a CJK
 * encoding or an unembedded base-14 font, alongside the copy step that makes them real.
 */
export const PDF_OPTIONS = {
  isEvalSupported: false,
} as const
