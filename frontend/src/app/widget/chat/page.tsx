"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button, Input, Loading, Spinner } from "@/components/ui";

type Message = { sender: "bot" | "user"; text: string };
type Config = {
  organization_name: string;
  is_demo: boolean;
  welcome_message: string;
  available_topics: string[];
  consent_disclaimer: string;
  courses_offered: string[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

function ChatInner() {
  const searchParams = useSearchParams();
  const key = searchParams.get("key") ?? "";

  const [cfg, setCfg] = useState<Config | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(() => (!key ? "Missing organization public key (?key=...)" : ""));
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!key) return;
    let ignore = false;
    fetch(`${API_BASE}/public/config?key=${encodeURIComponent(key)}`)
      .then((res) => {
        if (!res.ok) throw new Error("Invalid organization public key");
        return res.json();
      })
      .then((data: Config) => {
        if (!ignore) {
          setCfg(data);
          setMessages([{ sender: "bot", text: data.welcome_message }]);
        }
      })
      .catch((e) => {
        if (!ignore) setErr(e.message);
      });
    return () => {
      ignore = true;
    };
  }, [key]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(textToSend?: string) {
    const text = (textToSend ?? input).trim();
    if (!text || loading) return;

    setInput("");
    const newMsgs: Message[] = [...messages, { sender: "user", text }];
    setMessages(newMsgs);
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/public/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          public_key: key,
          session_id: sessionId,
          message: text,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail ?? "Failed to send message");
      }

      const data = await res.json();
      setSessionId(data.session_id);
      setMessages([...newMsgs, { sender: "bot", text: data.reply }]);
    } catch (e) {
      setMessages([
        ...newMsgs,
        {
          sender: "bot",
          text: e instanceof Error ? e.message : "Service temporarily unavailable. Please try again or use the lead form.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  if (err) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-50 p-4">
        <div className="max-w-md rounded-2xl border border-rose-200 bg-white p-6 text-center shadow-lg">
          <p className="text-sm font-semibold text-rose-600">Widget Configuration Error</p>
          <p className="mt-1 text-xs text-muted">{err}</p>
        </div>
      </div>
    );
  }

  if (!cfg) return <Loading />;

  return (
    <div className="flex h-screen flex-col bg-slate-50 font-sans text-ink">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-line bg-white px-4 py-3 shadow-xs">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 font-bold text-white shadow-xs">
            {cfg.organization_name.charAt(0)}
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight leading-tight">{cfg.organization_name}</h1>
            <p className="text-[11px] text-emerald-600 font-medium flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> AI Admissions Assistant
            </p>
          </div>
        </div>
        <Link
          href={`/widget/form?key=${encodeURIComponent(key)}`}
          className="rounded-lg border border-line bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          Standard form
        </Link>
      </header>

      {/* Suggested Quick Topics */}
      {cfg.available_topics.length > 0 && messages.length <= 2 && (
        <div className="flex gap-1.5 overflow-x-auto bg-slate-100/70 p-2 text-xs">
          {cfg.available_topics.slice(0, 3).map((topic, i) => (
            <button
              key={i}
              onClick={() => send(`What are the details for ${topic}?`)}
              className="shrink-0 rounded-full border border-line bg-white px-3 py-1 font-medium text-slate-700 transition hover:border-brand-500 hover:text-brand-600"
            >
              {topic}
            </button>
          ))}
        </div>
      )}

      {/* Chat Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex ${m.sender === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 shadow-xs ${
                m.sender === "user"
                  ? "bg-brand-600 text-white rounded-br-xs"
                  : "bg-white text-slate-800 border border-line rounded-bl-xs whitespace-pre-wrap"
              }`}
            >
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 rounded-2xl border border-line bg-white px-4 py-2 text-xs text-muted">
              <Spinner />
              <span>Checking admissions handbook...</span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input bar */}
      <footer className="border-t border-line bg-white p-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex gap-2"
        >
          <Input
            aria-label="Your message"
            placeholder="Ask about courses, eligibility, or type your answer..."
            value={input}
            disabled={loading}
            onChange={(e) => setInput(e.target.value)}
          />
          <Button type="submit" disabled={!input.trim() || loading}>
            Send
          </Button>
        </form>
        <p className="mt-2 text-center text-[10px] text-slate-400">
          Powered by Admissions AI. Verified college admissions information only.
        </p>
      </footer>
    </div>
  );
}

export default function ChatWidgetPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ChatInner />
    </Suspense>
  );
}
