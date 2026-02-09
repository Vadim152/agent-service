import { createServer as createHttpServer } from "node:http";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { URL } from "node:url";

import { createOpencodeClient } from "@opencode-ai/sdk/client";

const WRAPPER_HOST = process.env.OPENCODE_WRAPPER_HOST ?? "127.0.0.1";
const WRAPPER_PORT = Number.parseInt(process.env.OPENCODE_WRAPPER_PORT ?? "8011", 10);
const OPENCODE_HOST = process.env.OPENCODE_HOST ?? "127.0.0.1";
const OPENCODE_PORT = Number.parseInt(process.env.OPENCODE_PORT ?? "4096", 10);
const OPENCODE_TIMEOUT_MS = Number.parseInt(
  process.env.OPENCODE_STARTUP_TIMEOUT_MS ?? "15000",
  10,
);
const OPENCODE_BIN = process.env.OPENCODE_BIN?.trim() || null;

function nowIso() {
  return new Date().toISOString();
}

function toIso(timestamp) {
  if (typeof timestamp !== "number") {
    return nowIso();
  }
  return new Date(timestamp).toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startOpencodeRuntime() {
  const candidates = [];
  if (OPENCODE_BIN) {
    candidates.push(OPENCODE_BIN);
  }
  if (process.platform === "win32") {
    candidates.push("opencode.cmd");
  }
  candidates.push("opencode");

  const envPathPrefix = process.platform === "win32" ? `${process.env.APPDATA}\\npm` : "";
  const mergedPath = envPathPrefix
    ? `${envPathPrefix}${process.platform === "win32" ? ";" : ":"}${process.env.PATH ?? ""}`
    : process.env.PATH;

  let lastError = null;
  for (const bin of candidates) {
    try {
      const runtime = await new Promise((resolve, reject) => {
        const args = ["serve", `--hostname=${OPENCODE_HOST}`, `--port=${OPENCODE_PORT}`];
        const proc = spawn(bin, args, {
          env: {
            ...process.env,
            PATH: mergedPath,
          },
          shell: process.platform === "win32",
        });
        let output = "";
        const timeoutId = setTimeout(() => {
          proc.kill();
          reject(
            new Error(`Timeout waiting for opencode runtime after ${OPENCODE_TIMEOUT_MS}ms`),
          );
        }, OPENCODE_TIMEOUT_MS);

        proc.stdout?.on("data", (chunk) => {
          output += chunk.toString();
          const lines = output.split("\n");
          for (const line of lines) {
            if (line.startsWith("opencode server listening")) {
              const match = line.match(/on\s+(https?:\/\/[^\s]+)/);
              if (!match) {
                continue;
              }
              clearTimeout(timeoutId);
              resolve({
                url: match[1],
                close() {
                  proc.kill();
                },
              });
              return;
            }
          }
        });

        proc.stderr?.on("data", (chunk) => {
          output += chunk.toString();
        });

        proc.on("exit", (code) => {
          clearTimeout(timeoutId);
          reject(new Error(`opencode exited with code ${code}\n${output}`));
        });

        proc.on("error", (error) => {
          clearTimeout(timeoutId);
          reject(error);
        });
      });
      return runtime;
    } catch (error) {
      lastError = error;
      if (error?.code !== "ENOENT") {
        break;
      }
    }
  }
  throw lastError ?? new Error("Unable to start opencode runtime");
}

function toNumber(value, fallback = 0) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function writeJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

async function readBodyJson(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.from(chunk));
  }
  if (!chunks.length) {
    return {};
  }
  const raw = Buffer.concat(chunks).toString("utf-8");
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("Invalid JSON body");
  }
}

function parseSessionId(rawEvent) {
  if (!rawEvent || typeof rawEvent !== "object") {
    return null;
  }
  const properties = rawEvent.properties ?? {};
  if (typeof properties.sessionID === "string") {
    return properties.sessionID;
  }
  if (typeof properties?.info?.sessionID === "string") {
    return properties.info.sessionID;
  }
  if (typeof properties?.part?.sessionID === "string") {
    return properties.part.sessionID;
  }
  return null;
}

