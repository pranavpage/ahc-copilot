"use client";

import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import {
  useAui,
  AuiProvider,
  AuiConfig,
  Suggestions,
  Tools,
} from "@assistant-ui/react";
import dynamic from "next/dynamic";
import toolkit from "./toolkit";

// The thread list loads from the server; render it on the client only (avoids a hydration mismatch).
const ThreadList = dynamic(
  () => import("@/components/assistant-ui/elements/thread-list.aui").then((m) => m.ThreadList),
  { ssr: false },
);

function ThreadWithSuggestions() {
  const aui = useAui();
  const config = AuiConfig({
    tools: Tools({ toolkit }),
    suggestions: Suggestions([
      {
        title: "WELL-0001 status",
        label: "producing? last inspection? status card",
        prompt: "Is WELL-0001 producing oil right now? When was it last inspected, and by whom? Show me its status card.",
      },
      {
        title: "Down wells in NE Block 8",
        label: "which and why, as a table",
        prompt: "Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table.",
      },
      {
        title: "Temperature chart",
        label: "WELL-0001, last 13 weeks",
        prompt: "Show a line chart of WELL-0001's wellhead temperature against air temperature for the last 13 weeks, and mark when it was not producing oil.",
      },
      {
        title: "Spill heatmap",
        label: "2026, by area and month",
        prompt: "Show a heatmap of 2026 spills by geographic area and month.",
      },
    ]),
  });
  return (
    <AuiProvider extends={aui} config={config}>
      <Thread />
    </AuiProvider>
  );
}

export default function Home() {
  return (
    <div className="flex h-dvh">
      <div className="max-w-md">
        <ThreadList />
      </div>
      <div className="flex-grow">
        <ThreadWithSuggestions />
      </div>
    </div>
  );
}
