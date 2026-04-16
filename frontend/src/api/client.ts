import type {
  InitResponse,
  OutcomeResponse,
  RewindResponse,
  DiffLatestResponse,
} from "../types/game";

const BASE_URL = "http://localhost:8000";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

/** Reset state, reload world, and run adventure kickoff. */
export async function initGame(): Promise<InitResponse> {
  return request<InitResponse>("/init", { method: "POST" });
}

/**
 * Process a player action and advance the game state.
 * Pass `action: undefined` to have the intent agent generate one.
 */
export async function advanceGame(
  actorId: string,
  action?: string
): Promise<OutcomeResponse> {
  return request<OutcomeResponse>("/api/advance", {
    method: "POST",
    body: JSON.stringify({
      actor: {
        actor_id: actorId,
        action: action ?? null,
      },
    }),
  });
}

/** Delete the newest snapshot and restore the previous one. */
export async function rewindGame(): Promise<RewindResponse> {
  return request<RewindResponse>("/api/rewind");
}

/** Diff the two most recent snapshots for the active session. */
export async function diffLatestSnapshots(
  sessionId?: string
): Promise<DiffLatestResponse> {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return request<DiffLatestResponse>(`/api/snapshots/diff-latest${qs}`);
}
