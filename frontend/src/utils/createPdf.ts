// utils/createPdf.ts
import { PDFDocument, StandardFonts, rgb, type PDFFont } from "pdf-lib";
import fontkit from "@pdf-lib/fontkit";

type CreatePdfOpts = {
  title?: string;
  filename?: string;
  fontUrl?: string;   // optional override; must be .ttf or .otf
  margin?: number;
  fontSize?: number;
  lineHeight?: number;
  pageWidth?: number;
  pageHeight?: number;
  monospace?: boolean;
  tabSize?: number;
};

// A4 in PostScript points
const A4 = { width: 595.28, height: 841.89 };

// ---- Helpers ---------------------------------------------------------------

const isCombining = (ch: string) => /\p{M}/u.test(ch);
const normalizeLine = (s: string) => (s ?? "").replace(/\r/g, "").normalize("NFC");
const expandTabs = (s: string, n = 2) => s.replace(/\t/g, " ".repeat(Math.max(1, n)));

const DEFAULT_CANDIDATE_FONTS: string[] = [
  "/fonts/NotoSansMono-Regular.ttf",
  "/fonts/DejaVuSansMono.ttf",
  "/fonts/JetBrainsMono-Regular.ttf",
  "/fonts/RobotoMono-Regular.ttf",
  "/fonts/UbuntuMono-R.ttf",
];

/** Return "ttf"/"otf" when magic bytes match, otherwise "" */
function sniffFontFormat(bytes: Uint8Array): "ttf" | "otf" | "" {
  if (bytes.length < 4) return "";
  const [b0, b1, b2, b3] = bytes;
  // TrueType: 00 01 00 00
  if (b0 === 0x00 && b1 === 0x01 && b2 === 0x00 && b3 === 0x00) return "ttf";
  // OpenType/CFF: 4F 54 54 4F ("OTTO")
  if (b0 === 0x4f && b1 === 0x54 && b2 === 0x54 && b3 === 0x4f) return "otf";
  return "";
}

/** Detects if any code point is > 0xFF (needs Unicode-capable font) */
function containsNonLatin1(s: string): boolean {
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (cp > 0xff) return true;
  }
  return false;
}

/** True if any line contains a code point > 0xFF */
function textNeedsUnicode(lines: string[]): boolean {
  for (const line of lines) {
    if (containsNonLatin1(line)) return true;
  }
  return false;
}

/** Replace any code point > 0xFF with '?' (for Courier fallback only) */
function stripNonLatin1(s: string): string {
  let out = "";
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    out += cp <= 0xff ? ch : "?";
  }
  return out;
}

/** Per-URL cache */
const fontCache = new Map<string, Uint8Array>();

async function fetchFontBytes(url: string): Promise<Uint8Array> {
  if (fontCache.has(url)) return fontCache.get(url)!;

  const res = await fetch(url, { cache: "force-cache" });
  if (!res.ok) {
    throw new Error(`Font fetch failed: ${res.status} ${res.statusText} (${url})`);
  }
  const buf = await res.arrayBuffer();
  const bytes = new Uint8Array(buf);

  const fmt = sniffFontFormat(bytes);
  if (!fmt) {
    const magic = [...bytes.slice(0, 4)]
      .map(x => x.toString(16).padStart(2, "0"))
      .join(" ");
    throw new Error(
      `Unknown font format (magic ${magic}) from ${url}. Are you loading a real .ttf/.otf?`
    );
  }

  fontCache.set(url, bytes);
  return bytes;
}

async function tryEmbedUnicodeFont(
  doc: PDFDocument,
  urls: string[]
): Promise<{ font: PDFFont | null; url?: string; errorLog: string[] }> {
  const errors: string[] = [];
  for (const url of urls) {
    try {
      const bytes = await fetchFontBytes(url);
      const font = await doc.embedFont(bytes, { subset: false }); // keep full glyph set (Cyrillic)
      return { font, url, errorLog: errors };
    } catch (e: any) {
      errors.push(`${url}: ${e?.message || e}`);
    }
  }
  return { font: null, errorLog: errors };
}

// ---- Main API --------------------------------------------------------------

