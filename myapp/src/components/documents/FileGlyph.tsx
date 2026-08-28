/**
 * The little framed icon that stands in front of a filename.
 *
 * Three glyphs, not seven: the backend collapses png, jpg and tiff into one `image`
 * type, and a page and a deck are the only other shapes that read differently at
 * 16px. Distinguishing docx from pdf with two nearly identical page outlines would be
 * decoration — the extension is in the filename right beside it.
 *
 * The frame is neutral in every case. A red plate for PDFs and a blue one for Word is
 * the convention in a file manager and the wrong move here: red is this product's own
 * colour, and twenty rows of coloured plates turn a table into confetti with nothing
 * left to draw the eye to the one row that needs attention.
 */

import type { ComponentType } from 'react'
import { fileTypeFromName, FILE_TYPE_GLYPHS } from '@/models/documents'
import type { FileGlyphName } from '@/models/documents'
import { FileTextIcon, ImageIcon, PresentationIcon } from '@/components/ui/icons'

const GLYPHS: Record<FileGlyphName, ComponentType<{ className?: string }>> = {
  document: FileTextIcon,
  slides: PresentationIcon,
  image: ImageIcon,
}

export function FileGlyph({ filename }: { filename: string }) {
  const fileType = fileTypeFromName(filename)
  /* An unrecognised extension still gets a page rather than an empty square. The
     document exists either way, and a hole in the column reads as a rendering bug. */
  const Glyph = GLYPHS[fileType ? FILE_TYPE_GLYPHS[fileType] : 'document']

  return (
    <span
      aria-hidden="true"
      className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-hairline bg-surface-muted text-neutral-500"
    >
      <Glyph className="size-4.5" />
    </span>
  )
}
