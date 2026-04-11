import * as vscode from 'vscode';
import * as https from 'https';
import * as http from 'http';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

interface Suggestion {
  type: 'pattern' | 'similar_code' | 'warning' | 'related';
  message: string;
  related_file?: string;
  related_snippet?: string;
  confidence: number;
  line?: number;
}

interface ActiveSuggestionResponse {
  success: boolean;
  suggestions: Suggestion[];
  query_used: string;
  search_ms?: number;
}

// ─────────────────────────────────────────────
// State
// ─────────────────────────────────────────────

let statusBarItem: vscode.StatusBarItem;
let panel: vscode.WebviewPanel | undefined;
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
let lastSuggestions: Suggestion[] = [];
let enabled = true;

let diagnosticDebounce: ReturnType<typeof setTimeout> | undefined;
const reportedErrors = new Set<string>();

// ─────────────────────────────────────────────
// Activation
// ─────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext) {
  // Status bar
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = 'smartcontext.showPanel';
  statusBarItem.text = '$(brain) Brain';
  statusBarItem.tooltip = 'SmartContext: Active Suggestions';
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand('smartcontext.toggleSuggestions', toggleSuggestions),
    vscode.commands.registerCommand('smartcontext.showPanel', () => showPanel(context)),
  );

  // Listen to text changes
  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument(onTextChange),
    vscode.window.onDidChangeActiveTextEditor(onEditorChange),
    vscode.languages.onDidChangeDiagnostics(onDiagnosticsChange),
  );

  // Run once for the current editor
  if (vscode.window.activeTextEditor) {
    scheduleFetch(vscode.window.activeTextEditor);
  }
}

export function deactivate() {
  panel?.dispose();
}

// ─────────────────────────────────────────────
// Event handlers
// ─────────────────────────────────────────────

function onTextChange(e: vscode.TextDocumentChangeEvent) {
  if (!enabled) return;
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document !== e.document) return;
  scheduleFetch(editor);
}

function onEditorChange(editor: vscode.TextEditor | undefined) {
  if (!enabled || !editor) return;
  scheduleFetch(editor);
}

function onDiagnosticsChange(e: vscode.DiagnosticChangeEvent) {
  if (diagnosticDebounce) clearTimeout(diagnosticDebounce);
  diagnosticDebounce = setTimeout(() => reportErrors(e.uris), 3000);
}

async function reportErrors(uris: readonly vscode.Uri[]) {
  const cfg = getConfig();
  if (!cfg.apiToken || !cfg.projectId) return;

  for (const uri of uris) {
    const diagnostics = vscode.languages.getDiagnostics(uri);
    const errors = diagnostics.filter(
      d => d.severity === vscode.DiagnosticSeverity.Error,
    );

    for (const diag of errors.slice(0, 3)) {
      const key = `${uri.fsPath}:${diag.range.start.line}:${diag.message}`;
      if (reportedErrors.has(key)) continue;
      reportedErrors.add(key);

      const errorCode = diag.code === undefined ? undefined
        : typeof diag.code === 'object' ? String(diag.code.value)
        : String(diag.code);

      const body = JSON.stringify({
        project_id: cfg.projectId,
        error_pattern: diag.message.slice(0, 500),
        error_type: classifyErrorType(diag),
        error_code: errorCode,
        file_path: vscode.workspace.asRelativePath(uri),
        line_number: diag.range.start.line + 1,
      });

      // Fire and forget — never surface failures to the user
      post<unknown>(`${cfg.apiUrl}/vscode/report-error`, body, cfg.apiToken)
        .catch(() => {});
    }
  }

  // Prevent unbounded growth
  if (reportedErrors.size > 500) reportedErrors.clear();
}

function classifyErrorType(diag: vscode.Diagnostic): string {
  const src = (diag.source ?? '').toLowerCase();
  const msg = diag.message.toLowerCase();

  if (src === 'eslint' || src === 'stylelint') return 'lint';
  if (msg.includes('cannot find module') || msg.includes('has no exported member')) return 'import';
  if (src === 'ts' || src === 'typescript') return 'type';
  if (msg.includes('syntax') || msg.includes('unexpected token')) return 'syntax';
  return 'runtime';
}

function scheduleFetch(editor: vscode.TextEditor) {
  const cfg = getConfig();
  if (!cfg.apiToken || !cfg.projectId) return;

  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => fetchSuggestions(editor), cfg.debounceMs);
}

// ─────────────────────────────────────────────
// Core fetch
// ─────────────────────────────────────────────

