// File: src/utils/markdown.ts

/**
 * Converts Markdown-style links to HTML anchor elements.
 * Safely escapes content to prevent injection risks.
 * Supports multiple links per line.
 *
 * Example: [Google](https://google.com)
 */
export const convertMarkdownLinkToHTML = (text: string): string => {
  return text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_, label, url) =>
      `<a href="${encodeURI(
        url
      )}" target="_blank" rel="noopener noreferrer" class="text-blue-700 underline hover:text-blue-900">${escapeHtml(
        label
      )}</a>`
  );
};

/**
 * Escapes HTML-sensitive characters in user-provided text.
 */
const escapeHtml = (str: string): string =>
  str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