function messageContent(parts) {
  if (!Array.isArray(parts)) {
    return "";
  }
  const textChunks = [];
  for (const part of parts) {
    if (part?.type === "text" && typeof part.text === "string") {
      textChunks.push(part.text);
    }
    if (part?.type === "reasoning" && typeof part.text === "string") {
      textChunks.push(part.text);
    }
  }
  return textChunks.join("\n").trim();
}

function createEmptyTotals() {
  return {
    tokens: {
      input: 0,
      output: 0,
      reasoning: 0,
      cacheRead: 0,
      cacheWrite: 0,
    },
    cost: 0,
  };
}

const sessionState = new Map();
const sessionsByProject = new Map();
const eventsBySession = new Map();
const pendingPermissionsBySession = new Map();
const usageByMessageBySession = new Map();
const watchersByProject = new Map();

let opencodeRuntime = null;
let opencodeClient = null;

function ensureSessionEventLog(sessionId) {
  if (!eventsBySession.has(sessionId)) {
    eventsBySession.set(sessionId, []);
  }
  return eventsBySession.get(sessionId);
}

function ensurePendingPermissions(sessionId) {
  if (!pendingPermissionsBySession.has(sessionId)) {
    pendingPermissionsBySession.set(sessionId, new Map());
  }
  return pendingPermissionsBySession.get(sessionId);
}

function ensureMessageUsageMap(sessionId) {
  if (!usageByMessageBySession.has(sessionId)) {
    usageByMessageBySession.set(sessionId, new Map());
  }
  return usageByMessageBySession.get(sessionId);
}

function appendEvent(sessionId, eventType, payload) {
  const eventLog = ensureSessionEventLog(sessionId);
  const event = {
    eventType,
    payload: payload ?? {},
    createdAt: nowIso(),
    index: eventLog.length,
  };
  eventLog.push(event);
  return event;
}

function getSessionOrThrow(sessionId) {
  const session = sessionState.get(sessionId);
  if (!session) {
    const error = new Error(`Session not found: ${sessionId}`);
    error.statusCode = 404;
    throw error;
  }
  return session;
}

function setSessionActivity(session, activity, currentAction) {
  session.activity = activity;
  if (typeof currentAction === "string" && currentAction.trim()) {
    session.currentAction = currentAction.trim();
  }
  session.updatedAt = nowIso();
}

function clearRetryState(session) {
  session.lastRetryMessage = null;
  session.lastRetryAttempt = null;
  session.lastRetryAt = null;
}

function recalculateTotals(sessionId) {
  const usageMap = ensureMessageUsageMap(sessionId);
  const totals = createEmptyTotals();
  for (const usage of usageMap.values()) {
    totals.cost += toNumber(usage.cost, 0);
    totals.tokens.input += toNumber(usage.tokens?.input, 0);
    totals.tokens.output += toNumber(usage.tokens?.output, 0);
    totals.tokens.reasoning += toNumber(usage.tokens?.reasoning, 0);
    totals.tokens.cacheRead += toNumber(usage.tokens?.cacheRead, 0);
    totals.tokens.cacheWrite += toNumber(usage.tokens?.cacheWrite, 0);
  }
  return totals;
}

function applyAssistantUsageFromMessageInfo(session, info) {
  if (!info || typeof info !== "object" || info.role !== "assistant") {
    return;
  }
  const messageId = String(info.id ?? "");
  if (!messageId) {
    return;
  }
  const tokens = info.tokens ?? {};
  const usageMap = ensureMessageUsageMap(session.sessionId);
  usageMap.set(messageId, {
    cost: toNumber(info.cost, 0),
    tokens: {
      input: toNumber(tokens.input, 0),
      output: toNumber(tokens.output, 0),
      reasoning: toNumber(tokens.reasoning, 0),
      cacheRead: toNumber(tokens?.cache?.read, 0),
      cacheWrite: toNumber(tokens?.cache?.write, 0),
    },
  });
  session.totals = recalculateTotals(session.sessionId);
  const contextLimit = toNumber(info?.model?.limit?.context, 0);
  if (contextLimit > 0) {
    session.contextWindow = contextLimit;
  }
}

