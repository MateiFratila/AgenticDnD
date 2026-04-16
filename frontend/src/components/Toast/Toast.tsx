import { useEffect, useState } from "react";
import styles from "./Toast.module.css";

interface ToastProps {
  message: string | null;
  onDismiss: () => void;
  duration?: number;
}

export function Toast({ message, onDismiss, duration = 4000 }: ToastProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!message) {
      setVisible(false);
      return;
    }

    setVisible(true);
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onDismiss, 300); // wait for fade-out before clearing
    }, duration);

    return () => clearTimeout(timer);
  }, [message, duration, onDismiss]);

  if (!message) return null;

  return (
    <div
      className={`${styles.toast} ${visible ? styles.visible : styles.hidden}`}
      role="alert"
      onClick={() => {
        setVisible(false);
        setTimeout(onDismiss, 300);
      }}
    >
      <span className={styles.icon}>⚠</span>
      <span className={styles.text}>{message}</span>
    </div>
  );
}
