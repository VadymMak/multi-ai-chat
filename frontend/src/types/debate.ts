/**
 * Types for Debate Mode
 */

export interface DebateRound {
  round_num: number;
  model: string;
  role: "proposer" | "critic" | "defender";
  content: string;
  tokens: number;
  cost: number;
}

export interface FinalSolution {
  model: string;
  role: "judge";
  content: string;
  tokens: number;
  cost: number;
}

export interface DebateResult {
  debate_id: string;
  topic: string;
  session_id?: string;
  rounds: DebateRound[];
  final_solution: FinalSolution;
  total_tokens: number;
  total_cost: number;
  created_at: string;
}

export interface DebateRequest {
  topic: string;
  rounds: number;
  session_id?: string;
  role_id?: number;
  project_id?: number | string;
}
