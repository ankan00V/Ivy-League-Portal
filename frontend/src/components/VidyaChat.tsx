"use client";
import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, X, Send, Bot, User, Loader2 } from 'lucide-react';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const PUTER_MODEL = process.env.NEXT_PUBLIC_PUTER_MODEL || 'claude-sonnet-4-6';
const PUTER_SCRIPT_SRC = "https://js.puter.com/v2/";
let puterScriptLoadPromise: Promise<void> | null = null;

function ensurePuterLoaded(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Puter can only load in browser context."));
  }
  if (window.puter?.ai?.chat) {
    return Promise.resolve();
  }
  if (puterScriptLoadPromise) {
    return puterScriptLoadPromise;
  }

  puterScriptLoadPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-puter-sdk="true"]');
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Failed to load Puter SDK.")), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = PUTER_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.dataset.puterSdk = "true";
    script.onload = () => {
      if (window.puter?.ai?.chat) {
        resolve();
      } else {
        reject(new Error("Puter SDK loaded but AI API is unavailable."));
      }
    };
    script.onerror = () => reject(new Error("Failed to load Puter SDK from network."));
    document.body.appendChild(script);
  }).catch((error) => {
    // Allow retry on subsequent attempts.
    puterScriptLoadPromise = null;
    throw error;
  });

  return puterScriptLoadPromise;
}

