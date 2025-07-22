/**
 * Zustand store for Debate Mode
 */

import { create } from "zustand";
import { DebateRound, FinalSolution, DebateResult } from "../types/debate";
import { startDebate as apiStartDebate } from "../api/debateApi";
import { useToastStore } from "./toastStore";

interface DebateStore {
  // State
  isDebating: boolean;
  currentRound: number;
  totalRounds: number;
  topic: string | null;
  rounds: DebateRound[];
  finalSolution: FinalSolution | null;
  debateId: string | null;
  totalTokens: number;
  totalCost: number;
  error: string | null;

  // Actions
  startDebate: (
    topic: string,
    rounds?: number,
    sessionId?: string
  ) => Promise<void>;
  reset: () => void;
}

const initialState = {
  isDebating: false,
  currentRound: 0,
  totalRounds: 3,
  topic: null,
  rounds: [],
  finalSolution: null,
  debateId: null,
  totalTokens: 0,
  totalCost: 0,
  error: null,
};

export const useDebateStore = create<DebateStore>((set, get) => ({
  ...initialState,

  startDebate: async (
    topic: string,
    rounds: number = 3,
    sessionId?: string
  ) => {
    const { addToast } = useToastStore.getState();

    set({
      isDebating: true,
      currentRound: 0,
      totalRounds: rounds,
      topic,
      rounds: [],
      finalSolution: null,
      error: null,
    });

    try {
      // Call the API
      const result: DebateResult = await apiStartDebate({
        topic,
        rounds,
        session_id: sessionId,
      });

      // Update store with results
      set({
        isDebating: false,
        rounds: result.rounds,
        finalSolution: result.final_solution,
        debateId: result.debate_id,
        totalTokens: result.total_tokens,
        totalCost: result.total_cost,
        currentRound: result.rounds.length,
      });

      addToast(
        `Debate completed! Total cost: $${result.total_cost.toFixed(4)}`,
        "success"
      );
    } catch (error) {
      // ✅ FIX: Properly type the error
      let errorMessage = "Failed to start debate";

      if (error instanceof Error) {
        errorMessage = error.message;
      } else if (typeof error === "object" && error !== null) {
        // Handle axios error
        const axiosError = error as any;
        errorMessage =
          axiosError.response?.data?.detail ||
          axiosError.message ||
          errorMessage;
      }

      set({
        isDebating: false,
        error: errorMessage,
      });

      addToast(`Debate failed: ${errorMessage}`, "error");

      throw error;
    }
  },

  reset: () => {
    set(initialState);
  },
}));