function handlePermissionUpdated(permission) {
  const sessionId = permission?.sessionID;
  const permissionId = permission?.id;
  if (typeof sessionId !== "string" || typeof permissionId !== "string") {
    return;
  }
  const pending = ensurePendingPermissions(sessionId);
  pending.set(permissionId, {
    permissionId,
    title: String(permission?.title ?? "Approval required"),
    kind: String(permission?.type ?? "unknown"),
    callId: permission?.callID ?? null,
    messageId: permission?.messageID ?? null,
    metadata: permission?.metadata ?? {},
    createdAt: toIso(permission?.time?.created),
  });
  const session = sessionState.get(sessionId);
  if (session) {
    setSessionActivity(session, "waiting_permission", `Waiting approval: ${permission.title ?? permissionId}`);
  }
}

function handlePermissionReplied(payload) {
  const sessionId = payload?.sessionID;
  const permissionId = payload?.permissionID;
  if (typeof sessionId !== "string" || typeof permissionId !== "string") {
    return;
  }
  const pending = ensurePendingPermissions(sessionId);
  pending.delete(permissionId);
  const session = sessionState.get(sessionId);
  if (session && pending.size === 0 && session.activity === "waiting_permission") {
    setSessionActivity(session, "busy", "Continuing after approval");
  }
}

function handleSessionStatus(payload) {
  const sessionId = payload?.sessionID;
  const status = payload?.status;
  if (typeof sessionId !== "string" || !status || typeof status !== "object") {
    return;
  }
  const session = sessionState.get(sessionId);
  if (!session) {
    return;
  }
  const type = String(status.type ?? "idle");
  if (type === "busy") {
    clearRetryState(session);
    setSessionActivity(session, "busy", "Processing request");
    return;
  }
  if (type === "retry") {
    const attempt = toNumber(status.attempt, 0);
    const message = typeof status.message === "string" ? status.message : "Retrying";
    session.lastRetryMessage = message;
    session.lastRetryAttempt = attempt;
    session.lastRetryAt = nowIso();
    setSessionActivity(session, "retry", `${message} (attempt ${attempt})`);
    return;
  }
  clearRetryState(session);
  setSessionActivity(session, "idle", "Idle");
}

function handleMessageUpdated(payload) {
  const info = payload?.info;
  if (!info || typeof info !== "object") {
    return;
  }
  const sessionId = info.sessionID;
  if (typeof sessionId !== "string") {
    return;
  }
  const session = sessionState.get(sessionId);
  if (!session) {
    return;
  }
  applyAssistantUsageFromMessageInfo(session, info);
  if (info.error) {
    setSessionActivity(session, "error", String(info.error?.data?.message ?? "Message failed"));
    return;
  }
  if (info.role === "assistant") {
    const completed = Boolean(info?.time?.completed);
    setSessionActivity(session, completed ? "idle" : "busy", completed ? "Idle" : "Generating answer");
  }
}

function handleMessagePartUpdated(payload) {
  const part = payload?.part;
  if (!part || typeof part !== "object") {
    return;
  }
  const sessionId = part.sessionID;
  if (typeof sessionId !== "string") {
    return;
  }
  const session = sessionState.get(sessionId);
  if (!session) {
    return;
  }
  if (part.type === "tool") {
    const toolName = String(part.tool ?? "tool");
    const toolState = String(part?.state?.status ?? "pending");
    if (toolState === "error") {
      setSessionActivity(session, "error", `${toolName} failed`);
      return;
    }
    if (toolState === "completed") {
      setSessionActivity(session, "busy", `${toolName} completed`);
      return;
    }
    setSessionActivity(session, "busy", `${toolName}: ${toolState}`);
    return;
  }
  if (part.type === "compaction") {
    setSessionActivity(session, "busy", "Compacting context");
  }
}

