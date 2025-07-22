import React from "react";

export default function PdfChip({
  status = "ready",
  href,
  filename,
  sizeBytes,
}: {
  status?: "pending" | "ready" | "error";
  href?: string;
  filename?: string;
  sizeBytes?: number;
}) {
  const fmt = (n?: number) =>
    typeof n === "number" ? `${(n / 1024).toFixed(1)} KB` : undefined;

  const label =
    status === "pending"
      ? "PDF: generating…"
      : status === "error"
      ? "PDF: error"
      : filename
      ? `PDF: ${filename}`
      : "PDF ready";

  return (
    <div className="mt-2 inline-flex items-center gap-2 rounded-full border border-neutral-300 bg-neutral-100 px-3 py-1 text-xs text-neutral-700">
      <span>📄 {label}</span>
      {status === "ready" && href && (
        <a
          href={href}
          download={filename || true}
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
          className="underline hover:text-neutral-900"
        >
          Download{sizeBytes ? ` (${fmt(sizeBytes)})` : ""}
        </a>
      )}
    </div>
  );
}
