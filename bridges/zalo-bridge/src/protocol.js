/**
 * Wire protocol helpers for Zalo Bridge <-> DeepTutor.
 */

export function extractAttachments(rawContent, msgType = "") {
  let content = rawContent;
  if (
    typeof content === "string" &&
    content.trim().startsWith("{") &&
    content.trim().endsWith("}")
  ) {
    try {
      content = JSON.parse(content);
    } catch {
      // keep raw string if parsing fails
    }
  }

  const attachments = [];
  if (!content || typeof content !== "object") {
    return attachments;
  }

  // Extract photo attachment
  const isPhotoMsg =
    msgType === "chat.photo" ||
    Boolean(
      content.thumb ||
      content.thumbUrl ||
      content.hdUrl ||
      content.oriUrl ||
      content.normalUrl
    );

  if (isPhotoMsg) {
    const imgUrl =
      content.hdUrl ||
      content.oriUrl ||
      content.normalUrl ||
      content.href ||
      content.thumb ||
      content.thumbUrl ||
      content.url;

    if (imgUrl && typeof imgUrl === "string") {
      let filename = "photo.jpg";
      try {
        const parsedPath = new URL(imgUrl).pathname;
        const base = parsedPath.split("/").pop();
        if (base && /\.(jpg|jpeg|png|webp|gif)$/i.test(base)) {
          filename = base;
        }
      } catch {
        // fallback to default filename
      }
      attachments.push({
        type: "image",
        url: imgUrl,
        filename,
      });
    }
  } else if (
    msgType === "share.file" ||
    Boolean(content.fileSize || content.size)
  ) {
    // Extract file attachment
    const fileUrl = content.href || content.url;
    if (fileUrl && typeof fileUrl === "string") {
      const filename = String(
        content.title || content.fileName || "document"
      );
      const size = Number(content.fileSize || content.size || 0);
      attachments.push({
        type: "file",
        url: fileUrl,
        filename,
        ...(size > 0 ? { size } : {}),
      });
    }
  }

  return attachments;
}

export function formatInboundMessage(message, recentMessages) {
  const data = message.data || {};
  const threadType = message.type === 1 ? "group" : "user";
  const msgType = String(data.msgType || "");

  let rawContent = data.content;
  if (
    typeof rawContent === "string" &&
    rawContent.trim().startsWith("{") &&
    rawContent.trim().endsWith("}")
  ) {
    try {
      rawContent = JSON.parse(rawContent);
    } catch {
      // keep raw string if parsing fails
    }
  }

  const attachments = extractAttachments(rawContent, msgType);
  let content = "";

  if (typeof rawContent === "string") {
    content = rawContent;
  } else if (rawContent && typeof rawContent === "object") {
    // Extract caption / text
    if (typeof rawContent.description === "string" && rawContent.description.trim()) {
      content = rawContent.description;
    } else if (typeof rawContent.desc === "string" && rawContent.desc.trim()) {
      content = rawContent.desc;
    } else if (typeof rawContent.title === "string" && rawContent.title.trim()) {
      content = rawContent.title;
    }
  }

  // Fallback: when top-level attachments are empty, check quoted message
  if (attachments.length === 0 && data.quote) {
    const quote = data.quote;
    const quoteId = String(quote.globalMsgId || quote.cliMsgId || quote.msgId || "");

    // Tier 1: Look up in recentMessages cache
    if (recentMessages && quoteId && recentMessages.has(quoteId)) {
      const cached = recentMessages.get(quoteId);
      const cachedAtts = extractAttachments(cached?.content, cached?.msgType);
      if (cachedAtts.length > 0) {
        attachments.push(...cachedAtts);
      }
    }

    // Tier 2: Parse quote.attach payload directly
    if (attachments.length === 0 && quote.attach) {
      let attachObj = quote.attach;
      if (typeof attachObj === "string" && attachObj.trim().startsWith("{") && attachObj.trim().endsWith("}")) {
        try {
          attachObj = JSON.parse(attachObj);
        } catch {}
      }

      const quoteMsgType =
        quote.cliMsgType === 32
          ? "chat.photo"
          : quote.cliMsgType === 46
          ? "share.file"
          : "";

      if (attachObj && typeof attachObj === "object") {
        const parsedAtts = extractAttachments(attachObj, quoteMsgType);
        if (parsedAtts.length > 0) {
          attachments.push(...parsedAtts);
        }
      } else if (typeof attachObj === "string" && /^https?:\/\//i.test(attachObj)) {
        if (quote.cliMsgType === 32 || /\.(jpg|jpeg|png|webp|gif)$/i.test(attachObj)) {
          let filename = "photo.jpg";
          try {
            const base = new URL(attachObj).pathname.split("/").pop();
            if (base) filename = base;
          } catch {}
          attachments.push({ type: "image", url: attachObj, filename });
        } else if (quote.cliMsgType === 46) {
          attachments.push({
            type: "file",
            url: attachObj,
            filename: String(quote.msg || "document"),
          });
        }
      }
    }
  }

  return {
    type: "message",
    id: String(data.msgId || ""),
    thread_id: String(message.threadId || ""),
    thread_type: threadType,
    sender_id: String(data.uidFrom || message.threadId || ""),
    sender_name: String(data.dName || ""),
    content: content.trim(),
    attachments,
    is_self: Boolean(message.isSelf),
    mentions: Array.isArray(data.mentions) ? data.mentions : [],
    quote: data.quote || null,
    timestamp: Number(data.ts || Date.now()),
  };
}