function handleRawEvent(rawEvent) {
  const eventType = String(rawEvent?.type ?? "event.unknown");
  const payload = rawEvent?.properties ?? {};
  const sessionId = parseSessionId(rawEvent);

  if (eventType === "permission.updated") {
    handlePermissionUpdated(payload);
  } else if (eventType === "permission.replied") {
    handlePermissionReplied(payload);
  } else if (eventType === "session.status") {
    handleSessionStatus(payload);
  } else if (eventType === "message.updated") {
    handleMessageUpdated(payload);
  } else if (eventType === "message.part.updated") {
    handleMessagePartUpdated(payload);
  } else if (eventType === "session.idle") {
    const state = sessionState.get(payload?.sessionID ?? "");
    if (state) {
      setSessionActivity(state, "idle", "Idle");
    }
  } else if (eventType === "session.compacted") {
    const state = sessionState.get(payload?.sessionID ?? "");
    if (state) {
      setSessionActivity(state, "idle", "Context compacted");
    }
  } else if (eventType === "session.error") {
    const state = sessionState.get(payload?.sessionID ?? "");
    if (state) {
      const message = String(payload?.error?.data?.message ?? "Session error");
      setSessionActivity(state, "error", message);
    }
  }

  if (!sessionId) {
    return;
  }
  appendEvent(sessionId, eventType, payload);
  const state = sessionState.get(sessionId);
  if (state) {
    state.lastEventAt = nowIso();
    state.updatedAt = nowIso();
  }
}

async function ensureWatcher(projectRoot) {
  if (watchersByProject.has(projectRoot)) {
    return;
  }

  const watcher = { active: true };
  watchersByProject.set(projectRoot, watcher);

  (async () => {
    while (watcher.active) {
      try {
        const stream = await opencodeClient.event.subscribe({
          query: { directory: projectRoot },
          sseDefaultRetryDelay: 1000,
          sseMaxRetryDelay: 5000,
        });
        for await (const event of stream.stream) {
          handleRawEvent(event);
        }
      } catch (error) {
        console.error("[opencode-wrapper] watcher error", projectRoot, error);
        await sleep(1000);
      }
    }
  })();
}

function normalizeDecision(decision) {
  if (decision === "once" || decision === "always" || decision === "reject") {
    return decision;
  }
  throw new Error(`Unsupported decision value: ${decision}`);
}

function normalizeMessageId(rawMessageId) {
  const value = String(rawMessageId ?? "").trim();
  if (!value) {
    return `msg_${randomUUID()}`;
  }
  if (value.startsWith("msg")) {
    return value;
  }
  return `msg_${value}`;
}

function routeMatch(pathname, pattern) {
  const match = pathname.match(pattern);
  if (!match) {
    return null;
  }
  return match.slice(1).map((segment) => decodeURIComponent(segment));
}

function mapDiffRows(diffRows) {
  const files = Array.isArray(diffRows)
    ? diffRows.map((row) => ({
        file: String(row?.file ?? ""),
        before: typeof row?.before === "string" ? row.before : "",
        after: typeof row?.after === "string" ? row.after : "",
        additions: toNumber(row?.additions, 0),
        deletions: toNumber(row?.deletions, 0),
      }))
    : [];
  const summary = files.reduce(
    (acc, item) => {
      acc.files += item.file ? 1 : 0;
      acc.additions += item.additions;
      acc.deletions += item.deletions;
      return acc;
    },
    { files: 0, additions: 0, deletions: 0 },
  );
  return { files, summary };
}

function toResultObject(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value;
  }
  if (Array.isArray(value)) {
    return { items: value };
  }
  return { value: value ?? null };
}

function buildLimits(session) {
  const tokens = session.totals?.tokens ?? {};
  const used =
    toNumber(tokens.input, 0) +
    toNumber(tokens.output, 0) +
    toNumber(tokens.reasoning, 0) +
    toNumber(tokens.cacheRead, 0) +
    toNumber(tokens.cacheWrite, 0);
  const contextWindow = toNumber(session.contextWindow, 0);
  const percent =
    contextWindow > 0 ? Math.max(0, Math.min(100, Number(((used / contextWindow) * 100).toFixed(2)))) : null;
  return {
    contextWindow: contextWindow > 0 ? contextWindow : null,
    used,
    percent,
  };
}

function buildStatus(session) {
  const pending = ensurePendingPermissions(session.sessionId);
  return {
    sessionId: session.sessionId,
    activity: session.activity ?? "idle",
    currentAction: session.currentAction ?? "Idle",
    lastEventAt: session.lastEventAt ?? session.updatedAt ?? session.createdAt ?? nowIso(),
    updatedAt: session.updatedAt ?? nowIso(),
    pendingPermissionsCount: pending.size,
    totals: session.totals ?? createEmptyTotals(),
    limits: buildLimits(session),
    lastRetryMessage: session.lastRetryMessage ?? null,
    lastRetryAttempt: session.lastRetryAttempt ?? null,
    lastRetryAt: session.lastRetryAt ?? null,
  };
}

