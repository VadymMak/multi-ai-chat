// src/components/Layout/AutoScrollArea.tsx
import React, { useRef, useImperativeHandle, forwardRef } from "react";

export interface AutoScrollAreaHandle {
  scrollToBottom: () => void;
}

interface AutoScrollAreaProps {
  children: React.ReactNode;
  className?: string;
}

const AutoScrollArea = forwardRef<AutoScrollAreaHandle, AutoScrollAreaProps>(
  ({ children, className }, ref) => {
    const bottomRef = useRef<HTMLDivElement | null>(null);

    useImperativeHandle(ref, () => ({
      scrollToBottom: () => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      },
    }));

    return (
      <div className={className}>
        {children}
        <div ref={bottomRef} className="h-4" />
      </div>
    );
  }
);

export default AutoScrollArea;
