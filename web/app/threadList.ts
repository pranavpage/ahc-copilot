import type { RemoteThreadListAdapter } from "@assistant-ui/react";
import type { Client, Thread } from "@langchain/langgraph-sdk";
import { createAssistantStream } from "assistant-stream";

// The thread list, kept on the LangGraph server: each thread carries `user_id` and `title` in its
// metadata, so a reload (or a seeded demo, see scripts/seed_demo.py) shows the same list. A thread
// is named after its first user message.

const TITLE_MAX = 120;

type Content = string | readonly { type: string; text?: string }[] | undefined;

function textOf(content: Content): string {
  const text =
    typeof content === "string"
      ? content
      : (content ?? []).map((p) => (p.type === "text" ? (p.text ?? "") : "")).join(" ");
  return text.replace(/\s+/g, " ").trim().slice(0, TITLE_MAX);
}

function firstUserText(messages: readonly { type?: string; role?: string; content: Content }[]) {
  const first = messages.find((m) => m.role === "user" || m.type === "human");
  return first ? textOf(first.content) : "";
}

function toMetadata(t: Thread) {
  const meta = (t.metadata ?? {}) as { title?: string; archived?: boolean };
  const values = t.values as { messages?: { type?: string; content: Content }[] } | undefined;
  return {
    status: meta.archived ? ("archived" as const) : ("regular" as const),
    remoteId: t.thread_id,
    externalId: t.thread_id,
    title: meta.title || firstUserText(values?.messages ?? []) || undefined,
    lastMessageAt: new Date(t.updated_at),
  };
}

export function langGraphThreadList(client: Client, userId: string): RemoteThreadListAdapter {
  const setMeta = (id: string, metadata: Record<string, unknown>) =>
    client.threads.update(id, { metadata }).then(() => undefined);

  return {
    async list() {
      const threads = await client.threads.search({
        metadata: { user_id: userId },
        limit: 100,
        sortBy: "updated_at",
        sortOrder: "desc",
      });
      // Threads that never got a message are left out.
      return { threads: threads.map(toMetadata).filter((t) => t.title) };
    },
    async initialize() {
      const { thread_id } = await client.threads.create({ metadata: { user_id: userId } });
      return { remoteId: thread_id, externalId: thread_id };
    },
    async fetch(id) {
      return toMetadata(await client.threads.get(id));
    },
    rename: (id, title) => setMeta(id, { title }),
    archive: (id) => setMeta(id, { archived: true }),
    unarchive: (id) => setMeta(id, { archived: false }),
    delete: (id) => client.threads.delete(id),
    async generateTitle(id, messages) {
      const title = firstUserText(messages);
      if (title) await setMeta(id, { title });
      return createAssistantStream((c) => {
        if (title) c.appendText(title);
      });
    },
  };
}
