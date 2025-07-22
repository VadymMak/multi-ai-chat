import React from "react";
import { MarkdownMessage } from "../Shared/MarkdownMessage";
import type { RenderKind } from "../../types/chat";

type Props = {
  text: string;
  /** Render as user bubble (affects link colors, etc.) */
  isUser?: boolean;
  /** Extra wrapper classes */
  className?: string;
  /**
   * Defaults to "markdown". You can pass "poem_plain" or "poem_code" if you
   * explicitly want MarkdownMessage to behave like those modes,
   * though normally MessageRenderer picks the right one.
   */
  kind?: RenderKind;
};

const MarkdownView: React.FC<Props> = ({
  text,
  isUser = false,
  className,
  kind = "markdown",
}) => {
  return (
    <div className={className}>
      <MarkdownMessage text={text} isUser={isUser} kind={kind} />
    </div>
  );
};

export default MarkdownView;
