// src/utils/markdown.ts
export const convertMarkdownLinkToHTML = (text: string): string => {
  return text.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    `<a href="$2" target="_blank" rel="noopener noreferrer" class="text-blue-700 underline">$1</a>`
  );
};
