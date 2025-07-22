// src/components/Shared/MarkdownMessage.tsx
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CodeBlock, { codeFenceToProps } from "./CodeBlock";
import type { RenderKind } from "../../types/chat";

function isSafeHref(href?: string | null) {
  if (!href) return false;
  const lower = href.trim().toLowerCase();
  return (
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    lower.startsWith("mailto:") ||
    lower.startsWith("tel:")
  );
}

/** Collapse big gaps and keep tight line spacing */
function tightenMarkdown(s: string): string {
  if (!s) return s;
  return s.replace(/\n{2,}/g, "\n\n");
}

/** Strip code/list adornments for PLAIN-like modes */
function stripCodeAndListsForPlain(text: string): string {
  let s = text;

  // Replace fenced code blocks with raw inner text (no backticks)
  // ```lang\n...```  ->  ...
  s = s.replace(
    /```[\t ]*([^\n`]*)\n([\s\S]*?)```/g,
    (_m, _lang, body) => body
  );

  // Handle unterminated fence at end of stream
  s = s.replace(/```[\t ]*([^\n`]*)\n([\s\S]*)$/g, (_m, _lang, body) => body);

  // Strip inline code ticks: `word` -> word
  s = s.replace(/`([^`]+)`/g, "$1");

  // Remove list markers (bulleted/ordered)
  s = s.replace(/^\s*[-*•·]\s+/gm, "");
  s = s.replace(/^\s*\d+[.)]\s+/gm, "");

  return s;
}

/** Prepare text for rendering based on kind */
function preprocessDisplay(text: string, kind: RenderKind): string {
  let s = tightenMarkdown(text || "");
  if (kind === "plain" || kind === "poem_plain") {
    s = stripCodeAndListsForPlain(s);
  }
  // For markdown (and anything else routed here) we do not inject fences.
  return s;
}

export const MarkdownMessage: React.FC<{
  text: string;
  isUser: boolean;
  kind?: RenderKind; // "markdown" | "plain" | "poem_plain" (poem_code handled in bubble)
}> = ({ text, isUser, kind = "markdown" }) => {
  const mdComponents = React.useMemo(() => {
    const isPlain = kind === "plain" || kind === "poem_plain";

    return {
      // compact paragraphs
      p: ({ children }: { children: React.ReactNode }) => (
        <div className="mb-[6px] leading-snug">{children}</div>
      ),
      // tight lists (though plain mode strips markers already)
      ul: ({ children }: { children: React.ReactNode }) => (
        <div className="my-[2px] space-y-[4px]">{children}</div>
      ),
      ol: ({ children }: { children: React.ReactNode }) => (
        <div className="my-[2px] space-y-[4px]">{children}</div>
      ),
      li: (
        props: React.DetailedHTMLProps<
          React.LiHTMLAttributes<HTMLLIElement>,
          HTMLLIElement
        >
      ) => <div className="leading-snug mb-[4px]">{props.children}</div>,
      a: ({ href, children }: { href?: string; children: React.ReactNode }) => {
        const safe = isSafeHref(href);
        if (!safe) {
          return (
            <span className="underline decoration-dotted cursor-not-allowed">
              {children}
            </span>
          );
        }
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className={`underline ${
              isUser
                ? "text-blue-200 hover:text-white"
                : "text-blue-600 hover:text-blue-800"
            }`}
          >
            {children}
          </a>
        );
      },
      blockquote: ({ children }: { children: React.ReactNode }) => (
        <blockquote className="border-l-4 border-gray-300 pl-3 italic my-2">
          {children}
        </blockquote>
      ),
      hr: () => <hr className="my-2 border-neutral-200" />,
      img: ({ alt }: { alt?: string }) => (
        <span className="italic opacity-80">
          [image{alt ? `: ${alt}` : ""}]
        </span>
      ),

      // code (inline & block)
      code: (props: {
        inline?: boolean;
        className?: string;
        children: React.ReactNode;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        node?: any;
      }) => {
        const { inline, className, children, node } = props;
        const txt = String(children).replace(/\n$/, "");

        // In plain-ish modes: inline code is rendered as bare text
        if (inline && isPlain) {
          return <>{txt}</>;
        }
        if (inline) {
          return (
            <code className="font-mono px-1 py-0.5 rounded text-[12.5px] bg-neutral-100 text-neutral-900">
              {txt}
            </code>
          );
        }

        // Block code
        const { language, filename } = codeFenceToProps(
          className,
          (node?.data as any)?.meta || node?.meta
        );

        // In plain-ish modes: show as simple pre (no gray box/border)
        if (isPlain) {
          return (
            <pre className="whitespace-pre-wrap text-[14px] leading-6 bg-transparent border-0 px-0 py-1">
              {txt}
            </pre>
          );
        }

        // Normal markdown → real code block
        return <CodeBlock code={txt} language={language} filename={filename} />;
      },
    } as const;
  }, [isUser, kind]);

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents as any}>
      {preprocessDisplay(text, kind)}
    </ReactMarkdown>
  );
};
