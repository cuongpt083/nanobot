/**
 * The family of versions of one image in its folder (IM-15): the original, and each saved ``<stem>.vN.<ext>``
 * with the parent it was made from, read from its ``<stem>.vN.annotations.json``.
 */
import { listWorkspaceDir, readWorkspaceFile } from "@/lib/api";

export interface VersionNode {
  path: string;
  label: string;
  /** The image this one was made from; ``null`` for the original. */
  parent: string | null;
}

export interface VersionRow extends VersionNode {
  depth: number;
}

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp"];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** ``assets/banner.v3.png`` → folder ``assets``, stem ``banner`` (the version number is not part of the family). */
export function familyOf(path: string): { folder: string; family: string } {
  const slash = path.lastIndexOf("/");
  const folder = slash >= 0 ? path.slice(0, slash) : "";
  const name = slash >= 0 ? path.slice(slash + 1) : path;
  const stem = name.replace(/\.[^.]+$/, "");
  return { folder, family: stem.replace(/\.v\d+$/, "") };
}

/** Rows in tree order: the original first, then each version under the image it was made from. */
export function orderVersionTree(nodes: VersionNode[]): VersionRow[] {
  const byPath = new Map(nodes.map((node) => [node.path, node] as const));
  const children = new Map<string, VersionNode[]>();
  const roots: VersionNode[] = [];
  for (const node of nodes) {
    if (node.parent && node.parent !== node.path && byPath.has(node.parent)) {
      children.set(node.parent, [...(children.get(node.parent) ?? []), node]);
    } else {
      roots.push(node);
    }
  }
  const byLabel = (a: VersionNode, b: VersionNode) => a.label.localeCompare(b.label, undefined, { numeric: true });
  const rows: VersionRow[] = [];
  const visited = new Set<string>();
  const visit = (node: VersionNode, depth: number) => {
    if (visited.has(node.path)) return;
    visited.add(node.path);
    rows.push({ ...node, depth });
    for (const child of [...(children.get(node.path) ?? [])].sort(byLabel)) visit(child, depth + 1);
  };
  for (const root of [...roots].sort(byLabel)) visit(root, 0);
  // Nodes only reachable through a cycle have no root; they are shown at the top rather than dropped.
  for (const node of [...nodes].sort(byLabel)) visit(node, 0);
  return rows;
}

/** The versions of the image at ``path``, in tree order. A folder that cannot be listed gives no tree. */
export async function loadVersionTree(
  token: string,
  key: string,
  path: string,
  base: string = "",
): Promise<VersionRow[]> {
  const { folder, family } = familyOf(path);
  let entries: { name: string; kind: string }[];
  try {
    entries = (await listWorkspaceDir(token, key, folder, base)).entries;
  } catch {
    return [];
  }
  const pattern = new RegExp(`^${escapeRegExp(family)}(?:\\.v(\\d+))?\\.(${IMAGE_EXTENSIONS.join("|")})$`, "i");
  const prefix = folder ? `${folder}/` : "";
  const names = new Set(entries.map((entry) => entry.name));
  const found = entries
    .filter((entry) => entry.kind === "file" && pattern.test(entry.name))
    .map((entry) => ({ name: entry.name, match: pattern.exec(entry.name) }));
  const rootPath = found.find((item) => !item.match?.[1])?.name;
  const nodes: VersionNode[] = [];
  for (const item of found) {
    const number = item.match?.[1];
    const nodePath = `${prefix}${item.name}`;
    if (!number) {
      nodes.push({ path: nodePath, label: "original", parent: null });
      continue;
    }
    let parent: string | null = rootPath ? `${prefix}${rootPath}` : null;
    const annotationName = `${family}.v${number}.annotations.json`;
    if (names.has(annotationName)) try {
      const annotation = await readWorkspaceFile(token, key, `${prefix}${annotationName}`, base);
      const loaded: unknown = JSON.parse(annotation.content);
      const image = loaded && typeof loaded === "object" ? (loaded as { image?: unknown }).image : undefined;
      if (typeof image === "string" && image.trim()) parent = image.trim();
    } catch {
      // No recorded parent: the version hangs under the original.
    }
    nodes.push({ path: nodePath, label: `v${number}`, parent });
  }
  return orderVersionTree(nodes);
}