export default function VidyaChat() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: "Hey! I'm **Vidya**, your official AI mentor for VidyaVerse. Whether you need help finding the right hackathon or optimizing your resume, I've got your back. What's up?" }
  ]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (isOpen) {
      scrollToBottom();
    }
  }, [messages, isOpen]);

  const handleSendMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const userMsg: ChatMessage = { role: 'user', content: inputMessage.trim() };
    // Add a placeholder assistant message for streaming updates.
    setMessages(prev => [...prev, userMsg, { role: 'assistant', content: '' }]);
    setInputMessage('');
    setIsLoading(true);

    try {
      await ensurePuterLoaded();
      const chatHistory = [...messages.slice(-10), userMsg];
      const puter = typeof window !== 'undefined' ? window.puter : undefined;

      if (!puter?.ai?.chat) {
        throw new Error("Puter AI is not available yet. Please refresh and try again.");
      }

      const prompt = [
        "You are Vidya, an elite academic and career mentor.",
        "Give practical, concise, high-impact advice in markdown.",
        "Conversation:",
        ...chatHistory.map((msg) => `${msg.role === 'user' ? 'User' : 'Assistant'}: ${msg.content}`),
        "Assistant:"
      ].join("\n");

      const streamed = await puter.ai.chat(prompt, {
        model: PUTER_MODEL,
        stream: true,
      });

      if (streamed && Symbol.asyncIterator in Object(streamed)) {
        let fullText = "";
        for await (const part of streamed as AsyncIterable<PuterChatPart>) {
          const chunk = part?.text || "";
          if (!chunk) continue;
          fullText += chunk;
          setMessages((prev) => {
            const next = [...prev];
            if (next.length && next[next.length - 1].role === 'assistant') {
              next[next.length - 1] = { role: 'assistant', content: fullText };
            }
            return next;
          });
        }

        if (!fullText.trim()) {
          setMessages((prev) => {
            const next = [...prev];
            if (next.length && next[next.length - 1].role === 'assistant') {
              next[next.length - 1] = { role: 'assistant', content: "No response generated. Please retry." };
            }
            return next;
          });
        }
      } else {
        const response = streamed as PuterChatResponse;
        const text = response?.message?.content?.[0]?.text || "No response generated. Please retry.";
        setMessages((prev) => {
          const next = [...prev];
          if (next.length && next[next.length - 1].role === 'assistant') {
            next[next.length - 1] = { role: 'assistant', content: text };
          }
          return next;
        });
      }
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : "AI request failed.";
      console.warn(`[VidyaChat] Puter chat unavailable: ${detail}`);
      setMessages((prev) => {
        const next = [...prev];
        if (next.length && next[next.length - 1].role === 'assistant') {
          next[next.length - 1] = { role: 'assistant', content: `**System Error:** ${detail}` };
        } else {
          next.push({ role: 'assistant', content: `**System Error:** ${detail}` });
        }
        return next;
      });
    } finally {
      setIsLoading(false);
    }
  };

  // Simple Markdown parser for Bold and Linebreaks
  const formatMessage = (text: string) => {
      const parts = text.split(/(\*\*.*?\*\*)/g);
      return parts.map((part, index) => {
          if (part.startsWith('**') && part.endsWith('**')) {
              return <strong key={index} style={{ color: 'inherit' }}>{part.slice(2, -2)}</strong>;
          }
          return <span key={index}>{part.split('\n').map((line, i) => <React.Fragment key={i}>{line}<br/></React.Fragment>)}</span>;
      });
  };

  return (
    <>
      {/* Floating Action Button */}
      <motion.button
        className="card-panel"
        style={{
          position: 'fixed',
          bottom: '2rem',
          right: '2rem',
          width: '64px',
          height: '64px',
          borderRadius: '50%',
          background: 'var(--brand-primary)',
          color: '#000000',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 50,
          padding: 0,
        }}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95, y: 4, boxShadow: '0px 0px 0px #000000' }}
        onClick={() => setIsOpen(true)}
        initial={{ opacity: 0, scale: 0 }}
        animate={{ opacity: isOpen ? 0 : 1, scale: isOpen ? 0 : 1 }}
      >
        <MessageSquare size={28} />
      </motion.button>

      {/* Chat Window */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            className="card-panel"
            style={{
              position: 'fixed',
              bottom: '2rem',
              right: '2rem',
              width: '400px',
              height: '600px',
              maxHeight: '80vh',
              display: 'flex',
              flexDirection: 'column',
              zIndex: 50,
              padding: 0,
              overflow: 'hidden'
            }}
          >
            {/* Header */}
            <div style={{
              background: 'var(--brand-primary)',
              padding: '1.25rem 1.5rem',
              borderBottom: '2px solid var(--border-subtle)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              color: '#000000'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <Bot size={24} />
                <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.5rem', margin: 0, lineHeight: 1 }}>Vidya AI</h3>
              </div>
              <button 
                onClick={() => setIsOpen(false)}
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#000000', padding: '0.25rem' }}
              >
                <X size={24} />
              </button>
            </div>

            {/* Messages Area */}
            <div style={{
              flex: 1,
              overflowY: 'auto',
              padding: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
              background: 'var(--bg-base)'
            }}>
              {messages.map((msg, idx) => (
                <div 
                  key={idx} 
                  style={{ 
                    display: 'flex', 
                    gap: '0.75rem', 
                    alignItems: 'flex-start',
                    flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
                   }}
                >
                  {/* Avatar */}
                  <div style={{
                    width: '32px', height: '32px', flexShrink: 0,
                    borderRadius: 'var(--radius-sm)',
                    background: msg.role === 'assistant' ? 'var(--brand-primary)' : 'var(--bg-surface-hover)',
                    border: '2px solid var(--border-subtle)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: msg.role === 'assistant' ? '#000000' : 'var(--text-primary)'
                  }}>
                    {msg.role === 'assistant' ? <Bot size={18} /> : <User size={18} />}
                  </div>
                  
                  {/* Bubble */}
                  <div style={{
                    background: msg.role === 'user' ? 'var(--text-primary)' : 'var(--bg-surface)',
                    color: msg.role === 'user' ? 'var(--bg-base)' : 'var(--text-primary)',
                    padding: '0.85rem 1.15rem',
                    borderRadius: 'var(--radius-sm)',
                    border: msg.role === 'user' ? 'none' : '2px solid var(--border-subtle)',
                    boxShadow: msg.role === 'user' ? 'none' : 'var(--shadow-sm)',
                    fontSize: '0.95rem',
                    lineHeight: 1.5,
                    maxWidth: '80%'
                  }}>
                    {formatMessage(msg.content)}
                  </div>
                </div>
              ))}
              
              {isLoading && (
                 <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                    <div style={{
                        width: '32px', height: '32px', flexShrink: 0,
                        borderRadius: 'var(--radius-sm)',
                        background: 'var(--brand-primary)',
                        border: '2px solid var(--border-subtle)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: '#000000'
                    }}>
                        <Bot size={18} />
                    </div>
                    <div style={{
                        background: 'var(--bg-surface)',
                        padding: '0.85rem 1.15rem',
                        borderRadius: 'var(--radius-sm)',
                        border: '2px solid var(--border-subtle)',
                        boxShadow: 'var(--shadow-sm)',
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        color: 'var(--text-muted)'
                    }}>
                        <Loader2 size={16} className="animate-spin" /> Thinking...
                    </div>
                 </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <form 
              onSubmit={handleSendMessage}
              style={{
                padding: '1rem',
                borderTop: '2px solid var(--border-subtle)',
                background: 'var(--bg-surface)',
                display: 'flex',
                gap: '0.75rem'
              }}
            >
              <input
                type="text"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                placeholder="Ask Vidya anything..."
                disabled={isLoading}
                style={{
                  flex: 1,
                  background: 'var(--bg-base)',
                  border: '2px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.75rem 1rem',
                  color: 'var(--text-primary)',
                  fontSize: '0.95rem',
                  outline: 'none',
                  fontFamily: 'inherit'
                }}
              />
              <motion.button
                type="submit"
                disabled={!inputMessage.trim() || isLoading}
                whileHover={inputMessage.trim() && !isLoading ? { scale: 1.05 } : {}}
                whileTap={inputMessage.trim() && !isLoading ? { scale: 0.95 } : {}}
                style={{
                  background: inputMessage.trim() && !isLoading ? 'var(--brand-primary)' : 'var(--bg-base)',
                  color: inputMessage.trim() && !isLoading ? '#000000' : 'var(--text-muted)',
                  border: '2px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  width: '48px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: inputMessage.trim() && !isLoading ? 'pointer' : 'not-allowed',
                  boxShadow: inputMessage.trim() && !isLoading ? 'var(--shadow-sm)' : 'none'
                }}
              >
                <Send size={18} style={{ marginLeft: '2px' }} />
              </motion.button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
