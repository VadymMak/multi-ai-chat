export type AiStarter = "openai" | "anthropic";

export interface AiToAiResponse {
  messages: {
    id: string;
    sender: string;
    text: string;
    isSummary?: boolean;
  }[];
  youtube?: any[];
  web?: any[];
}
