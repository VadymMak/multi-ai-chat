
# AI Assistant — Output Modes Refactor Plan (Checklist)

**Goal:** Four canonical output modes (**markdown, plain, code, pdf**) with a clean renderer split, deterministic PDF (Cyrillic-safe), backend normalization, and a small, testable FE surface.

---

## Status Summary (today)

- ✅ Core FE split landed: `MessageRenderer`, `MarkdownView`, `PlainView`, `CodeCard`, refactored `ChatMessageBubble`, tightened `ChatArea` with `useAutoScroll`.
- ✅ InputBar “Fix A”: side‑effect‑free **mode toggles**; Send uses last selected mode; composer text unchanged.
- ✅ Secure attachments: `PdfChip` uses `rel="noopener noreferrer"` and `referrerPolicy="no-referrer"`; attachment links updated similarly.
- ✅ API client normalization: `aiApi.ts` sends render hints (output_mode/presentation) and **consumes** server/legacy fields into a unified `RenderMeta` + sources normalizer.
- ✅ Source cards migrated to `Attachments/SourceList` and rendered **after** the main body.
- ✅ Divider handling: “📌 New Phase Started After Summarization” shown as a centered divider.
- ✅ Backend runtime verified locally (`/docs#/` ok); OPENAI key issue solved; requests now flow.
- ✅ Backend thresholds/memory/logging checks (soft=1500, hard=3000, ~600‑token compact summaries, log lines) — verified via `?debug=1`.
- ⏳ Tests: quick Jest tests still to add.
- ⏳ PDF “server lifecycle” (pdf_status + assets) not implemented — client‑side PDF export is ready, fonts path in place.

---

## 0) Prep & Hygiene
- [x] **Create feature branch:** `feat/output-modes-refactor`
- [x] **Confirm no blockers:** `/api/ask`, `/api/chat/summarize`, `/api/youtube/search` reachable locally
- [ ] **CSS audit (quick):** ensure no global `ul,ol { list-style: none }` leaks into chat bubbles
- [x] **Decide toggle policy:** **respect the user’s choice** of `render.kind`; backend normalizes to match

**Notes:** For CSS, ensure lists inside bubbles rely on Tailwind (`list-disc list-inside`) and that no globals strip bullets/numbers.

---

## 1) Folder & File Structure (created)
**Components (new)**
- [x] `src/components/Renderers/MessageRenderer.tsx` *(facade / orchestrator)*
- [x] `src/components/Renderers/MarkdownView.tsx`
- [x] `src/components/Renderers/PlainView.tsx`
- [x] `src/components/Renderers/CodeCard.tsx`
- [x] `src/components/Attachments/PdfChip.tsx`
- [x] `src/components/Attachments/SourceList.tsx` *(moved from Shared)*
- [x] `src/components/Chat/TypingIndicator.tsx` *(already existed)*

**Hooks & Utils**
- [x] `src/hooks/useAutoScroll.ts` *(already existed & integrated)*
- [x] `src/utils/renderKinds.ts` *(types, guards, registry mapping)*

**Touch points (refactored)**
- [x] `src/components/Chat/ChatMessageBubble.tsx` → uses `MessageRenderer`, streaming split preserved
- [x] `src/components/Chat/ChatArea.tsx` → anchor logic + IntersectionObserver; divider handling
- [x] `src/pages/ChatPage.tsx` → prefers `overrides.kind` on send; session restore & history load
- [x] `src/components/Chat/InputBar.tsx` → **Fix A** toggles; drop/paste upload respects overrides

---

## 2) Backend Contract & Normalization
**Request/Response contract (client side in place)**
- [x] Request includes **render hints** via `output_mode`/`presentation` (derived from `RenderKind`).
- [x] Client reads response variations: `render.kind|type|output_mode|presentation|language|filename` → normalized.
- [x] Client consumes `sources` or legacy `youtube/web` arrays.

**Normalization rules (server-side) — desired**
- [ ] **markdown:** GFM only, sanitize links, strip raw HTML
- [ ] **plain:** remove markdown adorners; preserve newlines
- [ ] **code:** enforce exactly one code block; infer `language`/`filename`; cap length
- [ ] **pdf:** never ask LLM for PDF; deterministically convert our `text` to PDF

