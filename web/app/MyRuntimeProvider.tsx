"use client";

import { useState } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useStreamRuntime } from "@assistant-ui/react-langchain";
import { Client } from "@langchain/langgraph-sdk";
import { langGraphThreadList } from "./threadList";

export function MyRuntimeProvider({
  userId,
  children,
}: Readonly<{
  userId: string;
  children: React.ReactNode;
}>) {
  const apiUrl =
    process.env.NEXT_PUBLIC_LANGGRAPH_API_URL ||
    (typeof window !== "undefined"
      ? new URL("/api", window.location.href).href
      : undefined);

  // Stable for the life of the provider (it is keyed by user ID).
  const [threadList] = useState(() =>
    langGraphThreadList(new Client(apiUrl ? { apiUrl } : {}), userId),
  );

  const runtime = useStreamRuntime({
    assistantId: process.env.NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID!,
    apiUrl,
    unstable_threadListAdapter: threadList,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