async function getSessionMessages(session) {
  const rows = await opencodeClient.session.messages({
    path: { id: session.sessionId },
    query: { directory: session.projectRoot },
  });

  if (!Array.isArray(rows)) {
    return [];
  }

  return rows.map((row) => {
    const info = row?.info ?? {};
    const parts = Array.isArray(row?.parts) ? row.parts : [];
    const role = String(info?.role ?? "assistant");
    const content = messageContent(parts);
    return {
      messageId: String(info?.id ?? randomUUID()),
      role,
      content,
      runId: null,
      metadata: {
        providerId: info?.providerID ?? info?.model?.providerID ?? null,
        modelId: info?.modelID ?? info?.model?.modelID ?? null,
      },
      createdAt: toIso(info?.time?.created),
    };
  });
}

function buildHistory(session, limit) {
  const eventLog = ensureSessionEventLog(session.sessionId);
  const pending = ensurePendingPermissions(session.sessionId);
  const boundedLimit = Number.isFinite(limit) && limit > 0 ? Math.min(limit, 500) : 200;
  return {
    sessionId: session.sessionId,
    projectRoot: session.projectRoot,
    source: session.source,
    profile: session.profile,
    status: session.activity ?? "idle",
    events: eventLog.slice(-boundedLimit),
    pendingPermissions: Array.from(pending.values()),
    updatedAt: session.updatedAt ?? nowIso(),
  };
}

function writeSseEvent(res, eventType, payload) {
  res.write(`event: ${eventType}\n`);
  res.write(`data: ${JSON.stringify(payload)}\n\n`);
}

function setSseHeaders(res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
  });
}

async function handleCommand(session, command) {
  const normalized = String(command ?? "").trim().toLowerCase();
  if (!normalized) {
    const error = new Error("command is required");
    error.statusCode = 422;
    throw error;
  }

  if (normalized === "compact") {
    const result = await opencodeClient.session.summarize({
      path: { id: session.sessionId },
      query: { directory: session.projectRoot },
    });
    setSessionActivity(session, "busy", "Compacting context");
    appendEvent(session.sessionId, "command.executed", { command: normalized });
    return { command: normalized, result: toResultObject(result) };
  }

  if (normalized === "abort") {
    const result = await opencodeClient.session.abort({
      path: { id: session.sessionId },
      query: { directory: session.projectRoot },
    });
    setSessionActivity(session, "idle", "Aborted by user");
    appendEvent(session.sessionId, "command.executed", { command: normalized });
    return { command: normalized, result: toResultObject(result) };
  }

  if (normalized === "status") {
    const result = await opencodeClient.session.status({
      path: { id: session.sessionId },
      query: { directory: session.projectRoot },
    });
    appendEvent(session.sessionId, "command.executed", { command: normalized });
    return { command: normalized, result: toResultObject(result) };
  }

  if (normalized === "diff") {
    const diffRows = await opencodeClient.session.diff({
      path: { id: session.sessionId },
      query: { directory: session.projectRoot },
    });
    appendEvent(session.sessionId, "command.executed", { command: normalized });
    return { command: normalized, result: toResultObject(mapDiffRows(diffRows)) };
  }

  if (normalized === "help") {
    const result = await opencodeClient.command.list({
      query: { directory: session.projectRoot },
    });
    appendEvent(session.sessionId, "command.executed", { command: normalized });
    return { command: normalized, result: toResultObject(result) };
  }

  const error = new Error(`Unsupported command: ${normalized}`);
  error.statusCode = 422;
  throw error;
}

