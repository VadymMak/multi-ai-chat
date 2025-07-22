// src/components/Shared/CodeBlock.tsx
import React, { memo, useMemo, useState } from "react";
import { Highlight, themes } from "prism-react-renderer";
import { Copy, Download, Maximize2, X } from "lucide-react";
import { toast } from "../../store/toastStore";

type CodeBlockProps = {
  code: string;
  language?: string | null;
  filename?: string | null;
  showLineNumbers?: boolean;
};

/* ------------ helpers: language/extension inference & mapping ------------ */

const extFromLang = (lang?: string | null) => {
  if (!lang) return "txt";
  const m = (lang || "").toLowerCase();
  const map: Record<string, string> = {
    js: "js",
    javascript: "js",
    ts: "ts",
    typescript: "ts",
    jsx: "jsx",
    tsx: "tsx",
    json: "json",
    py: "py",
    python: "py",
    sh: "sh",
    bash: "sh",
    html: "html",
    css: "css",
    md: "md",
    markdown: "md",
    go: "go",
    rs: "rs",
    rust: "rs",
    java: "java",
    kt: "kt",
    kotlin: "kt",
    c: "c",
    "c++": "cpp",
    cpp: "cpp",
    cs: "cs",
    "c#": "cs",
    sql: "sql",
    yml: "yml",
    yaml: "yml",
    xml: "xml",
    txt: "txt",
    text: "txt",
  };
  return map[m] || m;
};

