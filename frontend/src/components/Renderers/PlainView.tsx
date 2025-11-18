import React from "react";
import { MarkdownMessage } from "../Shared/MarkdownMessage";

/**
 * Plain (and poem-plain) renderer. It strips markdown adorners and preserves
 * newlines, delegating to MarkdownMessage with kind="plain" or "poem_plain".
 */
type Props = {
  text: string;
  isUser?: boolean;
  className?: string;
  /** If true, uses the poem-friendly spacing variant. */
  poem?: boolean;
};

const PlainView: React.FC<Props> = ({
  text,
  isUser = false,
  className,
  poem = false,
}) => {
  const kind = poem ? ("poem_plain" as const) : ("plain" as const);
  return (
    <div className={className}>
      <MarkdownMessage text={text} isUser={isUser} kind={kind} />
    </div>
  );
};

export default PlainView;
