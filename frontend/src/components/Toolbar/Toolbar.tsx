import styles from "./Toolbar.module.css";

interface ToolbarProps {
  sessionId?: string;
  loading: boolean;
  onInit: () => void;
  onRewind: () => void;
}

export function Toolbar({ sessionId, loading, onInit, onRewind }: ToolbarProps) {
  return (
    <header className={styles.toolbar}>
      <div className={styles.brand}>
        <span className={styles.brandIcon}>⚔️</span>
        <span className={styles.brandName}>AgenticDnD</span>
      </div>

      {sessionId && (
        <span className={styles.sessionId} title="Active session ID">
          session: <code>{sessionId}</code>
        </span>
      )}

      <div className={styles.actions}>
        <button
          className={styles.btnSecondary}
          onClick={onRewind}
          disabled={loading || !sessionId}
          title="Undo the last turn"
        >
          ↩ Rewind
        </button>
        <button
          className={styles.btnPrimary}
          onClick={onInit}
          disabled={loading}
          title="Reset and start a new adventure"
        >
          {loading ? "Loading…" : "Init"}
        </button>
      </div>
    </header>
  );
}
