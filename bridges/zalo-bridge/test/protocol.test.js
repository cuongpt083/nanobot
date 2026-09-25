import test from "node:test";
import assert from "node:assert/strict";
import {
  formatInboundMessage,
  parseOutboundMessage,
  parseTypingMessage,
  formatStatus,
  formatQrEvent,
} from "../src/protocol.js";

test("formatInboundMessage formats user direct message correctly", () => {
  const zcaMsg = {
    type: 0, // ThreadType.User
    threadId: "user_456",
    isSelf: false,
    data: {
      msgId: "msg_111",
      uidFrom: "user_456",
      dName: "Alice",
      content: "Hello from Zalo",
      ts: "1725390000000",
    },
  };

  const wire = formatInboundMessage(zcaMsg);
  assert.equal(wire.type, "message");
  assert.equal(wire.id, "msg_111");
  assert.equal(wire.thread_id, "user_456");
  assert.equal(wire.thread_type, "user");
  assert.equal(wire.sender_id, "user_456");
  assert.equal(wire.sender_name, "Alice");
  assert.equal(wire.content, "Hello from Zalo");
  assert.equal(wire.is_self, false);
});

test("formatInboundMessage formats group message with mentions", () => {
  const zcaMsg = {
    type: 1, // ThreadType.Group
    threadId: "group_789",
    isSelf: false,
    data: {
      msgId: "msg_222",
      uidFrom: "user_123",
      dName: "Bob",
      content: "@Bot tell me a joke",
      mentions: [{ uid: "bot_999", pos: 0, len: 4 }],
      ts: "1725390010000",
    },
  };

  const wire = formatInboundMessage(zcaMsg);
  assert.equal(wire.thread_type, "group");
  assert.equal(wire.thread_id, "group_789");
  assert.equal(wire.sender_id, "user_123");
  assert.deepEqual(wire.mentions, [{ uid: "bot_999", pos: 0, len: 4 }]);
});

test("parseOutboundMessage validates send payload", () => {
  const raw = JSON.stringify({
    type: "send",
    thread_id: "user_456",
    thread_type: "user",
    text: "Bot reply",
    quote_id: "msg_111",
  });

  const parsed = parseOutboundMessage(raw);
  assert.equal(parsed.thread_id, "user_456");
  assert.equal(parsed.thread_type, "user");
  assert.equal(parsed.text, "Bot reply");
  assert.equal(parsed.quote_id, "msg_111");
});

test("formatStatus formats status event", () => {
  const status = formatStatus("connected", {
    userId: "bot_999",
    displayName: "Tutor Bot",
  });
  assert.equal(status.type, "status");
  assert.equal(status.status, "connected");
  assert.equal(status.user_id, "bot_999");
  assert.equal(status.display_name, "Tutor Bot");
});

test("formatQrEvent formats qr code payload", () => {
  const qr = formatQrEvent("qr_generated", {
    qrDataUrl: "data:image/png;base64,xyz",
    token: "tok_1",
  });
  assert.equal(qr.type, "qr_generated");
  assert.equal(qr.data.qr_data_url, "data:image/png;base64,xyz");
  assert.equal(qr.data.token, "tok_1");
});

test("parseOutboundMessage preserves styles array", () => {
  const raw = JSON.stringify({
    type: "send",
    thread_id: "user_456",
    thread_type: "user",
    text: "Bold text",
    styles: [{ start: 0, len: 4, st: "b" }],
  });

  const parsed = parseOutboundMessage(raw);
  assert.deepEqual(parsed.styles, [{ start: 0, len: 4, st: "b" }]);
});

test("parseTypingMessage parses typing payload correctly", () => {
  const raw = JSON.stringify({
    type: "typing",
    thread_id: "user_456",
    thread_type: "group",
  });

  const parsed = parseTypingMessage(raw);
  assert.equal(parsed.type, "typing");
  assert.equal(parsed.thread_id, "user_456");
  assert.equal(parsed.thread_type, "group");
});

test("formatInboundMessage extracts photo attachment with caption", () => {
  const zcaMsg = {
    type: 0,
    threadId: "user_456",
    isSelf: false,
    data: {
      msgId: "msg_photo_1",
      msgType: "chat.photo",
      uidFrom: "user_456",
      dName: "Alice",
      content: {
        href: "https://res-zalo.zadn.vn/photo/sample_hd.jpg",
        thumb: "https://res-zalo.zadn.vn/photo/sample_thumb.jpg",
        description: "What food is this?",
      },
      ts: "1725390000000",
    },
  };

  const wire = formatInboundMessage(zcaMsg);
  assert.equal(wire.type, "message");
  assert.equal(wire.content, "What food is this?");
  assert.ok(Array.isArray(wire.attachments));
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "image");
  assert.equal(wire.attachments[0].url, "https://res-zalo.zadn.vn/photo/sample_hd.jpg");
  assert.equal(wire.attachments[0].filename, "sample_hd.jpg");
});

test("formatInboundMessage extracts photo attachment without caption", () => {
  const zcaMsg = {
    type: 0,
    threadId: "user_456",
    isSelf: false,
    data: {
      msgId: "msg_photo_2",
      msgType: "chat.photo",
      uidFrom: "user_456",
      dName: "Alice",
      content: {
        normalUrl: "https://res-zalo.zadn.vn/photo/normal.png",
      },
      ts: "1725390000000",
    },
  };

  const wire = formatInboundMessage(zcaMsg);
  assert.equal(wire.content, "");
  assert.ok(Array.isArray(wire.attachments));
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "image");
  assert.equal(wire.attachments[0].url, "https://res-zalo.zadn.vn/photo/normal.png");
});

