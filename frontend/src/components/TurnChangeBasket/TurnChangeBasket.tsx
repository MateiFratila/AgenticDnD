import type { SnapshotDiff } from "../../types/game";
import styles from "./TurnChangeBasket.module.css";

interface TurnChangeBasketProps {
  diffs: SnapshotDiff[];
  oldSnapshot?: string;
  newSnapshot?: string;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function shortenPath(path: string | undefined): string {
  if (!path) return "(unknown)";
  const clean = path.startsWith(".") ? path.slice(1) : path;
  const parts = clean.split(/[.[\]]+/).filter(Boolean);
  return parts.length > 4 ? `…${parts.slice(-4).join(".")}` : parts.join(".");
}

export function TurnChangeBasket({ diffs, oldSnapshot, newSnapshot }: TurnChangeBasketProps) {
  const snapshotLabel = newSnapshot
    ? newSnapshot.replace(/\.json$/, "").split("_").slice(-1)[0]
    : undefined;

  return (
    <aside className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.title}>Turn Change Basket</span>
        {snapshotLabel && (
          <span className={styles.snapshotTag} title={`${oldSnapshot} → ${newSnapshot}`}>
            {snapshotLabel}
          </span>
        )}
        {diffs.length > 0 && (
          <span className={styles.count}>{diffs.length}</span>
        )}
      </div>

      {diffs.length === 0 ? (
        <div className={styles.empty}>
          <span>No changes yet.</span>
          <span className={styles.emptySub}>Changes will appear here after each turn.</span>
        </div>
      ) : (
        <ul className={styles.list}>
          {diffs.map((diff, i) => (
            <li key={i} className={`${styles.change} ${styles[`kind_${diff.kind}`]}`}>
              <span className={styles.path} title={diff.path}>
                {shortenPath(diff.path)}
              </span>
              <div className={styles.values}>
                {diff.kind !== "added" && diff.old_value !== undefined && (
                  <span className={styles.oldValue}>
                    {formatValue(diff.old_value)}
                  </span>
                )}
                {diff.kind === "changed" && <span className={styles.arrow}>→</span>}
                {diff.kind !== "removed" && (
                  <span className={styles.newValue}>
                    {formatValue(diff.new_value)}
                  </span>
                )}
                {diff.kind === "added" && <span className={styles.kindTag}>added</span>}
                {diff.kind === "removed" && <span className={`${styles.kindTag} ${styles.kindRemoved}`}>removed</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
