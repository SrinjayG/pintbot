// Pint bot listener — read-only WhatsApp linked device.
// Watches ONE group and drops each message into ../data/inbox as JSON
// (photos go to ../data/media). It never sends anything.
//
// Run from pintbot/listener:  node --env-file=../.env listener.js

import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  Browsers,
  isJidGroup,
  downloadMediaMessage,
} from "baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const INBOX = path.join(ROOT, "data", "inbox");
const MEDIA = path.join(ROOT, "data", "media");
fs.mkdirSync(INBOX, { recursive: true });
fs.mkdirSync(MEDIA, { recursive: true });

// Empty on first run → discovery mode (prints group names + IDs).
const PINT_GROUP_JID = (process.env.PINT_GROUP_JID || "").trim();
const logger = pino({ level: "silent" });

function writeAtomic(file, data) {
  const tmp = file + ".tmp";
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, file); // worker never sees half-written files
}

function extractText(m) {
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    ""
  );
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(path.join(ROOT, "listener", "auth"));

  const sock = makeWASocket({
    auth: state,
    logger,
    browser: Browsers.macOS("Desktop"),
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log("\nScan in WhatsApp → Settings → Linked devices → Link a device\n");
      qrcode.generate(qr, { small: true });
    }
    if (connection === "open") {
      console.log(
        PINT_GROUP_JID
          ? `✅ Connected (read-only). Watching ${PINT_GROUP_JID}`
          : "✅ Connected. DISCOVERY MODE: post in your pint group to see its ID."
      );
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.log("Logged out. Delete listener/auth and run again to re-link.");
        process.exit(1);
      }
      console.log("Connection dropped, reconnecting in 5s…", code ?? "");
      setTimeout(start, 5000);
    }
  });

  const seenGroups = new Set();

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    // "notify" = live messages; "append" = messages synced after a reconnect.
    if (type !== "notify" && type !== "append") return;

    for (const msg of messages) {
      try {
        const jid = msg.key.remoteJid;
        if (!jid || !isJidGroup(jid)) continue; // private chats: ignored, never stored

        if (!PINT_GROUP_JID) {
          if (!seenGroups.has(jid)) {
            seenGroups.add(jid);
            const meta = await sock.groupMetadata(jid).catch(() => null);
            console.log(`group: ${meta?.subject ?? "(unknown)"}  →  ${jid}`);
          }
          continue;
        }
        if (jid !== PINT_GROUP_JID) continue;

        const m = msg.message;
        if (!m) continue;
        const id = msg.key.id;
        const outFile = path.join(INBOX, `${id}.json`);
        if (fs.existsSync(outFile)) continue; // already captured

        let photo = null;
        if (m.imageMessage) {
          try {
            const buf = await downloadMediaMessage(msg, "buffer", {}, {
              logger,
              reuploadRequest: sock.updateMediaMessage,
            });
            photo = path.join("data", "media", `${id}.jpg`);
            fs.writeFileSync(path.join(ROOT, photo), buf);
          } catch (e) {
            console.warn("photo download failed for", id, e.message);
          }
        }

        const record = {
          id,
          sender_id: msg.key.fromMe ? "me" : (msg.key.participant || msg.key.remoteJid),
          sender_name: msg.key.fromMe ? (process.env.MY_NAME || "me") : (msg.pushName || null),
          from_me: Boolean(msg.key.fromMe),
          timestamp: Number(msg.messageTimestamp),
          text: extractText(m),
          photo,
          quoted_id: m.extendedTextMessage?.contextInfo?.stanzaId || m.imageMessage?.contextInfo?.stanzaId || null,
        };
        writeAtomic(outFile, JSON.stringify(record));
        console.log(`📥 ${record.sender_name ?? record.sender_id}: ${record.text || "(photo)"}`);
      } catch (e) {
        console.error("failed to capture message:", e.message);
      }
    }
  });
}

start();