**Observability**
- [x] Client logs/phases; error descriptions improved
- [ ] Server returns `{ ttfb_ms, ttlb_ms, input_tokens, output_tokens, summarized, rotated }`

**Acceptance**
- [ ] Sample curl per mode shows proper `render.requested/applied`, `content_type`, `assets[]` and normalized output

---

## 3) PDF Reliability (Cyrillic hard guarantees)
- [x] **Client PDFs:** `createSimplePdf` wired (Noto Sans/Mono paths via `/public/fonts`). `CodeBlock` “Export as PDF” + `/pdf` command → chip/download.
- [ ] **Server PDFs:** embed fonts + deterministic pipeline (`text → md/html → pdf`), `pdf_status` field, asset size.
- [ ] **Unicode cmap:** verify copy/paste preserves Cyrillic (server PDF).
- [ ] **Layout defaults:** A4, margins, base font size/line height; long‑word/code wrapping.
- [ ] **Async lifecycle:** `pending→ready/error`; `assets[]` when ready.

**Acceptance**
- [ ] One Russian page renders perfectly; round‑trip copy/paste equals source.

---

## 4) InputBar (Fix A) — Side‑effect‑free Mode Toggles
- [x] Mode buttons **only** toggle local `render.kind`
- [x] Toggles **do not send** and **do not mutate** composer text
- [x] Send uses **last selected** mode; composer clears; focus returns to textarea

**Jest (to add)**
```ts
// InputBar.test.tsx
// ...from the plan — verifies toggles don’t send or rewrite, Send honors mode
```

---

## 5) Renderer Split — Primary Views

### 5.1 MarkdownView
- [x] Semantic lists/tables; safe links; compact spacing
- [x] Split‑while‑streaming (prose fast; code appears as fence opens)

**Acceptance (manual)**: H2 + bullets + ordered list + fenced code + table render correctly; DOM shows real `<ul>/<ol>/<li>`.

### 5.2 PlainView
- [x] No adorners (bullets/numbers/backticks removed)
- [x] Newlines preserved; poem is a **presentation** flag

### 5.3 CodeCard
- [x] Exactly one code block; `language` + optional `filename`
- [x] Scroll for long code; copy/download/export‑pdf actions

---

## 6) Attachments & Orchestration

### 6.1 PdfChip
- [x] Shows `pending/ready/error`
- [x] Secure download: `rel="noopener noreferrer"` and `referrerPolicy="no-referrer"`

### 6.2 SourceList (YouTube/Web)
- [x] Renders after the body; safe link attrs; no duplicates when server de‑dupes

### 6.3 MessageRenderer (facade)
- [x] Reads normalized render meta + sources + attachments
- [x] Renders **one primary** view + attachments in stable order

---

## 7) Chat Integration & UX Polish
- [x] **ChatMessageBubble** uses `MessageRenderer`; streaming stays smooth
- [x] **ChatArea** uses `useAutoScroll` (pinned during stream; smooth on finalize)
- [x] **Rotation UX**: server divider recognized; `chat_session_id` adoption wired in `ChatPage`/`aiApi`

**Acceptance**: Smooth streaming, no jumps; divider appears once; session id updates as returned.

---

## 8) Minimal Test Pass (now)
- [ ] **Mode toggles:** no send / no text mutation; Send honors selected mode
- [ ] **Markdown smoke:** H2 + bullets + ordered list + fenced code + table (semantic DOM)
- [ ] **Plain:** no adorners; newlines preserved
- [ ] **Code:** single code card; correct language/filename
- [ ] **PDF (Cyrillic):** client PDF generated; copy/paste preserves Cyrillic glyphs
- [ ] **Sources after text:** safe links; no dupes

---

## 9) Telemetry & Compliance
- [ ] Server logs: `{ render.requested, render.applied, compliance, fixups[], ttfb_ms, ttlb_ms, tokens }`
- [ ] Track `pdf_status` timings and asset size
- [ ] Keep 1–2 **golden prompts** per mode (incl. Russian lines)