export async function createSimplePdf(
  lines: string[],
  opts: CreatePdfOpts = {}
): Promise<{ url: string; filename: string }> {
  const {
    title = "Export",
    filename = "export",
    fontUrl,                // optional override
    margin = 48,
    fontSize = 11,
    lineHeight = 14,
    pageWidth = A4.width,
    pageHeight = A4.height,
    monospace = false,
    tabSize = 2,
  } = opts;

  const doc = await PDFDocument.create();
  // @pdf-lib/fontkit has its own types, but cast to any to satisfy TS in some setups
  doc.registerFontkit(fontkit as any);

  // Probe candidate fonts (override first)
  const candidates = fontUrl
    ? [fontUrl, ...DEFAULT_CANDIDATE_FONTS.filter(u => u !== fontUrl)]
    : [...DEFAULT_CANDIDATE_FONTS];

  const normalized = lines.map(normalizeLine);
  const needsUnicode = textNeedsUnicode(normalized);

  let font: PDFFont | null = null;
  let embeddedFrom: string | undefined;
  let usedUnicode = false;

  // Try to embed a Unicode font
  const { font: uFont, url: okUrl, errorLog } = await tryEmbedUnicodeFont(doc, candidates);
  if (uFont) {
    font = uFont;
    usedUnicode = true;
    embeddedFrom = okUrl;
  } else {
    // No custom font embedded → fallback to Courier (Latin)
    font = await doc.embedStandardFont(StandardFonts.Courier);
    usedUnicode = false;

    if (needsUnicode) {
      // Fail fast with a clear message (do not silently print '?')
      const detail = errorLog.length ? `\nTried:\n- ${errorLog.join("\n- ")}` : "";
      throw new Error(
        "[PDF] A Unicode TTF/OTF font could not be embedded, but the text requires Unicode (e.g., Cyrillic).\n" +
          "Add a Cyrillic-capable TTF (e.g., /public/fonts/DejaVuSansMono.ttf) and ensure the URL is correct." +
          detail
      );
    }
  }

  try {
    doc.setTitle(title);
  } catch {
    /* ignore metadata errors */
  }

  // ---- Page + layout helpers ----
  const addPage = () => doc.addPage([pageWidth, pageHeight]);
  let page = addPage();
  const maxWidth = pageWidth - margin * 2;
  let x = margin;
  let y = pageHeight - margin;

  const drawLine = (t: string) => {
    const safe = usedUnicode ? t : stripNonLatin1(t);
    page.drawText(safe.length ? safe : " ", { x, y, size: fontSize, font: font!, color: rgb(0, 0, 0) });
    y -= lineHeight;
  };

  let maxCols = Infinity;
  if (monospace) {
    const colW = Math.max(1, font!.widthOfTextAtSize("M", fontSize));
    maxCols = Math.max(1, Math.floor(maxWidth / colW));
  }

  const addNewPageIfNeeded = () => {
    if (y < margin + lineHeight) {
      page = addPage();
      x = margin;
      y = pageHeight - margin;
    }
  };

  const wrapAndDraw = (raw: string) => {
    let s = normalizeLine(raw);
    if (monospace) s = expandTabs(s, tabSize);

    if (s === "") {
      drawLine("");
      addNewPageIfNeeded();
      return;
    }

    if (monospace) {
      // Fixed-width wrapping by columns
      while (s.length > 0) {
        drawLine(s.slice(0, maxCols));
        s = s.slice(maxCols);
        addNewPageIfNeeded();
      }
      return;
    }

    // Proportional wrapping by measuring width
    while (s.length > 0) {
      let lo = 0,
        hi = s.length,
        fit = 0;
      // Binary search for max slice that fits
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        const w = font!.widthOfTextAtSize(s.slice(0, mid), fontSize);
        if (w <= maxWidth) {
          fit = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      if (fit === 0) fit = 1;

      // Prefer breaking at last space if reasonable
      let split = fit;
      const chunk = s.slice(0, fit);
      const lastSpace = chunk.lastIndexOf(" ");
      if (lastSpace > 0 && chunk.length > 4) split = lastSpace;

      // Avoid splitting before combining mark
      while (split < s.length && isCombining(s[split])) split++;

      drawLine(s.slice(0, split));
      s = s.slice(split).replace(/^\s+/, "");
      addNewPageIfNeeded();
    }
  };

  for (const raw of normalized) {
    addNewPageIfNeeded();
    wrapAndDraw(raw ?? "");
  }

  const bytes = await doc.save();
  const blob = new Blob([bytes], { type: "application/pdf" });
  const outName = `${filename}.pdf`;

  // Helpful one-time log to confirm which font was used
  if (usedUnicode && embeddedFrom) {
    // eslint-disable-next-line no-console
    console.log(`[PDF] Embedded Unicode font: ${embeddedFrom}`);
  }

  return { url: URL.createObjectURL(blob), filename: outName };
}
