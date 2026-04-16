/** Types mirroring the backend response models. */

export interface ResolvedActionResponse {
  actor_id: string;
  action: string;
  source: "player" | "intent_agent";
  in_character_note?: string | null;
  reasoning?: string | null;
}

export interface NpcTurnResponse {
  actor_id: string;
  generated_action: string;
  status: string;
  ruling: string;
  advanced_turn: boolean;
  applied_mutation_count: number;
}

export interface ActionResponse {
  status: string;
  ruling: string;
  actor: ResolvedActionResponse;
  actor_id: string;
  awaiting_actor_id: string;
  advanced_turn: boolean;
  applied_mutation_count: number;
  npc_turns: NpcTurnResponse[];
}

export interface OutcomeResponse {
  success: boolean;
  data?: ActionResponse | null;
  error?: string | null;
  actor_id?: string | null;
}

export interface KickoffSummary {
  status: string;
  ruling: string;
  actor_id: string;
  awaiting_actor_id: string;
  advanced_turn: boolean;
  applied_mutation_count: number;
}

export interface InitResponse {
  success: boolean;
  session_id?: string;
  deleted_snapshots?: number;
  kickoff?: KickoffSummary;
  error?: string;
}

export interface RewindResponse {
  success: boolean;
  session_id?: string;
  deleted_snapshot?: string;
  restored_from_snapshot?: string | null;
  active_actor_id?: string;
  awaiting_input_from?: string;
  world_version?: number;
  turn_count?: number;
  error?: string;
}

export interface SnapshotDiff {
  path: string;
  kind: "added" | "removed" | "changed";
  old_value: unknown;
  new_value: unknown;
}

export interface DiffLatestResponse {
  success: boolean;
  session_id?: string;
  old_snapshot?: string;
  new_snapshot?: string;
  diff_count?: number;
  diffs?: SnapshotDiff[];
  error?: string;
}

// ── Frontend-only view models ────────────────────────────────────────────────

export type TranscriptEntryKind = "kickoff" | "player" | "npc" | "system";

export interface TranscriptEntry {
  id: string;
  kind: TranscriptEntryKind;
  actorId: string;
  action?: string;
  ruling: string;
  status: string;
  source?: "player" | "intent_agent";
  reasoning?: string | null;
}