export function parseOutboundMessage(raw) {
  let parsed;
  try {
    parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    throw new Error("Invalid JSON payload");
  }

  if (!parsed || parsed.type !== "send") {
    throw new Error(`Expected type 'send', got '${parsed?.type}'`);
  }
  if (!parsed.thread_id || typeof parsed.text !== "string") {
    throw new Error("Missing thread_id or text in send payload");
  }

  const rawThreadId = String(parsed.thread_id);
  const isGroup = parsed.thread_type === "group" || rawThreadId.startsWith("group:");
  const threadId = rawThreadId.startsWith("group:") ? rawThreadId.slice(6) : rawThreadId;

  return {
    type: "send",
    thread_id: threadId,
    thread_type: isGroup ? "group" : "user",
    text: String(parsed.text),
    styles: Array.isArray(parsed.styles) ? parsed.styles : undefined,
    quote_id: parsed.quote_id ? String(parsed.quote_id) : undefined,
  };
}

export function parseTypingMessage(raw) {
  let parsed;
  try {
    parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    throw new Error("Invalid JSON payload");
  }

  if (!parsed || parsed.type !== "typing") {
    throw new Error(`Expected type 'typing', got '${parsed?.type}'`);
  }
  if (!parsed.thread_id) {
    throw new Error("Missing thread_id in typing payload");
  }

  const rawThreadId = String(parsed.thread_id);
  const isGroup = parsed.thread_type === "group" || rawThreadId.startsWith("group:");
  const threadId = rawThreadId.startsWith("group:") ? rawThreadId.slice(6) : rawThreadId;

  return {
    type: "typing",
    thread_id: threadId,
    thread_type: isGroup ? "group" : "user",
  };
}



export function formatStatus(status, details = {}) {
  return {
    type: "status",
    status,
    user_id: details.userId ? String(details.userId) : undefined,
    display_name: details.displayName ? String(details.displayName) : undefined,
    message: details.message ? String(details.message) : undefined,
  };
}

export function formatQrEvent(type, data = {}) {
  return {
    type,
    data: {
      qr_data_url: data.qrDataUrl,
      code: data.code,
      token: data.token,
      avatar: data.avatar,
      display_name: data.displayName,
      uid: data.uid,
      name: data.name,
    },
  };
}
