// src/components/Shared/CodeBlock.tsx
import React, { memo, useMemo, useRef, useEffect, useState } from "react";
import { Highlight, themes } from "prism-react-renderer";
import { Copy, Download, WrapText, FileDown } from "lucide-react";
import { createSimplePdf } from "../../utils/createPdf";

// A monospace font with Cyrillic support placed in /public/fonts
const PDF_FONT_URL = "/fonts/NotoSansMono-Regular.ttf?v=2";

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
  const [wrapped, setWrapped] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [toastVisible, setToastVisible] = useState(false);
  const toastTimer = useRef<number | null>(null);
  const toastHideTimer = useRef<number | null>(null);

  const showToast = (text: string) => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    if (toastHideTimer.current) window.clearTimeout(toastHideTimer.current);
    setToast(text);
    setToastVisible(true);
    toastTimer.current = window.setTimeout(() => setToastVisible(false), 1100);
    toastHideTimer.current = window.setTimeout(() => setToast(null), 1500);
  };

  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
      if (toastHideTimer.current) window.clearTimeout(toastHideTimer.current);
    },
    []
  );

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
      showToast("Copied");
    } catch {
      showToast("Copy failed");
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
    showToast("Download started");
  };

  const onExportPdf = async () => {
    try {
      const lines = code.split(/\r?\n/);
      const safeBase =
        (fileNameProp && fileNameProp.replace(/\.[^.]+$/, "")) ||
        `code-${extFromLang(langRaw)}`;

      const { url, filename } = await createSimplePdf(lines, {
        title: safeBase,
        filename: safeBase,
        fontUrl: PDF_FONT_URL,
        monospace: true,
        tabSize: 2,
      });

      const a = document.createElement("a");
      a.href = url;
      a.download = filename.endsWith(".pdf") ? filename : `${safeBase}.pdf`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();

      if (url.startsWith("blob:")) {
        setTimeout(() => {
          try {
            URL.revokeObjectURL(url);
          } catch {}
        }, 1000);
      }
      showToast("PDF ready");
    } catch (err: any) {
      console.error("[PDF] Export failed:", err);
      showToast(err?.message ? `PDF failed: ${err.message}` : "PDF failed");
    }
  };

  const header = useMemo(
    () => fileNameProp || (langRaw ? langRaw.toUpperCase() : "CODE"),
    [fileNameProp, langRaw]
  );

  return (
    <div
      data-md-block="true"
      className="rounded-2xl border border-neutral-200 bg-neutral-50 overflow-hidden shadow-sm"
      role="region"
      aria-label={header}
    >
      {/* Header */}
      <div className="relative flex items-center justify-between px-3 py-2 border-b border-neutral-200 text-xs text-neutral-600">
        <div className="truncate">{header}</div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setWrapped((w) => !w)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-neutral-200/60"
            title={wrapped ? "Disable wrap" : "Wrap lines"}
            aria-label="Toggle line wrap"
          >
            <WrapText size={14} />
          </button>
          <button
            onClick={onCopy}
            className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-neutral-200/60"
            title="Copy"
            aria-label="Copy code"
          >
            <Copy size={14} />
          </button>
          <button
            onClick={onDownload}
            className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-neutral-200/60"
            title="Download"
            aria-label="Download code"
          >
            <Download size={14} />
          </button>
          <button
            onClick={onExportPdf}
            className="inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-neutral-200/60"
            title="Export as PDF"
            aria-label="Export as PDF"
          >
            <FileDown size={14} />
          </button>
        </div>

        {/* Inline toast */}
        {toast && (
          <div
            aria-live="polite"
            className={[
              "pointer-events-none absolute right-3 top-2",
              "rounded-full bg-black/75 px-2 py-0.5 text-[11px] font-medium text-white shadow",
              "transition-all duration-300",
              toastVisible
                ? "opacity-100 translate-y-0"
                : "opacity-0 translate-y-1",
            ].join(" ")}
          >
            {toast}
          </div>
        )}
      </div>

      {/* Code */}
      <div className="max-h-[480px] overflow-auto">
        <Highlight
          theme={themes.github}
          code={code}
          language={prismLang as any}
        >
          {({ className, style, tokens, getLineProps, getTokenProps }) => (
            <pre
              className={[
                className || "",
                "m-0 px-3 py-3 bg-transparent font-mono text-[13.5px] leading-[1.45]",
                wrapped ? "whitespace-pre-wrap break-words" : "whitespace-pre",
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
                      <span className="select-none text-neutral-400 pr-3 text-right w-8">
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
