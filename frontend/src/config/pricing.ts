// Model pricing in USD per 1M tokens
export const MODEL_PRICING = {
  "gpt-4o": { input: 2.5, output: 10.0 },
  "gpt-4o-mini": { input: 0.15, output: 0.6 },
  "claude-sonnet-4-20250514": { input: 3.0, output: 15.0 },
  "claude-3-5-haiku-latest": { input: 0.25, output: 1.25 },
} as const;

export type ModelName = keyof typeof MODEL_PRICING;
