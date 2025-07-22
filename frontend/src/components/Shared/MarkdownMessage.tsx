// File: src/components/Shared/MarkdownMessage.tsx
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CodeBlock, { codeFenceToProps } from "./CodeBlock";
import type { RenderKind } from "../../types/chat";

type Props = {
  text: string;
  isUser: boolean;
  kind?: RenderKind; // "markdown" | "plain" | "poem_plain"
};

const REMARK_PLUGINS = [remarkGfm] as const;

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

function tightenMarkdown(s: string): string {
  if (!s) return s;
  return s.replace(/\n{2,}/g, "\n\n");
}

function stripCodeAndListsForPlain(text: string): string {
  let s = text;
  s = s.replace(
    /```[\t ]*([^\n`]*)\n([\s\S]*?)```/g,
    (_m, _lang, body) => body
  );
  s = s.replace(/```[\t ]*([^\n`]*)\n([\s\S]*)$/g, (_m, _lang, body) => body);
  s = s.replace(/`([^`]+)`/g, "$1");
  s = s.replace(/^\s*[-*•·]\s+/gm, "");
  s = s.replace(/^\s*\d+[.)]\s+/gm, "");
  return s;
}

function preprocessDisplay(text: string, kind: RenderKind): string {
  let s = tightenMarkdown(text || "");
  if (kind === "plain" || kind === "poem_plain") {
    s = stripCodeAndListsForPlain(s);
  }
  return s;
}

const MarkdownMessageBase: React.FC<Props> = ({
  text,
  isUser,
  kind = "markdown",
}) => {
  const isPlain = kind === "plain" || kind === "poem_plain";

  // Preprocess only when text/kind change
  const prepared = React.useMemo(
    () => preprocessDisplay(text, kind),
    [text, kind]
  );

  // Stable component mappings; only depends on isUser/isPlain
  const mdComponents = React.useMemo(() => {
    return {
      p: ({ children }: { children: React.ReactNode }) => (
        <div className="mb-[6px] leading-snug">{children}</div>
      ),
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
        if (!isSafeHref(href)) {
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

      code: (props: {
        inline?: boolean;
        className?: string;
        children: React.ReactNode;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        node?: any;
      }) => {
        const { inline, className, children, node } = props;
        const txt = String(children).replace(/\n$/, "");

        if (inline) {
          if (isPlain) return <>{txt}</>;
          return (
            <code className="font-mono px-1 py-0.5 rounded text-[12.5px] bg-neutral-100 text-neutral-900">
              {txt}
            </code>
          );
        }

        const { language, filename } = codeFenceToProps(
          className,
          (node?.data as any)?.meta || node?.meta
        );

        if (isPlain) {
          return (
            <pre className="whitespace-pre-wrap text-[14px] leading-6 bg-transparent border-0 px-0 py-1">
              {txt}
            </pre>
          );
        }

        return <CodeBlock code={txt} language={language} filename={filename} />;
      },
    } as const;
  }, [isUser, isPlain]);

  return (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS as any}
      components={mdComponents as any}
      skipHtml
    >
      {prepared}
    </ReactMarkdown>
  );
};

// Avoid re-parsing unless props materially change
const propsEqual = (a: Props, b: Props) =>
  a.text === b.text &&
  a.isUser === b.isUser &&
  (a.kind ?? "markdown") === (b.kind ?? "markdown");

export const MarkdownMessage = React.memo(MarkdownMessageBase, propsEqual);
export default MarkdownMessage;
