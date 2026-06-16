"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const https = __importStar(require("https"));
const http = __importStar(require("http"));
// ─────────────────────────────────────────────
// State
// ─────────────────────────────────────────────
let diagnosticDebounce;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let activityDebounce;
const reportedErrors = new Set();
// ─────────────────────────────────────────────
// Activation — silent, no UI
// ─────────────────────────────────────────────
function activate(context) {
    context.subscriptions.push(vscode.languages.onDidChangeDiagnostics(onDiagnosticsChange), vscode.window.onDidChangeActiveTextEditor(onActiveEditorChange), vscode.workspace.onDidSaveTextDocument(onDidSaveDocument));
    // Report whatever is already open on activation
    const editor = vscode.window.activeTextEditor;
    if (editor)
        scheduleActivityReport(editor.document);
}
function deactivate() { }
// ─────────────────────────────────────────────
// Activity tracking — report current open file
// ─────────────────────────────────────────────
function onActiveEditorChange(editor) {
    if (!editor)
        return;
    scheduleActivityReport(editor.document);
}
function onDidSaveDocument(doc) {
    scheduleActivityReport(doc);
}
function scheduleActivityReport(doc) {
    if (activityDebounce)
        clearTimeout(activityDebounce);
    activityDebounce = setTimeout(() => reportActivity(doc), 5000);
}
async function reportActivity(doc) {
    const cfg = getConfig();
    if (!cfg.apiUrl || !cfg.apiToken)
        return;
    const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
    const projectId = folder ? getProjectId(doc.uri) : null;
    const folderIdentifier = folder ? folder.name.slice(0, 64) : null;
    const filePath = vscode.workspace.asRelativePath(doc.uri);
    const language = doc.languageId;
    const body = JSON.stringify({
        project_id: projectId,
        folder_identifier: folderIdentifier,
        file_path: filePath,
        language,
    });
    // Fire and forget — never surfaces failures to the user
    post(`${cfg.apiUrl}/vscode/activity`, body, cfg.apiToken).catch(() => { });
}
// ─────────────────────────────────────────────
// Diagnostics listener
// ─────────────────────────────────────────────
function onDiagnosticsChange(e) {
    if (diagnosticDebounce)
        clearTimeout(diagnosticDebounce);
    diagnosticDebounce = setTimeout(() => reportErrors(e.uris), 3000);
}
async function reportErrors(uris) {
    const cfg = getConfig();
    if (!cfg.apiUrl || !cfg.apiToken)
        return;
    for (const uri of uris) {
        const projectId = getProjectId(uri);
        if (!projectId)
            continue;
        const diagnostics = vscode.languages.getDiagnostics(uri);
        const errors = diagnostics.filter(d => d.severity === vscode.DiagnosticSeverity.Error);
        for (const diag of errors.slice(0, 3)) {
            const key = `${uri.fsPath}:${diag.range.start.line}:${diag.message}`;
            if (reportedErrors.has(key))
                continue;
            reportedErrors.add(key);
            const errorCode = diag.code === undefined
                ? undefined
                : typeof diag.code === 'object'
                    ? String(diag.code.value)
                    : String(diag.code);
            const body = JSON.stringify({
                project_id: projectId,
                error_pattern: diag.message.slice(0, 500),
                error_type: classifyErrorType(diag),
                error_code: errorCode,
                file_path: vscode.workspace.asRelativePath(uri),
                line_number: diag.range.start.line + 1,
            });
            // Fire and forget — never surfaces failures to the user
            post(`${cfg.apiUrl}/vscode/report-error`, body, cfg.apiToken)
                .catch(() => { });
        }
    }
    // Prevent unbounded growth
    if (reportedErrors.size > 500)
        reportedErrors.clear();
}
// ─────────────────────────────────────────────
// Project ID from .smartcontext.json
// ─────────────────────────────────────────────
function getProjectId(uri) {
    const folder = vscode.workspace.getWorkspaceFolder(uri);
    if (!folder)
        return null;
    const configPath = path.join(folder.uri.fsPath, '.smartcontext.json');
    try {
        const raw = fs.readFileSync(configPath, 'utf8');
        const data = JSON.parse(raw);
        if (typeof data.project_id === 'number' && data.project_id > 0) {
            return data.project_id;
        }
    }
    catch {
        // No .smartcontext.json or invalid JSON — silently skip this workspace
    }
    return null;
}
// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────
function classifyErrorType(diag) {
    const src = (diag.source ?? '').toLowerCase();
    const msg = diag.message.toLowerCase();
    if (src === 'eslint' || src === 'stylelint')
        return 'lint';
    if (msg.includes('cannot find module') || msg.includes('has no exported member'))
        return 'import';
    if (src === 'ts' || src === 'typescript')
        return 'type';
    if (msg.includes('syntax') || msg.includes('unexpected token'))
        return 'syntax';
    return 'runtime';
}
function getConfig() {
    const cfg = vscode.workspace.getConfiguration('smartcontext');
    return {
        apiUrl: cfg.get('apiUrl', '').replace(/\/$/, ''),
        apiToken: cfg.get('apiToken', ''),
    };
}
function post(url, body, token) {
    return new Promise((resolve, reject) => {
        const parsed = new URL(url);
        const isHttps = parsed.protocol === 'https:';
        const options = {
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
                    reject(new Error(`HTTP ${res.statusCode}`));
                    return;
                }
                try {
                    resolve(JSON.parse(data));
                }
                catch {
                    reject(new Error('Invalid JSON'));
                }
            });
        });
        req.on('error', reject);
        req.setTimeout(8000, () => { req.destroy(); reject(new Error('timeout')); });
        req.write(body);
        req.end();
    });
}
//# sourceMappingURL=extension.js.map