test("formatInboundMessage extracts document attachment from share.file", () => {
  const zcaMsg = {
    type: 1,
    threadId: "group_789",
    isSelf: false,
    data: {
      msgId: "msg_file_1",
      msgType: "share.file",
      uidFrom: "user_123",
      dName: "Bob",
      content: {
        title: "nutrition_plan.pdf",
        href: "https://d-zalo.zadn.vn/file/nutrition_plan.pdf",
        fileSize: 1048576,
      },
      ts: "1725390000000",
    },
  };

  const wire = formatInboundMessage(zcaMsg);
  assert.ok(Array.isArray(wire.attachments));
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "file");
  assert.equal(wire.attachments[0].filename, "nutrition_plan.pdf");
  assert.equal(wire.attachments[0].url, "https://d-zalo.zadn.vn/file/nutrition_plan.pdf");
  assert.equal(wire.attachments[0].size, 1048576);
});

test("formatInboundMessage extracts quoted photo from recentMessages cache", () => {
  const recentMessages = new Map();
  recentMessages.set("msg_photo_orig", {
    msgId: "msg_photo_orig",
    msgType: "chat.photo",
    content: {
      href: "https://res-zalo.zadn.vn/photo/cached_hd.jpg",
      thumb: "https://res-zalo.zadn.vn/photo/cached_thumb.jpg",
      description: "Original photo caption",
    },
  });

  const replyMsg = {
    type: 1, // group
    threadId: "group_100",
    isSelf: false,
    data: {
      msgId: "msg_reply_1",
      msgType: "webchat",
      uidFrom: "user_user1",
      dName: "Bob",
      content: "@Bot please analyze this picture",
      mentions: [{ uid: "bot_999", pos: 0, len: 4 }],
      quote: {
        globalMsgId: "msg_photo_orig",
        cliMsgId: "msg_photo_orig",
        cliMsgType: 32,
        msg: "Original photo caption",
      },
      ts: "1725390020000",
    },
  };

  const wire = formatInboundMessage(replyMsg, recentMessages);
  assert.equal(wire.content, "@Bot please analyze this picture");
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "image");
  assert.equal(wire.attachments[0].url, "https://res-zalo.zadn.vn/photo/cached_hd.jpg");
  assert.equal(wire.attachments[0].filename, "cached_hd.jpg");
});

test("formatInboundMessage extracts quoted photo from quote.attach JSON payload when cache miss", () => {
  const replyMsg = {
    type: 1,
    threadId: "group_100",
    isSelf: false,
    data: {
      msgId: "msg_reply_2",
      msgType: "webchat",
      uidFrom: "user_user1",
      dName: "Bob",
      content: "@Bot explain this formula",
      quote: {
        globalMsgId: "msg_non_cached",
        cliMsgType: 32,
        attach: JSON.stringify({
          hdUrl: "https://res-zalo.zadn.vn/photo/formula_hd.png",
          thumb: "https://res-zalo.zadn.vn/photo/formula_thumb.png",
        }),
      },
      ts: "1725390030000",
    },
  };

  const wire = formatInboundMessage(replyMsg);
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "image");
  assert.equal(wire.attachments[0].url, "https://res-zalo.zadn.vn/photo/formula_hd.png");
  assert.equal(wire.attachments[0].filename, "formula_hd.png");
});

test("formatInboundMessage extracts quoted photo from quote.attach direct URL when cache miss", () => {
  const replyMsg = {
    type: 1,
    threadId: "group_100",
    isSelf: false,
    data: {
      msgId: "msg_reply_3",
      msgType: "webchat",
      uidFrom: "user_user1",
      dName: "Bob",
      content: "check this",
      quote: {
        globalMsgId: "msg_direct_url",
        cliMsgType: 32,
        attach: "https://res-zalo.zadn.vn/photo/graph.jpg",
      },
      ts: "1725390040000",
    },
  };

  const wire = formatInboundMessage(replyMsg);
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "image");
  assert.equal(wire.attachments[0].url, "https://res-zalo.zadn.vn/photo/graph.jpg");
});

test("formatInboundMessage extracts quoted document from quote.attach with cliMsgType 46", () => {
  const replyMsg = {
    type: 1,
    threadId: "group_100",
    isSelf: false,
    data: {
      msgId: "msg_reply_4",
      msgType: "webchat",
      uidFrom: "user_user1",
      dName: "Bob",
      content: "summarize this file",
      quote: {
        globalMsgId: "msg_doc_1",
        cliMsgType: 46,
        msg: "research_paper.pdf",
        attach: JSON.stringify({
          href: "https://d-zalo.zadn.vn/file/research_paper.pdf",
          fileSize: 204800,
          title: "research_paper.pdf",
        }),
      },
      ts: "1725390050000",
    },
  };

  const wire = formatInboundMessage(replyMsg);
  assert.equal(wire.attachments.length, 1);
  assert.equal(wire.attachments[0].type, "file");
  assert.equal(wire.attachments[0].filename, "research_paper.pdf");
  assert.equal(wire.attachments[0].url, "https://d-zalo.zadn.vn/file/research_paper.pdf");
  assert.equal(wire.attachments[0].size, 204800);
});

test("formatInboundMessage does not produce attachments when quoted message is plain text", () => {
  const replyMsg = {
    type: 1,
    threadId: "group_100",
    isSelf: false,
    data: {
      msgId: "msg_reply_5",
      msgType: "webchat",
      uidFrom: "user_user1",
      dName: "Bob",
      content: "yes I agree",
      quote: {
        globalMsgId: "msg_txt_1",
        cliMsgType: 1,
        msg: "Let's meet at 2pm",
      },
      ts: "1725390060000",
    },
  };

  const wire = formatInboundMessage(replyMsg);
  assert.equal(wire.attachments.length, 0);
});


