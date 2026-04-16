import { useState, type FormEvent, type KeyboardEvent } from "react";
import styles from "./ActionInput.module.css";

interface ActionInputProps {
  awaitingActorId: string;
  loading: boolean;
  onSubmit: (actorId: string, action?: string) => void;
  autopilot: boolean;
  countdown: number | null;
  onAutopilotToggle: () => void;
}

export function ActionInput({ awaitingActorId, loading, onSubmit, autopilot, countdown, onAutopilotToggle }: ActionInputProps) {
  const [text, setText] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    onSubmit(awaitingActorId, trimmed || undefined);
    setText("");
  }

  function handleAutoClick() {
    onSubmit(awaitingActorId, undefined);
    setText("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const trimmed = text.trim();
      onSubmit(awaitingActorId, trimmed || undefined);
      setText("");
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.label}>
        <span className={styles.labelLeft}>
          <span className={styles.dot} />
          Waiting for <strong>{awaitingActorId}</strong>
        </span>
        <button
          type="button"
          className={`${styles.btnAutopilot} ${autopilot ? styles.btnAutopilotOn : ""}`}
          onClick={onAutopilotToggle}
          disabled={loading && !autopilot}
          title={autopilot ? "Autopilot ON — click to disable" : "Enable autopilot"}
        >
          {autopilot
            ? countdown !== null
              ? `Auto in ${countdown}…`
              : "⏸ Autopilot"
            : "▶▶ Autopilot"}
        </button>
      </div>
      <div className={styles.row}>
        <textarea
          className={styles.input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe your action… (or click Auto)"
          rows={2}
          disabled={loading}
        />
        <div className={styles.buttons}>
          <button
            type="button"
            className={styles.btnAuto}
            onClick={handleAutoClick}
            disabled={loading}
            title="Let the AI decide the action"
          >
            Auto
          </button>
          <button
            type="submit"
            className={styles.btnSubmit}
            disabled={loading || !text.trim()}
          >
            {loading ? "…" : "▶"}
          </button>
        </div>
      </div>
    </form>
  );
}
