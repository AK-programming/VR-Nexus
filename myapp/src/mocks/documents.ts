/**
 * The Documents fixtures used to live here. They are gone, and this file is a marker for
 * why — it should be deleted outright, and only survives as a stub because the sandbox
 * that would run `rm` is not currently available.
 *
 * It exported `MOCK_DOCUMENTS`, `MOCK_JOBS`, `MOCK_FAILED_AT` and a `DOCUMENTS_DATA`
 * bundle, and every Documents screen read from them. All four are now unused: the
 * library listing, the processing queue and the viewer each read the real API through
 * `@/services/documentService`, which is what "make this section functional" meant.
 *
 * The fixtures were also actively harmful, in a way worth recording so they do not come
 * back. They were typed `DocumentRecord[]` — a `LibraryDocument & ClientSideFields`
 * intersection that invented `size_bytes`, `uploaded_by_name`, `summary` and `file_url`,
 * none of which the API returns. Because the fixtures satisfied that invented type
 * perfectly, every screen built against them compiled, rendered beautifully, and could
 * not be pointed at the live service without rewriting. The fake type is what let the
 * mock and the real thing drift apart unnoticed; deleting `DocumentRecord` is what
 * surfaced it, and this file was the last thing still referencing it.
 *
 * `SAMPLE_PDF_URL` also lived here, pointing at `/samples/nlc-terminal-operating-system.pdf`
 * so the viewer had something to render. Nothing needs that sample any more. The viewer
 * shows a file only when the API can actually serve this document's bytes, and no route
 * does yet — so there is no longer a copy step to perform in `public/samples/`.
 *
 * If fixtures are ever wanted again — for a test, or for offline work — type them as the
 * real `LibraryDocument` and let the compiler reject anything the API does not return.
 *
 * The empty export is what keeps this a module. Under `isolatedModules` a file with
 * nothing but comments is treated as a global script and rejected outright.
 */

export {}