async function handleRequest(req, res) {
  const requestUrl = new URL(req.url ?? "/", `http://${WRAPPER_HOST}:${WRAPPER_PORT}`);
  const { pathname } = requestUrl;

  if (req.method === "GET" && pathname === "/internal/health") {
    return writeJson(res, 200, {
      status: "ok",
      wrapper: `http://${WRAPPER_HOST}:${WRAPPER_PORT}`,
      opencode: opencodeRuntime?.url ?? null,
      startedAt: nowIso(),
    });
  }

  if (req.method === "POST" && pathname === "/internal/sessions") {
    const body = await readBodyJson(req);
    const projectRoot = String(body.projectRoot ?? "").trim();
    const source = String(body.source ?? "ide-plugin");
    const profile = String(body.profile ?? "quick");
    const reuseExisting = body.reuseExisting !== false;

    if (!projectRoot) {
      return writeJson(res, 422, { detail: "projectRoot is required" });
    }

    if (reuseExisting) {
      const existingId = sessionsByProject.get(projectRoot);
      if (existingId && sessionState.has(existingId)) {
        const existing = sessionState.get(existingId);
        return writeJson(res, 200, {
          sessionId: existing.sessionId,
          createdAt: existing.createdAt,
          reused: true,
          projectRoot: existing.projectRoot,
          source: existing.source,
          profile: existing.profile,
        });
      }
    }

    await ensureWatcher(projectRoot);
    const created = await opencodeClient.session.create({
      query: { directory: projectRoot },
      body: { title: `${source}:${profile}` },
    });
    const sessionId = String(created?.id ?? "");
    if (!sessionId) {
      return writeJson(res, 502, { detail: "OpenCode did not return session id" });
    }

    const session = {
      sessionId,
      projectRoot,
      source,
      profile,
      createdAt: toIso(created?.time?.created),
      updatedAt: nowIso(),
      lastEventAt: nowIso(),
      activity: "idle",
      currentAction: "Idle",
      totals: createEmptyTotals(),
      contextWindow: null,
      lastRetryMessage: null,
      lastRetryAttempt: null,
      lastRetryAt: null,
    };
    sessionState.set(sessionId, session);
    sessionsByProject.set(projectRoot, sessionId);
    ensureSessionEventLog(sessionId);
    ensurePendingPermissions(sessionId);
    ensureMessageUsageMap(sessionId);
    appendEvent(sessionId, "session.created", { sessionId, projectRoot, source, profile });

    return writeJson(res, 200, {
      sessionId,
      createdAt: session.createdAt,
      reused: false,
      projectRoot,
      source,
      profile,
    });
  }

  {
    const match = routeMatch(pathname, /^\/internal\/sessions\/([^/]+)\/prompt-async$/);
    if (req.method === "POST" && match) {
      const [sessionId] = match;
      const session = getSessionOrThrow(sessionId);
      const body = await readBodyJson(req);
      const content = String(body.content ?? "").trim();
      if (!content) {
        return writeJson(res, 422, { detail: "content is required" });
      }

      const messageId = normalizeMessageId(body.messageId);
      await opencodeClient.session.promptAsync({
        path: { id: sessionId },
        query: { directory: session.projectRoot },
        body: {
          messageID: messageId,
          agent: body.agent ?? undefined,
          system: body.system ?? undefined,
          tools: body.tools ?? undefined,
          parts: [{ type: "text", text: content }],
        },
      });

      setSessionActivity(session, "busy", "Processing prompt");
      appendEvent(sessionId, "message.accepted", { sessionId, messageId });
      return writeJson(res, 200, { sessionId, messageId, accepted: true });
    }
  }

  {
    const match = routeMatch(
      pathname,
      /^\/internal\/sessions\/([^/]+)\/permissions\/([^/]+)$/,
    );
    if (req.method === "POST" && match) {
      const [sessionId, permissionId] = match;
      const session = getSessionOrThrow(sessionId);
      const body = await readBodyJson(req);
      const response = normalizeDecision(String(body.response ?? ""));

      await opencodeClient.postSessionIdPermissionsPermissionId({
        path: { id: sessionId, permissionID: permissionId },
        query: { directory: session.projectRoot },
        body: { response },
      });

      const pending = ensurePendingPermissions(sessionId);
      pending.delete(permissionId);
      appendEvent(sessionId, "permission.replied", {
        sessionId,
        permissionId,
        response,
      });
      setSessionActivity(session, pending.size > 0 ? "waiting_permission" : "busy", "Permission replied");
      return writeJson(res, 200, {
        sessionId,
        permissionId,
        accepted: true,
      });
    }
  }

  {
    const match = routeMatch(pathname, /^\/internal\/sessions\/([^/]+)\/history$/);
    if (req.method === "GET" && match) {
      const [sessionId] = match;
      const session = getSessionOrThrow(sessionId);
      const limit = Number.parseInt(requestUrl.searchParams.get("limit") ?? "200", 10);
      const history = buildHistory(session, limit);
      const messages = await getSessionMessages(session);
      history.messages = messages.slice(-Math.min(Math.max(limit, 1), 500));
      history.updatedAt = nowIso();
      return writeJson(res, 200, history);
    }
  }

  {
    const match = routeMatch(pathname, /^\/internal\/sessions\/([^/]+)\/status$/);
    if (req.method === "GET" && match) {
      const [sessionId] = match;
      const session = getSessionOrThrow(sessionId);
      return writeJson(res, 200, buildStatus(session));
    }
  }

  {
    const match = routeMatch(pathname, /^\/internal\/sessions\/([^/]+)\/diff$/);
    if (req.method === "GET" && match) {
      const [sessionId] = match;
      const session = getSessionOrThrow(sessionId);
      const diffRows = await opencodeClient.session.diff({
        path: { id: sessionId },
        query: { directory: session.projectRoot },
      });
      const mapped = mapDiffRows(diffRows);
      return writeJson(res, 200, {
        sessionId,
        ...mapped,
        updatedAt: nowIso(),
      });
    }
  }

  {
    const match = routeMatch(pathname, /^\/internal\/sessions\/([^/]+)\/commands$/);
    if (req.method === "POST" && match) {
      const [sessionId] = match;
      const session = getSessionOrThrow(sessionId);
      const body = await readBodyJson(req);
      const outcome = await handleCommand(session, body.command);
      return writeJson(res, 200, {
        sessionId,
        accepted: true,
        command: outcome.command,
        result: outcome.result ?? {},
        updatedAt: nowIso(),
      });
    }
  }

  {
    const match = routeMatch(pathname, /^\/internal\/sessions\/([^/]+)\/events$/);
    if (req.method === "GET" && match) {
      const [sessionId] = match;
      getSessionOrThrow(sessionId);
      setSseHeaders(res);

      let cursor = Number.parseInt(requestUrl.searchParams.get("fromIndex") ?? "0", 10);
      if (!Number.isFinite(cursor) || cursor < 0) {
        cursor = 0;
      }

      const flushEvents = () => {
        const eventLog = ensureSessionEventLog(sessionId);
        while (cursor < eventLog.length) {
          const event = eventLog[cursor];
          cursor += 1;
          writeSseEvent(res, event.eventType, event);
        }
      };

      flushEvents();
      const pollTimer = setInterval(flushEvents, 250);
      const heartbeatTimer = setInterval(() => {
        res.write(`: heartbeat ${Date.now()}\n\n`);
      }, 15000);

      req.on("close", () => {
        clearInterval(pollTimer);
        clearInterval(heartbeatTimer);
      });
      return;
    }
  }

  return writeJson(res, 404, { detail: `Not found: ${pathname}` });
}

async function bootstrap() {
  opencodeRuntime = await startOpencodeRuntime();
  opencodeClient = createOpencodeClient({
    baseUrl: opencodeRuntime.url,
    responseStyle: "data",
    throwOnError: true,
  });

  const server = createHttpServer(async (req, res) => {
    try {
      await handleRequest(req, res);
    } catch (error) {
      const statusCode = Number(error?.statusCode ?? 500);
      const detail = error?.message ?? "Unexpected wrapper error";
      console.error("[opencode-wrapper] request error", error);
      writeJson(res, statusCode, { detail });
    }
  });

  server.listen(WRAPPER_PORT, WRAPPER_HOST, () => {
    console.log(
      `[opencode-wrapper] listening on http://${WRAPPER_HOST}:${WRAPPER_PORT}, opencode=${opencodeRuntime.url}`,
    );
  });

  const shutdown = () => {
    for (const watcher of watchersByProject.values()) {
      watcher.active = false;
    }
    server.close(() => {
      opencodeRuntime?.close();
      process.exit(0);
    });
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

bootstrap().catch((error) => {
  console.error("[opencode-wrapper] startup failed", error);
  process.exit(1);
});