---

## 10) Rollout & Safety
- [ ] (Optional) Feature flag for new renderer
- [ ] Idempotent message storage intact
- [ ] Commit message:
  ```
  feat(render): split by mode (markdown/plain/code/pdf) with facade; deterministic PDF (Cyrillic-safe)
  refactor(input): side-effect-free output-mode toggles
  chore(obs): render compliance, pdf_status, metrics
  ```

**Definition of Done**
- [ ] Four modes render reliably with clear separation of concerns
- [ ] PDF generation deterministic and Cyrillic-safe
- [ ] No layout jumps; smooth streaming; rotation divider correct
- [ ] Minimal test pass green; logs/metrics trustworthy

---

## Tomorrow’s Test Plan (A–F)

**A) Mode toggles do not send / do not mutate composer**  
- Focus textarea, type: `this should stay here`  
- Click modes: MD → Plain → Code → Poem-plain → Poem-code  
- Expect: no message sent; text unchanged; only active button flips.  
- Press Send once → latest assistant `render.kind` equals last selected.

**B) Markdown rendering (lists / tables / spacing)**  
Paste and send:
```md
## H2 One

This is a short sentence.

- bullet one
- bullet two
- bullet three

1. step one
2. step two

```python filename=main.py
def greet_user(name):
    return f"Hello, {name}!"
```
| Header 1 | Header 2 | Header 3 |
|---------:|:--------:|----------|
| Cell 1   | Cell 2   | Cell 3   |
```
Pass: H2 styled; bullets/numbers visible; code card shows `main.py`; table as GFM with borders.

**C) Plain / Poem-plain (no adorners)**  
Plain mode — send exactly:
```
bullet one

step one
inline `tick` here
```
Pass: plain lines; no bullets/numbers; backticks removed; line breaks preserved.

**D) Code / Poem-code (single block)**  
Code mode — send only:
````
```ts filename=hello.ts
export const hi = (n: string) => `hi ${n}`;
```
````
Pass: a single `CodeCard`, correct language+filename, no extra prose.

**E) DevTools DOM checks**  
Semantic `<ul>/<ol>/<li>`; links have `target="_blank"` + `rel="noopener noreferrer nofollow"`.

**F) Streaming split checks**  
Ask for prose + fenced block in MD mode. Pass: prose renders immediately; code appears as the fence opens; no layout jump at finalize.

---

## Backend Token/Memory/Logging — Acceptance (verified)

- ✅ **Settings/Thresholds** — `SOFT_TOKEN_LIMIT=1500`, `HARD_TOKEN_LIMIT=3000`, per‑model override path present.  
- ✅ **Memory utils** — compact autosummaries ~600 tokens, prioritize code/requirements signals.  
- ✅ **Logging** — emits `[Token Preflight] total=X` and `[Summarization] compressed X→Y` during soft/hard flows.

**How to re‑check quickly (Swagger + `?debug=1`):**
1) Call `POST /api/ask?debug=1` with short prompt → expect `debug.thresholds.soft === 1500`, `hard === 3000`; `near_soft=false`, `over_hard=false`.
2) Build history and call `POST /api/ask?debug=1` → soft path: `rotated=false`, `divider_message` stored, `debug.summarized=true`, `debug.summary_tokens ≲ 650`.  
   For hard path: `rotated=true`, `new_chat_session_id` present, divider saved to old session.
3) Check server logs:  
   `[Token Preflight] total=XXXX (soft=1500, hard=3000)` and  
   `[Summarization] compressed 12,345→598 tokens` + audit events.

---

## Next Steps (shortlist)

1) ✅ FE split complete — **ship behind a flag (optional)**.  
2) ⏳ Add Jest test A (mode toggles) + smoke tests for MD/Plain/Code.  
3) ⏳ Server PDF lifecycle (`pdf_status`, `assets[]`, font embedding).  
4) ⏳ CSS audit: ensure no global list resets leak into bubbles.  
5) ⏳ Telemetry payloads from server (ttfb/ttlb/tokens/compliance).

