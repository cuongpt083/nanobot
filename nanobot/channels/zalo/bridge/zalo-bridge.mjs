#!/usr/bin/env node
/**
 * JSONL sidecar wrapping zca-js for nanobot's Zalo personal-account channel.
 *
 * Protocol (stdin/stdout, one JSON object per line):
 *   request:  {"id":"1","method":"login_qr","params":{}}
 *   response: {"id":"1","ok":true,"result":{...}}
 *   event:    {"event":"qr","payload":{"code":"..."}}
 */
import fs from "node:fs";
import fsPromises from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";

const ThreadType = Object.freeze({ User: 0, Group: 1 });
const LoginQRCallbackEventType = Object.freeze({
  QRCodeGenerated: 0,
  QRCodeExpired: 1,
  QRCodeScanned: 2,
  QRCodeDeclined: 3,
  GotLoginInfo: 4,
});

const credentialsPath = process.env.ZALO_CREDENTIALS_PATH || "";
if (!credentialsPath) {
  failFatal("ZALO_CREDENTIALS_PATH is required");
}

/** @type {import("zca-js").API | null} */
let api = null;
let qrAbort = null;
let listenerStarted = false;

function writeLine(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function emit(event, payload = {}) {
  writeLine({ event, payload });
}

function failFatal(message) {
  writeLine({ event: "error", payload: { message } });
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function reply(id, result) {
  writeLine({ id, ok: true, result });
}

function replyError(id, message) {
  writeLine({ id, ok: false, error: message });
}

function errorMessage(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

async function imageMetadataGetter(filePath) {
  const data = await fsPromises.readFile(filePath);
  return probeImage(data);
}

function probeImage(buf) {
  const size = buf.length;
  if (size >= 24 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20), size };
  }
  if (size > 4 && buf[0] === 0xff && buf[1] === 0xd8) {
    let offset = 2;
    while (offset + 9 < size) {
      if (buf[offset] !== 0xff) {
        break;
      }
      const marker = buf[offset + 1];
      const length = buf.readUInt16BE(offset + 2);
      if (marker === 0xc0 || marker === 0xc1 || marker === 0xc2) {
        return {
          height: buf.readUInt16BE(offset + 5),
          width: buf.readUInt16BE(offset + 7),
          size,
        };
      }
      offset += 2 + length;
    }
  }
  return { width: 1, height: 1, size };
}

function readStoredCredentials() {
  try {
    const raw = fs.readFileSync(credentialsPath, "utf8");
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    if (!parsed.imei || !parsed.cookie || !parsed.userAgent) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function snapshotCredentials(currentApi, fallback) {
  const ctx = currentApi.getContext();
  const cookieJson = currentApi.getCookie().toJSON();
  const cookies =
    Array.isArray(cookieJson?.cookies) && cookieJson.cookies.length > 0
      ? cookieJson.cookies
      : fallback?.cookie;
  const imei = ctx.imei || fallback?.imei;
  const userAgent = ctx.userAgent || fallback?.userAgent;
  if (!imei || !cookies || !userAgent) {
    throw new Error("Zalo session did not expose credentials");
  }
  return {
    imei,
    cookie: cookies,
    userAgent,
    language: ctx.language || fallback?.language || "vi",
    createdAt: fallback?.createdAt || new Date().toISOString(),
    lastUsedAt: new Date().toISOString(),
  };
}

function writeCredentials(payload) {
  const dir = path.dirname(credentialsPath);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const tmp = `${credentialsPath}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(payload, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(tmp, credentialsPath);
  try {
    fs.chmodSync(path.dirname(credentialsPath), 0o700);
  } catch {
    // ignore
  }
}

function clearCredentials() {
  try {
    fs.unlinkSync(credentialsPath);
    return true;
  } catch {
    return false;
  }
}

async function createZalo() {
  const { Zalo } = await import("zca-js");
  return new Zalo({
    logging: false,
    selfListen: false,
    imageMetadataGetter,
  });
}

function stopListener() {
  if (!api) {
    return;
  }
  try {
    api.listener.stop();
  } catch {
    // ignore
  }
  listenerStarted = false;
}

async function loginWithStoredSession() {
  const stored = readStoredCredentials();
  if (!stored) {
    throw new Error("No saved Zalo session. Run: nanobot channels login zalo");
  }
  const zalo = await createZalo();
  api = await zalo.login({
    imei: stored.imei,
    cookie: stored.cookie,
    userAgent: stored.userAgent,
    language: stored.language,
  });
  writeCredentials(snapshotCredentials(api, stored));
  return accountSnapshot();
}

function accountSnapshot() {
  if (!api) {
    return { authenticated: false };
  }
  let userId = "";
  try {
    userId = String(api.getOwnId() || "");
  } catch {
    userId = "";
  }
  return { authenticated: true, userId };
}

async function loginQr() {
  if (qrAbort) {
    try {
      qrAbort();
    } catch {
      // ignore
    }
    qrAbort = null;
  }
  stopListener();
  api = null;

  const zalo = await createZalo();
  let captured = null;
  const apiSession = await zalo.loginQR(undefined, (event) => {
    if (event.actions?.abort) {
      qrAbort = () => {
        try {
          event.actions.abort();
        } catch {
          // ignore
        }
      };
    }
    switch (event.type) {
      case LoginQRCallbackEventType.QRCodeGenerated: {
        const image = String(event.data?.image || "");
        emit("qr", {
          code: String(event.data?.code || ""),
          image: image.startsWith("data:image")
            ? image
            : image
              ? `data:image/png;base64,${image}`
              : "",
        });
        break;
      }
      case LoginQRCallbackEventType.QRCodeExpired: {
        try {
          event.actions.retry();
        } catch {
          emit("qr_expired", {});
        }
        break;
      }
      case LoginQRCallbackEventType.QRCodeScanned: {
        emit("qr_scanned", {
          displayName: String(event.data?.display_name || ""),
        });
        break;
      }
      case LoginQRCallbackEventType.QRCodeDeclined: {
        emit("qr_declined", {});
        break;
      }
      case LoginQRCallbackEventType.GotLoginInfo: {
        captured = {
          imei: event.data.imei,
          cookie: event.data.cookie,
          userAgent: event.data.userAgent,
        };
        break;
      }
      default:
        break;
    }
  });
  qrAbort = null;
  api = apiSession;
  writeCredentials(snapshotCredentials(apiSession, captured));
  const snapshot = accountSnapshot();
  emit("login_ok", snapshot);
  return snapshot;
}

function startListen() {
  if (!api) {
    throw new Error("Zalo is not authenticated");
  }
  if (listenerStarted) {
    return { listening: true };
  }
  api.listener.on("message", (message) => {
    emit("message", message);
  });
  api.listener.on("error", (error) => {
    emit("error", { message: errorMessage(error) });
  });
  api.listener.on("closed", (code, reason) => {
    emit("closed", { code, reason: String(reason || "") });
  });
  api.listener.start({ retryOnClose: true });
  listenerStarted = true;
  return { listening: true };
}

async function sendMessage(params) {
  if (!api) {
    throw new Error("Zalo is not authenticated");
  }
  const threadId = String(params.threadId || "").trim();
  if (!threadId) {
    throw new Error("threadId is required");
  }
  const type = params.isGroup ? ThreadType.Group : ThreadType.User;
  const text = String(params.text || "");
  const attachments = Array.isArray(params.attachments) ? params.attachments : [];
  if (attachments.length > 0) {
    const uploaded = [];
    for (const item of attachments) {
      const filePath = String(item.path || "").trim();
      if (!filePath) {
        continue;
      }
      const data = await fsPromises.readFile(filePath);
      const filename = path.basename(filePath);
      const metadata = probeImage(data);
      uploaded.push({
        data,
        filename: filename.includes(".") ? filename : `${filename}.bin`,
        metadata: {
          totalSize: metadata.size,
          width: metadata.width,
          height: metadata.height,
        },
      });
    }
    const response = await api.sendMessage(
      {
        msg: text,
        attachments: uploaded,
      },
      threadId,
      type,
    );
    return { messageId: extractMessageId(response) };
  }
  const response = await api.sendMessage(text, threadId, type);
  return { messageId: extractMessageId(response) };
}

function extractMessageId(result) {
  if (!result || typeof result !== "object") {
    return "";
  }
  if (result.msgId != null) {
    return String(result.msgId);
  }
  if (result.message?.msgId != null) {
    return String(result.message.msgId);
  }
  if (result.attachment?.[0]?.msgId != null) {
    return String(result.attachment[0].msgId);
  }
  return "";
}

async function sendTyping(params) {
  if (!api) {
    throw new Error("Zalo is not authenticated");
  }
  const threadId = String(params.threadId || "").trim();
  if (!threadId) {
    throw new Error("threadId is required");
  }
  const type = params.isGroup ? ThreadType.Group : ThreadType.User;
  await api.sendTypingEvent(threadId, type);
  return { ok: true };
}

async function handle(method, params) {
  switch (method) {
    case "status": {
      if (api) {
        return accountSnapshot();
      }
      const stored = readStoredCredentials();
      return { authenticated: Boolean(stored), stored: Boolean(stored) };
    }
    case "login_session":
      return await loginWithStoredSession();
    case "login_qr":
      return await loginQr();
    case "listen":
      return startListen();
    case "send":
      return await sendMessage(params);
    case "typing":
      return await sendTyping(params);
    case "logout": {
      stopListener();
      if (qrAbort) {
        try {
          qrAbort();
        } catch {
          // ignore
        }
        qrAbort = null;
      }
      api = null;
      const cleared = clearCredentials();
      return { cleared };
    }
    case "abort_qr": {
      if (qrAbort) {
        try {
          qrAbort();
        } catch {
          // ignore
        }
        qrAbort = null;
      }
      return { aborted: true };
    }
    default:
      throw new Error(`Unknown method: ${method}`);
  }
}

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", async (line) => {
  const trimmed = line.trim();
  if (!trimmed) {
    return;
  }
  let request;
  try {
    request = JSON.parse(trimmed);
  } catch (error) {
    emit("error", { message: `Invalid JSON request: ${errorMessage(error)}` });
    return;
  }
  const id = request.id;
  const method = request.method;
  const params = request.params && typeof request.params === "object" ? request.params : {};
  if (!id || !method) {
    emit("error", { message: "Request must include id and method" });
    return;
  }
  try {
    const result = await handle(method, params);
    reply(id, result ?? {});
  } catch (error) {
    replyError(id, errorMessage(error));
  }
});

rl.on("close", () => {
  stopListener();
  process.exit(0);
});

process.on("SIGINT", () => {
  stopListener();
  process.exit(0);
});
process.on("SIGTERM", () => {
  stopListener();
  process.exit(0);
});

emit("ready", {});
