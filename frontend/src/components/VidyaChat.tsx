"use client";
import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, X, Send, Bot, User, Loader2, Link2 } from "lucide-react";

import { apiUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/auth-session";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Array<{
    opportunity_id: string;
    url: string;
    title?: string | null;
    source?: string | null;
  }>;
}

type ChatApiResponse = {
  request_id: string;
  message: string;
  mode: string;
  citations?: Array<{
    opportunity_id: string;
    url: string;
    title?: string | null;
    source?: string | null;
  }>;
};

export default function VidyaChat() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "I’m **Vidya**, your backend-routed assistant for VidyaVerse. Ask for opportunities, strategy, or profile advice.",
    },
  ]);
  const [inputMessage, setInputMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
    }
  }, [messages, isOpen]);

  const handleSendMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const token = getAccessToken();
    if (!token) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "**Sign in required:** the assistant uses your VidyaVerse session." },
      ]);
      setInputMessage("");
      return;
    }

    const userMsg: ChatMessage = { role: "user", content: inputMessage.trim() };
    const nextMessages = [...messages, userMsg];
    setMessages([...nextMessages, { role: "assistant", content: "" }]);
    setInputMessage("");
    setIsLoading(true);

    try {
      const response = await fetch(apiUrl("/api/v1/chat/"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          messages: nextMessages.slice(-10).map((message) => ({
            role: message.role,
            content: message.content,
          })),
          surface: "global_chat",
        }),
      });
      const payload = (await response.json().catch(() => null)) as ChatApiResponse | { detail?: string } | null;
      if (!response.ok || !payload || !("message" in payload)) {
        throw new Error(
          payload && "detail" in payload && typeof payload.detail === "string"
            ? payload.detail
            : "Assistant request failed.",
        );
      }

      setMessages((prev) => {
        const updated = [...prev];
        if (updated.length && updated[updated.length - 1].role === "assistant") {
          updated[updated.length - 1] = {
            role: "assistant",
            content: payload.message,
            citations: payload.citations || [],
          };
        }
        return updated;
      });
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : "Assistant request failed.";
      setMessages((prev) => {
        const updated = [...prev];
        if (updated.length && updated[updated.length - 1].role === "assistant") {
          updated[updated.length - 1] = { role: "assistant", content: `**System Error:** ${detail}` };
        }
        return updated;
      });
    } finally {
      setIsLoading(false);
    }
  };

  const formatMessage = (text: string) => {
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={index} style={{ color: "inherit" }}>
            {part.slice(2, -2)}
          </strong>
        );
      }
      return (
        <span key={index}>
          {part.split("\n").map((line, i) => (
            <React.Fragment key={i}>
              {line}
              <br />
            </React.Fragment>
          ))}
        </span>
      );
    });
  };

  return (
    <>
      <motion.button
        className="card-panel"
        style={{
          position: "fixed",
          bottom: "2rem",
          right: "2rem",
          width: "64px",
          height: "64px",
          borderRadius: "50%",
          background: "var(--brand-primary)",
          color: "#000000",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 50,
          padding: 0,
        }}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95, y: 4, boxShadow: "0px 0px 0px #000000" }}
        onClick={() => setIsOpen(true)}
        aria-label="Open Vidya AI chat"
        initial={{ opacity: 0, scale: 0 }}
        animate={{ opacity: isOpen ? 0 : 1, scale: isOpen ? 0 : 1 }}
      >
        <MessageSquare size={28} />
      </motion.button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="card-panel"
            style={{
              position: "fixed",
              bottom: "2rem",
              right: "2rem",
              width: "400px",
              height: "600px",
              maxHeight: "80vh",
              display: "flex",
              flexDirection: "column",
              zIndex: 50,
              padding: 0,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                background: "var(--brand-primary)",
                padding: "1.25rem 1.5rem",
                borderBottom: "2px solid var(--border-subtle)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                color: "#000000",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <Bot size={24} />
                <h3 style={{ fontFamily: "var(--font-serif)", fontSize: "1.5rem", margin: 0, lineHeight: 1 }}>
                  Vidya AI
                </h3>
              </div>
              <button onClick={() => setIsOpen(false)} aria-label="Close Vidya AI chat">
                <X size={22} />
              </button>
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: "1rem", display: "grid", gap: "0.9rem" }}>
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  style={{
                    display: "flex",
                    gap: "0.75rem",
                    alignItems: "flex-start",
                    justifyContent: message.role === "user" ? "flex-end" : "flex-start",
                  }}
                >
                  {message.role === "assistant" && <Bot size={18} style={{ marginTop: "0.2rem" }} />}
                  <div
                    style={{
                      maxWidth: "84%",
                      padding: "0.85rem 1rem",
                      borderRadius: "var(--radius-sm)",
                      background:
                        message.role === "user"
                          ? "var(--brand-primary)"
                          : "color-mix(in srgb, var(--bg-surface) 88%, white 12%)",
                      color: message.role === "user" ? "#000000" : "var(--text-primary)",
                      border: "2px solid var(--border-subtle)",
                      fontSize: "0.95rem",
                      lineHeight: 1.55,
                    }}
                  >
                    {formatMessage(message.content)}
                    {message.citations && message.citations.length > 0 && (
                      <div style={{ marginTop: "0.7rem", display: "grid", gap: "0.4rem" }}>
                        {message.citations.slice(0, 3).map((citation) => (
                          <a
                            key={`${citation.opportunity_id}-${citation.url}`}
                            href={citation.url}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "0.35rem",
                              fontSize: "0.8rem",
                              color: "inherit",
                              textDecoration: "underline",
                            }}
                          >
                            <Link2 size={12} />
                            {citation.title || citation.source || citation.url}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                  {message.role === "user" && <User size={18} style={{ marginTop: "0.2rem" }} />}
                </div>
              ))}
              {isLoading && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "var(--text-secondary)" }}>
                  <Loader2 size={16} className="animate-spin" />
                  Thinking...
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <form
              onSubmit={handleSendMessage}
              style={{
                borderTop: "2px solid var(--border-subtle)",
                padding: "1rem",
                display: "flex",
                gap: "0.75rem",
                background: "var(--bg-surface)",
              }}
            >
              <input
                value={inputMessage}
                onChange={(event) => setInputMessage(event.target.value)}
                placeholder="Ask Vidya about roles, fit, or next steps..."
                className="input-base"
                style={{ flex: 1 }}
                disabled={isLoading}
              />
              <button type="submit" className="btn-secondary" disabled={isLoading || !inputMessage.trim()}>
                {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
