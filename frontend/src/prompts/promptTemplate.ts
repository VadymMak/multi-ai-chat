export interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  model: "openai" | "anthropic" | "grok" | "any";
  template: string;
  placeholders: string[]; // For UI to show dynamic fields
  defaultValues?: Record<string, string>; // Optional: prefilled
}

export const promptTemplates: PromptTemplate[] = [
  {
    id: "career_advisor",
    name: "AI Career Advisor",
    description: "Guide me on career decisions, job search, or upskilling",
    model: "openai",
    template: `Act as a professional AI career advisor. Help the user navigate their career as a [role] with guidance on [goal]. Provide practical and strategic advice.`,
    placeholders: ["role", "goal"],
    defaultValues: {
      role: "frontend developer",
      goal: "becoming senior in the next 6 months",
    },
  },
  {
    id: "dev_expert",
    name: "Development Consultant",
    description: "Provide deep insight into a coding or system design issue",
    model: "any",
    template: `Act as a senior [specialty] engineer. Help solve the following problem in detail: [problem]`,
    placeholders: ["specialty", "problem"],
  },
  {
    id: "summarizer",
    name: "Meeting Summarizer",
    description: "Summarize a technical or business discussion",
    model: "anthropic",
    template: `You are a helpful AI. Summarize the key points and action items from this transcript:\n\n[transcript]`,
    placeholders: ["transcript"],
  },
  {
    id: "troubleshooter",
    name: "Troubleshooting Agent",
    description: "Diagnose and resolve a software issue",
    model: "openai",
    template: `Act as a software troubleshooter. Diagnose this issue and suggest fixes:\n\n[issue_description]`,
    placeholders: ["issue_description"],
  },
  {
    id: "prompt_generator",
    name: "Prompt Generator",
    description: "Generate a better prompt from a vague user request",
    model: "openai",
    template: `Act as a prompt engineer. Improve this request by rewriting it as a powerful prompt:\n\n[request]`,
    placeholders: ["request"],
  },
  {
    id: "esoteric_insight",
    name: "Esoteric Advisor",
    description: "Provide insight from Buddhist, Vedic, or symbolic sources",
    model: "anthropic",
    template: `Act as a spiritual guide drawing from Buddhist and Vedic knowledge. Reflect on this question:\n\n[spiritual_question]`,
    placeholders: ["spiritual_question"],
  },
];
