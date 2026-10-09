/**
 * Splits a proposed change into hunks (runs of changed lines) and assembles the text from the hunks the user keeps.
 *
 * Lines are compared with a longest-common-subsequence table, which needs memory proportional to the product of
 * the two line counts. Past ``MAX_HUNK_CELLS`` the file is not split: the user can still accept or reject it whole.
 */

export interface Hunk {
  id: number;
  /** Index of the first original line this hunk replaces. */
  start: number;
  /** Original lines removed by the hunk (may be empty for a pure insertion). */
  oldLines: string[];
  /** Proposed lines the hunk adds (may be empty for a pure deletion). */
  newLines: string[];
}

export const MAX_HUNK_CELLS = 4_000_000;

export function splitLines(text: string): string[] {
  return text.split("\n");
}

/** The hunks that turn ``original`` into ``proposed``. Empty when the texts are equal or too large to split. */
export function diffHunks(original: string, proposed: string): Hunk[] {
  const a = splitLines(original);
  const b = splitLines(proposed);
  const cols = b.length + 1;
  if ((a.length + 1) * cols > MAX_HUNK_CELLS) return [];

  // lcs[i * cols + j] = length of the common subsequence of a[i:] and b[j:].
  const lcs = new Uint32Array((a.length + 1) * cols);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i * cols + j] = a[i] === b[j]
        ? lcs[(i + 1) * cols + j + 1] + 1
        : Math.max(lcs[(i + 1) * cols + j], lcs[i * cols + j + 1]);
    }
  }

  const hunks: Hunk[] = [];
  let current: Hunk | null = null;
  const close = () => {
    if (current) hunks.push(current);
    current = null;
  };
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      close();
      i += 1;
      j += 1;
      continue;
    }
    if (!current) current = { id: hunks.length, start: i, oldLines: [], newLines: [] };
    if (j < b.length && (i >= a.length || lcs[i * cols + j + 1] >= lcs[(i + 1) * cols + j])) {
      current.newLines.push(b[j]);
      j += 1;
    } else {
      current.oldLines.push(a[i]);
      i += 1;
    }
  }
  close();
  return hunks.map((hunk, id) => ({ ...hunk, id }));
}

/** The text with the kept hunks applied and the others left as they were in ``original``. */
export function assemble(original: string, hunks: Hunk[], kept: ReadonlySet<number>): string {
  const lines = splitLines(original);
  const out: string[] = [];
  let cursor = 0;
  for (const hunk of hunks) {
    out.push(...lines.slice(cursor, hunk.start));
    out.push(...(kept.has(hunk.id) ? hunk.newLines : hunk.oldLines));
    cursor = hunk.start + hunk.oldLines.length;
  }
  out.push(...lines.slice(cursor));
  return out.join("\n");
}
