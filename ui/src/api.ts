// Types mirror the backend's pydantic models (backend/src/regateo). Keep them in sync by hand.
import { useEffect, useState } from "react";

export type Role = "seller" | "buyer";
export type ActionKind = "offer" | "accept" | "reject" | "message" | "walk_away";

export interface Estimate { mean: number | null; lo: number | null; hi: number | null; n: number }
export interface Paired {
  n: number; mean_diff: number | null; lo: number | null; hi: number | null; p_value: number | null;
  a_better: number | null; ties: number | null; b_better: number | null;
}

export interface Progress {
  status: string | null; total: number | null; by_status: Record<string, number>; done: number;
  cost_usd: number; deals: number; last_update: number | null;
  input_tokens: number; output_tokens: number; llm_calls: number;
}

export interface Run {
  id: string; kind: "gym" | "arena" | "match"; name: string; config: Record<string, unknown>;
  status: string; created_at: number; ended_at: number | null; progress: Progress;
}

export interface Overview {
  runs: Record<string, number>; running_runs: number; matches: number; deals: number; cost_usd: number;
  llm_calls: number; input_tokens: number; output_tokens: number;
}

export interface MatchSummary {
  id: string; status: string; scenario_id: string; item: string; seller: string; buyer: string;
  protocol: string; meta: Record<string, string | number>; deal: boolean | null; price: number | null;
  end_reason: string | null; messages: number | null; seller_share: number | null; buyer_share: number | null;
  past_reservation: Role | null; cost_usd: number; started_at: number; ended_at: number | null;
}

export interface Move { text: string; action: ActionKind | null; price: number | null; meta: Record<string, unknown> }
/** The referee's reading of a message (backend: referee.reader). */
export interface Reading {
  kind: "offer" | "accept" | "reject" | "none"; price: number | null; source: "structured" | "rules" | "llm";
  ambiguous: boolean; candidates: number[]; note: string; shadow: Reading | null;
}
export interface Message {
  idx: number; sender: Role; text: string; move: Move; t: number; latency_s: number;
  reading: Reading | null;   // null only from an API older than the reader
  offer: number | null;   // the price this message offers or accepts, per the reading
}

export interface Scenario {
  id: string; item: string; currency: string; seller_reservation: number; buyer_reservation: number;
  market_low: number; market_high: number; info_mode: string;
  rules: { max_rounds: number; deadline_known: boolean; time_limit_s: number | null };
}

export interface Outcome {
  deal: boolean; price: number | null; closed_by: Role | null; closed_at: number | null; messages: number;
  end_reason: string; seller_share: number; buyer_share: number; past_reservation: Role | null;
  error_by: Role | null; detail: string;
}

export interface AgentRef { name: string; version: string; config: Record<string, unknown> }

export interface MatchDetail {
  match: {
    id: string; run_id: string | null; scenario: Scenario; seed: number | null; seller: AgentRef; buyer: AgentRef;
    protocol: string; status: string; outcome: Outcome | null; cost_usd: number; meta: Record<string, unknown>;
    started_at: number; ended_at: number | null;
  };
  messages: Message[];
  llm_calls: {
    profile: string; provider: string; model: string; tags: Record<string, string>;
    usage: { input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_write_tokens: number };
    cost_usd: number; latency_s: number; cached: boolean; error: string | null;
  }[];
}

export interface SideStats {
  label: string; matches: number; mean_share: Estimate; deal_rate: Estimate; past_reservation: number; errors: number;
  clean_deal_rate?: Estimate | null;   // deals within its own limit
}
export interface Breakdown { key: string; a: Estimate; b: Estimate; diff: Paired }
/** One promotion check (docs/04-hill-climbing.md §3.1). */
export interface Check { name: "gain" | "limit" | "deals" | "opponents"; status: "pass" | "fail" | "warn" | "n/a"; detail: string }
/** A benchmark challenger against the reference, on the pairs both finished. */
export interface ChallengerStats {
  subject: string; side: SideStats; reference: SideStats; diff: Paired;
  by_opponent: Breakdown[]; by_role: Breakdown[]; by_cell: Breakdown[];
  stopped_at: number | null;   // early stopping dropped it after this many pairs
  checks: Check[];
}
export interface FollowUp { run_id: string; name: string; agents: string[] }
export interface GymReport {
  run_id: string; name: string; mode: "duel" | "benchmark"; status: string; total: number | null; done: number;
  purpose: "dev" | "holdout"; tier: string | null; source_run: string | null; follow_ups: FollowUp[];
  a: SideStats; b: SideStats; diff: Paired; by_opponent: Breakdown[]; by_role: Breakdown[]; by_cell: Breakdown[];
  challengers: ChallengerStats[];   // benchmark: every challenger vs the reference (B)
  cost_usd: number; input_tokens: number; output_tokens: number;
}

export interface Standing {
  rank: number; label: string; rating: number; mean_share: Estimate; deal_rate: Estimate; matches: number;
  past_reservation: number; errors: number;
}
export interface ArenaReport {
  run_id: string; name: string; status: string; total: number | null; done: number;
  leaderboard: Standing[]; matrix: { row: string; col: string; mean_share: number; n: number }[]; cost_usd: number;
}

export type RunReport =
  | { kind: "gym"; report: GymReport }
  | { kind: "arena"; report: ArenaReport }
  | { kind: "match"; report: null };

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${path}`);
  return res.json() as Promise<T>;
}

/** Fetch `path`, refetching whenever `version` changes. */
export function useApi<T>(path: string | null, version: unknown = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let live = true;
    get<T>(path)
      .then((d) => live && (setData(d), setError(null)))
      .catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [path, version]);
  return { data, error };
}

/** Subscribe to a server-sent event stream; handlers get parsed JSON. Closes on "end". */
export function useEventStream(path: string | null, handlers: Record<string, (data: unknown) => void>) {
  useEffect(() => {
    if (!path) return;
    const es = new EventSource(`/api${path}`);
    for (const [event, fn] of Object.entries(handlers)) {
      es.addEventListener(event, (e) => {
        fn(JSON.parse((e as MessageEvent).data));
        if (event === "end") es.close();
      });
    }
    es.addEventListener("end", () => es.close());
    return () => es.close();
    // handlers are recreated each render; the stream only depends on the path
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
}
