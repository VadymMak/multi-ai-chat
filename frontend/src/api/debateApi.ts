/**
 * API client for Debate Mode
 */

import axiosInstance from "../services/axiosInstance";
import { DebateRequest, DebateResult } from "../types/debate";

/**
 * Start a new debate
 */
export async function startDebate(
  request: DebateRequest
): Promise<DebateResult> {
  const response = await axiosInstance.post<DebateResult>(
    "/api/debate",
    request
  );
  return response.data;
}

/**
 * Get debate by ID (placeholder for future functionality)
 */
export async function getDebate(debateId: string): Promise<DebateResult> {
  const response = await axiosInstance.get<DebateResult>(
    `/api/debate/${debateId}`
  );
  return response.data;
}