const normalizeLangFromClass = (cls?: string | null) => {
  if (!cls) return null;
  const m = cls.match(/language-([\w#+-]+)/i);
  return m ? m[1] : null;
};

// Infer a language from a filename's extension
const inferLangFromFilename = (filename?: string | null): string | null => {
  if (!filename) return null;
  const m = filename.toLowerCase().match(/\.([a-z0-9]+)$/);
  if (!m) return null;
  const ext = m[1];
  const extToLang: Record<string, string> = {
    js: "javascript",
    mjs: "javascript",
    cjs: "javascript",
    ts: "typescript",
    tsx: "tsx",
    jsx: "jsx",
    json: "json",
    py: "python",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    html: "html",
    css: "css",
    md: "markdown",
    markdown: "markdown",
    go: "go",
    rs: "rust",
    java: "java",
    kt: "kotlin",
    c: "c",
    h: "c",
    cpp: "cpp",
    cxx: "cpp",
    cc: "cpp",
    cs: "csharp",
    sql: "sql",
    yml: "yaml",
    yaml: "yaml",
    xml: "xml",
    txt: "text",
  };
  return extToLang[ext] || null;
};

// Map common aliases to Prism’s expected ids
const toPrismLang = (lang: string | null): string | null => {
  if (!lang) return null;
  const l = lang.toLowerCase();
  const map: Record<string, string> = {
    "c++": "cpp",
    cs: "csharp",
    "c#": "csharp",
    ts: "typescript",
    js: "javascript",
    py: "python",
    sh: "bash",
    yml: "yaml",
    md: "markdown",
    txt: "markdown",
    text: "markdown",
  };
  return map[l] || l;
};

// Pick a MIME-ish type for simple downloads
const mimeForExt = (ext: string) => {
  const map: Record<string, string> = {
    js: "text/javascript",
    ts: "text/plain",
    tsx: "text/plain",
    jsx: "text/plain",
    json: "application/json",
    py: "text/x-python",
    sh: "text/x-shellscript",
    html: "text/html",
    css: "text/css",
    md: "text/markdown",
    go: "text/plain",
    rs: "text/plain",
    java: "text/x-java",
    kt: "text/plain",
    c: "text/plain",
    cpp: "text/plain",
    cs: "text/plain",
    sql: "text/plain",
    yml: "text/yaml",
    txt: "text/plain",
    xml: "application/xml",
  };
  return map[ext] || "text/plain";
};

/* -------------------------------- component ------------------------------- */

const CodeBlockInner: React.FC<CodeBlockProps> = ({
  code,
  language,
  filename: fileNameProp,
  showLineNumbers = true,
}) => {
  const [wrapLines, setWrapLines] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Prefer explicit language; fall back to filename inference
  const langRaw = useMemo(
    () =>
      (language && language.trim().toLowerCase()) ||
      inferLangFromFilename(fileNameProp) ||
      null,
    [language, fileNameProp]
  );

  const prismLang = useMemo(
    () => toPrismLang(langRaw) || "markdown",
    [langRaw]
  );

  const onCopy = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(code);
      } else {
        // Fallback
        const ta = document.createElement("textarea");
        ta.value = code;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      toast.success("Code copied!");
    } catch {
      toast.error("Failed to copy");
    }
  };

  const onDownload = () => {
    const ext = extFromLang(langRaw || inferLangFromFilename(fileNameProp));
    const blob = new Blob([code], { type: `${mimeForExt(ext)};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download =
      fileNameProp && /\S/.test(fileNameProp) ? fileNameProp : `code.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast.success("Download started");
  };

  const header = useMemo(
    () => fileNameProp || (langRaw ? langRaw.toUpperCase() : "CODE"),
    [fileNameProp, langRaw]
  );

  return (
    <div
      data-md-block="true"
      className="rounded-2xl border border-border bg-panel overflow-hidden shadow-sm"
      role="region"
      aria-label={header}
    >
      {/* Header */}
      <div className="relative flex items-center justify-between px-3 py-2 bg-surface border-b border-border">
        <span className="text-xs font-semibold text-text-primary uppercase tracking-wide">
          {header}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onCopy}
            className="group flex items-center gap-1.5 px-2.5 py-1 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
            title="Copy code"
          >
            <Copy size={14} className="text-text-secondary" />
            <span className="text-xs font-medium text-text-primary">Copy</span>
          </button>
          <button
            onClick={onDownload}
            className="group flex items-center gap-1.5 px-2.5 py-1 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
            title="Download as file"
          >
            <Download size={14} className="text-text-secondary" />
            <span className="text-xs font-medium text-text-primary">
              Download
            </span>
          </button>
          <button
            onClick={() => setWrapLines(!wrapLines)}
            className="group flex items-center gap-1.5 px-2.5 py-1 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
            title={wrapLines ? "Unwrap lines" : "Wrap lines"}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="text-text-secondary"
            >
              {wrapLines ? (
                <path d="M3 10h11m0 0l-4-4m4 4l-4 4m4 4h11" />
              ) : (
                <path d="M3 10h18M3 14h18" />
              )}
            </svg>
            <span className="text-xs font-medium text-text-primary">
              {wrapLines ? "Unwrap" : "Wrap"}
            </span>
          </button>
          <button
            onClick={() => setIsFullscreen(true)}
            className="group flex items-center gap-1.5 px-2.5 py-1 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
            title="Open in fullscreen"
          >
            <Maximize2 size={14} className="text-text-secondary" />
            <span className="text-xs font-medium text-text-primary">
              Fullscreen
            </span>
          </button>
        </div>
      </div>

      {/* Code */}
      <div className="max-h-[480px] overflow-auto">
        <Highlight
          theme={themes.vsDark}
          code={code}
          language={prismLang as any}
        >
          {({ className, style, tokens, getLineProps, getTokenProps }) => (
            <pre
              className={[
                className || "",
                "m-0 px-3 py-3 bg-transparent font-mono text-[13.5px] leading-[1.45]",
                wrapLines ? "whitespace-pre-wrap break-all" : "whitespace-pre",
              ].join(" ")}
              style={style}
            >
              {tokens.map((line, i) => {
                const {
                  className: lineCN,
                  style: lineStyle,
                  ...restLine
                } = getLineProps({ line });
                return (
                  <div
                    key={i}
                    className={`flex ${lineCN || ""}`}
                    style={lineStyle}
                    {...restLine}
                  >
                    {showLineNumbers && (
                      <span className="select-none text-text-secondary pr-3 text-right w-8">
                        {i + 1}
                      </span>
                    )}
                    <span className="flex-1">
                      {line.map((token, j) => {
                        const {
                          className: tokCN,
                          style: tokStyle,
                          ...restTok
                        } = getTokenProps({ token });
                        return (
                          <span
                            key={j}
                            className={tokCN}
                            style={tokStyle}
                            {...restTok}
                          />
                        );
                      })}
                    </span>
                  </div>
                );
              })}
            </pre>
          )}
        </Highlight>
      </div>

      {/* Fullscreen Modal */}
      {isFullscreen && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
          onClick={() => setIsFullscreen(false)}
        >
          <div
            className="w-full h-full max-w-7xl max-h-[90vh] bg-panel border border-border rounded-2xl overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Fullscreen Header */}
            <div className="flex items-center justify-between px-4 py-3 bg-surface border-b border-border">
              <span className="text-sm font-semibold text-text-primary uppercase tracking-wide">
                {header}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={onCopy}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
                  title="Copy code"
                >
                  <Copy size={14} className="text-text-secondary" />
                  <span className="text-xs font-medium text-text-primary">
                    Copy
                  </span>
                </button>
                <button
                  onClick={onDownload}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
                  title="Download as file"
                >
                  <Download size={14} className="text-text-secondary" />
                  <span className="text-xs font-medium text-text-primary">
                    Download
                  </span>
                </button>
                <button
                  onClick={() => setWrapLines(!wrapLines)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface/80 border border-border rounded-md transition-all"
                  title={wrapLines ? "Unwrap lines" : "Wrap lines"}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className="text-text-secondary"
                  >
                    {wrapLines ? (
                      <path d="M3 10h11m0 0l-4-4m4 4l-4 4m4 4h11" />
                    ) : (
                      <path d="M3 10h18M3 14h18" />
                    )}
                  </svg>
                  <span className="text-xs font-medium text-text-primary">
                    {wrapLines ? "Unwrap" : "Wrap"}
                  </span>
                </button>
                <button
                  onClick={() => setIsFullscreen(false)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-error/10 hover:bg-error/20 border border-error rounded-md transition-all"
                  title="Close fullscreen"
                >
                  <X size={14} className="text-error" />
                  <span className="text-xs font-medium text-error">Close</span>
                </button>
              </div>
            </div>

            {/* Fullscreen Code */}
            <div className="flex-1 overflow-auto">
              <Highlight
                theme={themes.vsDark}
                code={code}
                language={prismLang as any}
              >
                {({
                  className,
                  style,
                  tokens,
                  getLineProps,
                  getTokenProps,
                }) => (
                  <pre
                    className={[
                      className || "",
                      "m-0 px-4 py-4 bg-transparent font-mono text-sm leading-[1.6]",
                      wrapLines
                        ? "whitespace-pre-wrap break-all"
                        : "whitespace-pre",
                    ].join(" ")}
                    style={style}
                  >
                    {tokens.map((line, i) => {
                      const {
                        className: lineCN,
                        style: lineStyle,
                        ...restLine
                      } = getLineProps({ line });
                      return (
                        <div
                          key={i}
                          className={`flex ${lineCN || ""}`}
                          style={lineStyle}
                          {...restLine}
                        >
                          {showLineNumbers && (
                            <span className="select-none text-text-secondary pr-4 text-right min-w-[3rem]">
                              {i + 1}
                            </span>
                          )}
                          <span className="flex-1">
                            {line.map((token, j) => {
                              const {
                                className: tokCN,
                                style: tokStyle,
                                ...restTok
                              } = getTokenProps({ token });
                              return (
                                <span
                                  key={j}
                                  className={tokCN}
                                  style={tokStyle}
                                  {...restTok}
                                />
                              );
                            })}
                          </span>
                        </div>
                      );
                    })}
                  </pre>
                )}
              </Highlight>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Helpful for renderers to detect this component
(CodeBlockInner as any).displayName = "CodeBlock";

// Only re-render when these props change
const propsEqual = (a: Readonly<CodeBlockProps>, b: Readonly<CodeBlockProps>) =>
  a.code === b.code &&
  (a.language ?? null) === (b.language ?? null) &&
  (a.filename ?? null) === (b.filename ?? null) &&
  (a.showLineNumbers ?? true) === (b.showLineNumbers ?? true);

const CodeBlock = memo(CodeBlockInner, propsEqual);
export default CodeBlock;

/** Parse language/filename meta from markdown code fences */
export const codeFenceToProps = (
  rawClassName?: string,
  meta?: string
): { language: string | null; filename: string | null } => {
  const language = normalizeLangFromClass(rawClassName);
  let filename: string | null = null;

  // Support meta like:
  // ```ts filename=index.ts
  // ```ts file="index.ts"
  // ```ts title=example.ts
  if (meta) {
    const m =
      meta.match(/\bfilename=(?:"([^"]+)"|([^\s]+))/) ||
      meta.match(/\bfile=(?:"([^"]+)"|([^\s]+))/) ||
      meta.match(/\btitle=(?:"([^"]+)"|([^\s]+))/);
    if (m) filename = (m[1] || m[2]) ?? null;
  }

  const inferred = filename ? inferLangFromFilename(filename) : null;
  return { language: language || inferred, filename };
};
