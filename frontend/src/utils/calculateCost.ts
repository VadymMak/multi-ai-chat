import { MODEL_PRICING, ModelName } from "../config/pricing";

/**
 * Calculate the USD cost for token usage
 * @param inputTokens - Number of input tokens
 * @param outputTokens - Number of output tokens
 * @param model - Model name
 * @returns Formatted cost string like "$0.02" or "$1.50"
 */
export function calculateCost(
  inputTokens: number,
  outputTokens: number,
  model: string
): string {
  // Check if model has pricing data
  const pricing = MODEL_PRICING[model as ModelName];

  if (!pricing) {
    // Unknown model, return placeholder
    return "$0.00";
  }

  // Calculate cost: (tokens * price_per_1M_tokens) / 1,000,000
  const inputCost = (inputTokens * pricing.input) / 1_000_000;
  const outputCost = (outputTokens * pricing.output) / 1_000_000;
  const totalCost = inputCost + outputCost;

  // Format as currency
  if (totalCost < 0.01) {
    return "$<0.01";
  }

  return `$${totalCost.toFixed(2)}`;
}
