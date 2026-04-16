import { useState, useCallback, useRef, useEffect } from "react";
import { Toolbar } from "./components/Toolbar/Toolbar";
import { TranscriptPanel } from "./components/TranscriptPanel/TranscriptPanel";
import { ActionInput } from "./components/ActionInput/ActionInput";
import { TurnChangeBasket } from "./components/TurnChangeBasket/TurnChangeBasket";
import { Toast } from "./components/Toast/Toast";
import { initGame, advanceGame, rewindGame, diffLatestSnapshots } from "./api/client";
import type { TranscriptEntry, SnapshotDiff } from "./types/game";
import styles from "./App.module.css";

let _entryCounter = 0;
function nextId() {
  return String(++_entryCounter);
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [awaitingActorId, setAwaitingActorId] = useState<string | undefined>(undefined);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [diffs, setDiffs] = useState<SnapshotDiff[]>([]);
  const [diffMeta, setDiffMeta] = useState<{ old?: string; new?: string }>({});
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [autopilot, setAutopilot] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);

  // Mutable refs — safe to read inside interval callbacks without stale-closure issues.
  const autopilotRef = useRef(false);
  const countdownIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const consecutiveRejectionsRef = useRef(0);
  const awaitingActorIdRef = useRef<string | undefined>(undefined);
  const handleActionRef = useRef<(actorId: string, action?: string) => Promise<void>>(
    async () => {}
  );

  // Keep awaitingActorIdRef current on every render.
  awaitingActorIdRef.current = awaitingActorId;

  // Clean up any running countdown on unmount.
  useEffect(() => {
    return () => {
      if (countdownIntervalRef.current !== null) {
        clearInterval(countdownIntervalRef.current);
      }
    };
  }, []);

  function clearCountdown() {
    if (countdownIntervalRef.current !== null) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    setCountdown(null);
  }

  function startCountdown() {
    clearCountdown();
    let remaining = 5;
    setCountdown(remaining);
    countdownIntervalRef.current = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(countdownIntervalRef.current!);
        countdownIntervalRef.current = null;
        setCountdown(null);
        const actorId = awaitingActorIdRef.current;
        if (actorId && autopilotRef.current) {
          handleActionRef.current(actorId, undefined);
        }
      } else {
        setCountdown(remaining);
      }
    }, 1000);
  }

  function handleAutopilotToggle() {
    const newVal = !autopilotRef.current;
    autopilotRef.current = newVal;
    setAutopilot(newVal);
    if (!newVal) {
      clearCountdown();
    }
  }

  function showError(msg: string) {
    setErrorMsg(msg);
  }

  function appendEntry(entry: TranscriptEntry) {
    setTranscript((prev) => [...prev, entry]);
  }

  const fetchDiff = useCallback(async (sid?: string) => {
    try {
      const result = await diffLatestSnapshots(sid);
      if (result.success && result.diffs) {
        setDiffs(result.diffs);
        setDiffMeta({ old: result.old_snapshot, new: result.new_snapshot });
      }
    } catch {
      // Diff failure is non-critical; swallow silently.
    }
  }, []);

  async function handleInit() {
    setLoading(true);
    try {
      const result = await initGame();
      if (!result.success || !result.kickoff) {
        showError(result.error ?? "Init failed.");
        return;
      }

      setTranscript([]);
      setDiffs([]);
      setDiffMeta({});
      setSessionId(result.session_id);

      const kickoff = result.kickoff;
      appendEntry({
        id: nextId(),
        kind: "kickoff",
        actorId: kickoff.actor_id || "DM",
        ruling: kickoff.ruling,
        status: kickoff.status,
      });

      setAwaitingActorId(kickoff.awaiting_actor_id);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Init failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRewind() {
    setLoading(true);
    try {
      const result = await rewindGame();
      if (!result.success) {
        showError(result.error ?? "Rewind failed.");
        return;
      }

      setTranscript((prev) => prev.slice(0, -1));
      setAwaitingActorId(result.awaiting_input_from);
      setDiffs([]);
      setDiffMeta({});

      appendEntry({
        id: nextId(),
        kind: "system",
        actorId: "system",
        ruling: `↩ Rewound to snapshot "${result.restored_from_snapshot ?? "previous"}".`,
        status: "rewind",
      });
    } catch (err) {
      showError(err instanceof Error ? err.message : "Rewind failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleAction(actorId: string, action?: string) {
    clearCountdown();
    setLoading(true);
    try {
      const outcome = await advanceGame(actorId, action);

      if (!outcome.success || !outcome.data) {
        showError(outcome.error ?? "Action failed.");
        if (autopilotRef.current) {
          autopilotRef.current = false;
          setAutopilot(false);
        }
        return;
      }

      const data = outcome.data;

      // Track consecutive rejections for autopilot retry-once logic.
      if (data.status === "rejected") {
        consecutiveRejectionsRef.current += 1;
      } else {
        consecutiveRejectionsRef.current = 0;
      }

      appendEntry({
        id: nextId(),
        kind: "player",
        actorId: data.actor.actor_id,
        action: data.actor.action,
        ruling: data.ruling,
        status: data.status,
        source: data.actor.source,
        reasoning: data.actor.reasoning,
      });

      for (const npc of data.npc_turns) {
        appendEntry({
          id: nextId(),
          kind: "npc",
          actorId: npc.actor_id,
          action: npc.generated_action,
          ruling: npc.ruling,
          status: npc.status,
          source: "intent_agent",
        });
      }

      setAwaitingActorId(data.awaiting_actor_id);
      await fetchDiff(sessionId);

      if (autopilotRef.current) {
        if (data.status === "rejected" && consecutiveRejectionsRef.current >= 2) {
          autopilotRef.current = false;
          setAutopilot(false);
          showError("Autopilot paused: action rejected twice in a row.");
        } else {
          startCountdown();
        }
      }
    } catch (err) {
      showError(err instanceof Error ? err.message : "Action failed.");
      if (autopilotRef.current) {
        autopilotRef.current = false;
        setAutopilot(false);
      }
    } finally {
      setLoading(false);
    }
  }

  // Always point to the latest handleAction so the countdown interval avoids stale closures.
  handleActionRef.current = handleAction;

  return (
    <div className={styles.app}>
      <Toolbar
        sessionId={sessionId}
        loading={loading}
        onInit={handleInit}
        onRewind={handleRewind}
      />

      <div className={styles.body}>
        <div className={styles.leftPanel}>
          <TranscriptPanel entries={transcript} />
          {awaitingActorId && (
            <ActionInput
              awaitingActorId={awaitingActorId}
              loading={loading}
              onSubmit={handleAction}
              autopilot={autopilot}
              countdown={countdown}
              onAutopilotToggle={handleAutopilotToggle}
            />
          )}
        </div>

        <TurnChangeBasket
          diffs={diffs}
          oldSnapshot={diffMeta.old}
          newSnapshot={diffMeta.new}
        />
      </div>

      <Toast
        message={errorMsg}
        onDismiss={() => setErrorMsg(null)}
      />
    </div>
  );
}