async function fetchSuggestions(editor: vscode.TextEditor) {
  const cfg = getConfig();
  if (!cfg.enabled || !cfg.apiToken || !cfg.projectId) {
    setStatus('$(brain) Brain', 'Configure SmartContext: set apiToken and projectId');
    return;
  }

  const doc = editor.document;
  const cursorLine = editor.selection.active.line;
  const fileContent = doc.getText();
  const filePath = vscode.workspace.asRelativePath(doc.uri);

  setStatus('$(sync~spin) Brain…', 'Fetching suggestions…');

  try {
    const body = JSON.stringify({
      project_id: cfg.projectId,
      file_path: filePath,
      file_content: fileContent,
      cursor_line: cursorLine,
      language: doc.languageId,
    });

    const data = await post<ActiveSuggestionResponse>(
      `${cfg.apiUrl}/vscode/active-suggestions`,
      body,
      cfg.apiToken,
    );

    if (!data.success) {
      setStatus('$(brain) Brain', 'No suggestions');
      return;
    }

    lastSuggestions = data.suggestions;
    const count = data.suggestions.length;
    const hasWarning = data.suggestions.some(s => s.type === 'warning');

    if (count === 0) {
      setStatus('$(brain) Brain', 'No suggestions');
    } else if (hasWarning) {
      setStatus(`$(warning) Brain ${count}`, `${count} suggestion(s) — click to view`);
    } else {
      setStatus(`$(lightbulb) Brain ${count}`, `${count} suggestion(s) — click to view`);
    }

    // If panel is open, refresh it
    if (panel) {
      panel.webview.html = buildPanelHtml(lastSuggestions);
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    setStatus('$(error) Brain', `Error: ${msg}`);
  }
}

// ─────────────────────────────────────────────
// Panel
// ─────────────────────────────────────────────

function showPanel(context: vscode.ExtensionContext) {
  if (panel) {
    panel.reveal(vscode.ViewColumn.Beside);
    panel.webview.html = buildPanelHtml(lastSuggestions);
    return;
  }

  panel = vscode.window.createWebviewPanel(
    'smartcontextBrain',
    'Brain Suggestions',
    vscode.ViewColumn.Beside,
    { enableScripts: false },
  );

  panel.webview.html = buildPanelHtml(lastSuggestions);

  panel.onDidDispose(() => { panel = undefined; }, null, context.subscriptions);
}

function buildPanelHtml(suggestions: Suggestion[]): string {
  const rows = suggestions.length === 0
    ? '<p class="empty">No suggestions yet. Start typing…</p>'
    : suggestions.map(s => {
        const icon = s.type === 'warning' ? '⚠️'
          : s.type === 'similar_code' ? '🔍'
          : s.type === 'pattern' ? '📐'
          : '💡';
        const pct = Math.round(s.confidence * 100);
        const file = s.related_file ? `<div class="file">📄 ${s.related_file}</div>` : '';
        const snippet = s.related_snippet
          ? `<pre class="snippet">${escHtml(s.related_snippet.slice(0, 300))}</pre>`
          : '';
        return `
          <div class="card ${s.type}">
            <div class="header">
              <span class="icon">${icon}</span>
              <span class="message">${escHtml(s.message)}</span>
              <span class="badge">${pct}%</span>
            </div>
            ${file}${snippet}
          </div>`;
      }).join('');

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: var(--vscode-font-family); font-size: 13px;
         background: var(--vscode-editor-background);
         color: var(--vscode-editor-foreground); padding: 12px; margin: 0; }
  h2 { font-size: 14px; margin: 0 0 12px; opacity: .7; }
  .empty { opacity: .5; font-style: italic; }
  .card { border: 1px solid var(--vscode-panel-border);
          border-radius: 6px; padding: 10px 12px; margin-bottom: 10px; }
  .card.warning { border-color: #e8a838; }
  .card.similar_code { border-color: #4a90d9; }
  .card.pattern { border-color: #6da77c; }
  .header { display: flex; align-items: flex-start; gap: 8px; }
  .icon { font-size: 16px; line-height: 1; flex-shrink: 0; }
  .message { flex: 1; line-height: 1.4; }
  .badge { font-size: 11px; opacity: .6; white-space: nowrap; }
  .file { margin-top: 6px; font-size: 11px; opacity: .6; }
  .snippet { margin: 8px 0 0; padding: 8px;
             background: var(--vscode-textBlockQuote-background);
             border-radius: 4px; font-size: 11px; white-space: pre-wrap;
             overflow: hidden; max-height: 120px; }
</style>
</head>
<body>
<h2>🧠 Brain Suggestions</h2>
${rows}
</body>
</html>`;
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

function toggleSuggestions() {
  enabled = !enabled;
  vscode.window.showInformationMessage(
    `SmartContext suggestions ${enabled ? 'enabled' : 'disabled'}`,
  );
  if (!enabled) setStatus('$(brain) Brain [off]', 'Active suggestions disabled');
}

function setStatus(text: string, tooltip: string) {
  statusBarItem.text = text;
  statusBarItem.tooltip = tooltip;
}

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('smartcontext');
  return {
    apiUrl:     cfg.get<string>('apiUrl', 'http://localhost:8000').replace(/\/$/, ''),
    apiToken:   cfg.get<string>('apiToken', ''),
    projectId:  cfg.get<number>('projectId', 0),
    debounceMs: cfg.get<number>('debounceMs', 1500),
    enabled:    cfg.get<boolean>('enabled', true),
  };
}

function escHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function post<T>(url: string, body: string, token: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const isHttps = parsed.protocol === 'https:';
    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'Authorization': `Bearer ${token}`,
      },
    };

    const req = (isHttps ? https : http).request(options, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 200)}`));
          return;
        }
        try { resolve(JSON.parse(data) as T); }
        catch (e) { reject(new Error(`Invalid JSON: ${data.slice(0, 100)}`)); }
      });
    });

    req.on('error', reject);
    req.setTimeout(8000, () => { req.destroy(); reject(new Error('Request timeout')); });
    req.write(body);
    req.end();
  });
}
