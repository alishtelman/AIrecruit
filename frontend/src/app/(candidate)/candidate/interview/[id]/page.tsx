"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { interviewApi } from "@/lib/api";
import type { InterviewDetail, InterviewMessage } from "@/lib/types";

export default function InterviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { loading: authLoading } = useAuth();

  const [interview, setInterview] = useState<InterviewDetail | null>(null);
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [questionCount, setQuestionCount] = useState(0);
  const [maxQuestions, setMaxQuestions] = useState(8);
  const [currentQuestion, setCurrentQuestion] = useState<string | null>(null);
  const [canFinish, setCanFinish] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load interview on mount
  useEffect(() => {
    if (!id || authLoading) return;
    interviewApi
      .getDetail(id)
      .then((data) => {
        setInterview(data);
        setMessages(data.messages.filter((m) => m.role !== "system"));
        setQuestionCount(data.question_count);
        setMaxQuestions(data.max_questions);

        if (data.status === "report_generated" && data.report_id) {
          router.replace(`/candidate/reports/${data.report_id}`);
          return;
        }

        // Derive current question (last assistant message)
        const lastAssistant = [...data.messages]
          .reverse()
          .find((m) => m.role === "assistant");
        const lastMsg = data.messages[data.messages.length - 1];
        const waitingForAnswer = lastMsg?.role === "assistant";

        if (
          data.question_count >= data.max_questions &&
          lastMsg?.role === "candidate"
        ) {
          setCanFinish(true);
          setCurrentQuestion(null);
        } else if (waitingForAnswer && lastAssistant) {
          setCurrentQuestion(lastAssistant.content);
        }
      })
      .catch(() => setError("Could not load interview"));
  }, [id, authLoading, router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    if (!input.trim() || sending || !id) return;
    const text = input.trim();
    setInput("");
    setSending(true);
    setError("");

    // Optimistic: add candidate message immediately
    const optimistic: InterviewMessage = {
      role: "candidate",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);

    try {
      const res = await interviewApi.sendMessage(id, { message: text });
      setQuestionCount(res.question_count);
      setCurrentQuestion(res.current_question);

      if (res.current_question) {
        const aiMsg: InterviewMessage = {
          role: "assistant",
          content: res.current_question,
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, aiMsg]);
        setCanFinish(false);
      } else {
        // No more questions — ready to finish
        setCanFinish(true);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to send message");
      // Remove optimistic message on error
      setMessages((prev) => prev.slice(0, -1));
      setInput(text);
    } finally {
      setSending(false);
    }
  }

  async function handleFinish() {
    if (!id || finishing) return;
    setFinishing(true);
    setError("");
    try {
      const res = await interviewApi.finish(id);
      router.push(`/candidate/reports/${res.report_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to finish interview");
      setFinishing(false);
    }
  }

  if (authLoading || !interview) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-slate-400">{error || "Loading interview…"}</div>
      </div>
    );
  }

  const roleLabel = interview.target_role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const progress = Math.round((questionCount / maxQuestions) * 100);

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-800 px-6 py-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <Link href="/candidate/reports" className="text-slate-500 hover:text-slate-300 text-sm transition-colors">
            ←
          </Link>
          <div>
            <span className="text-white font-semibold">{roleLabel} Interview</span>
            <span className="text-slate-400 text-sm ml-3">
              Question {questionCount} of {maxQuestions}
            </span>
          </div>
        </div>
        {/* Progress bar */}
        <div className="w-32 h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-2xl w-full mx-auto">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "candidate" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "candidate"
                  ? "bg-blue-600 text-white rounded-br-sm"
                  : "bg-slate-800 border border-slate-700 text-slate-100 rounded-bl-sm"
              }`}
            >
              {msg.role === "assistant" && (
                <div className="text-blue-400 text-xs font-medium mb-1 uppercase tracking-wide">AI Interviewer</div>
              )}
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Error */}
      {error && (
        <div className="max-w-2xl w-full mx-auto px-4">
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3 mb-3">
            {error}
          </div>
        </div>
      )}

      {/* Finish CTA */}
      {canFinish && (
        <div className="max-w-2xl w-full mx-auto px-4 pb-4">
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-5 text-center">
            <div className="text-white font-semibold mb-1">Interview complete!</div>
            <div className="text-slate-400 text-sm mb-4">
              You've answered all {maxQuestions} questions. Generate your assessment report now.
            </div>
            <button
              onClick={handleFinish}
              disabled={finishing}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold px-8 py-2.5 rounded-lg transition-colors"
            >
              {finishing ? "Generating report…" : "Finish & Get Report"}
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      {!canFinish && interview.status === "in_progress" && (
        <div className="border-t border-slate-800 px-4 py-4 shrink-0">
          <div className="max-w-2xl mx-auto flex gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Type your answer… (Enter to send, Shift+Enter for new line)"
              rows={2}
              className="flex-1 bg-slate-800 border border-slate-700 text-white rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-slate-500 resize-none"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 rounded-xl transition-colors font-medium"
            >
              {sending ? "…" : "Send"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
