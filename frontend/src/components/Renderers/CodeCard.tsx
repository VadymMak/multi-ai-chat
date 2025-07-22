import React from "react";
import CodeBlock from "../Shared/CodeBlock";

type Props = {
  code: string;
  language?: string | null;
  filename?: string | null;
  showLineNumbers?: boolean;
  /** Optional wrapper classes so parents can control spacing/layout */
  className?: string;
};

/**
 * CodeCard — thin facade around CodeBlock so MessageRenderer can treat all
 * primary views uniformly (MarkdownView / PlainView / CodeCard).
 */
const CodeCard: React.FC<Props> = ({
  code,
  language,
  filename,
  showLineNumbers = true,
  className,
}) => {
  return (
    <div className={className}>
      <CodeBlock
        code={code}
        language={language}
        filename={filename}
        showLineNumbers={showLineNumbers}
      />
    </div>
  );
};

export default CodeCard;
