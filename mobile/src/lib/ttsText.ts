/** Strip markdown syntax so expo-speech doesn't read "hash star asterisk". */
export function stripMarkdownToSpeakable(md: string): string {
  let text = md;

  // Fenced code blocks — remove entirely (no point reading raw code)
  text = text.replace(/```[\s\S]*?```/g, " ");

  // Headings: ## Heading → Heading
  text = text.replace(/^#{1,6}\s+/gm, "");

  // Bold-italic combined: ***text*** / ___text___
  text = text.replace(/(\*\*\*|___)(.*?)\1/gs, "$2");

  // Bold: **text** / __text__
  text = text.replace(/(\*\*|__)(.*?)\1/gs, "$2");

  // Italic: *text* / _text_
  text = text.replace(/([*_])(.*?)\1/gs, "$2");

  // Inline code: `code` → code
  text = text.replace(/`([^`]+)`/g, "$1");

  // Blockquote markers: > text → text
  text = text.replace(/^>\s?/gm, "");

  // Images: ![alt](url) → (drop entirely)
  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, "");

  // Links: [text](url) → text
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");

  // Unordered list bullets: - item / * item / + item
  text = text.replace(/^[\t ]*[-*+]\s+/gm, "");

  // Ordered list: 1. item
  text = text.replace(/^[\t ]*\d+\.\s+/gm, "");

  // Horizontal rules: --- / *** / ___
  text = text.replace(/^[-*_]{3,}\s*$/gm, "");

  // Collapse runs of blank lines
  text = text.replace(/\n{3,}/g, "\n\n");

  // Collapse multiple spaces / tabs on a line
  text = text.replace(/[ \t]+/g, " ");

  return text.trim();
}

/** Returns "ru-RU" if the text contains Cyrillic characters, otherwise "en-US". */
export function detectTtsLanguage(text: string): string {
  return /[а-яА-ЯёЁ]/.test(text) ? "ru-RU" : "en-US";
}
