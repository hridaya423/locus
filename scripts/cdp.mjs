// Headless Chrome over the DevTools protocol, with no dependencies (Node 22+ has fetch and WebSocket).
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function browser() {
  const port = 9400 + Math.floor(Math.random() * 500);
  const proc = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "locus-chrome-"))}`, "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
  process.on("exit", () => proc.kill());
  let targets;
  for (let i = 0; i < 100 && !targets; i++) {
    await sleep(100);
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch {}
  }
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0;
  const pending = new Map();
  const errors = [];
  const listeners = new Set();
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.id) return pending.get(m.id)?.(m);
    listeners.forEach((fn) => fn(m));
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text);
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push(`${m.params.entry.text} ${m.params.entry.url ?? ""}`.trim());
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const i = ++id;
    const timer = setTimeout(() => reject(new Error(`${method} timed out`)), 60000);
    pending.set(i, (m) => { clearTimeout(timer); resolve(m); });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  const page = {
    errors,
    send,
    listen: (fn) => listeners.add(fn),
    unlisten: (fn) => listeners.delete(fn),
    eval: async (expression) => {
      const m = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description ?? m.result.exceptionDetails.text);
      return m.result?.result?.value;
    },
    width: async (width) => send("Emulation.setDeviceMetricsOverride", { width, height: width < 500 ? 844 : 900, deviceScaleFactor: 1, mobile: width < 500 }),
    goto: async (url) => { await send("Page.navigate", { url }); await sleep(300); },
    // Polls an expression until it returns something truthy; returns that value, or null after the timeout.
    until: async (expression, ms = 30000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const v = await page.eval(expression).catch(() => null);
        if (v) return v;
        await sleep(250);
      }
      return null;
    },
    shot: async (file, full = false) => {
      const m = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: full });
      writeFileSync(file, Buffer.from(m.result.data, "base64"));
    },
    close: () => { ws.close(); proc.kill(); },
  };
  return page;
}

// The dataset page has finished reading its record when the About heading or an error line is on screen.
export const PAGE_READY = `!!(document.querySelector('#about, #samples, #characteristics, #files') || [...document.querySelectorAll('p')].some(p => /did not send|has no dataset|has no sample/.test(p.textContent)))`;
