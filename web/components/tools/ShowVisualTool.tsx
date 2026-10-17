"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { Visual } from "@/components/visual/Visual";
import type { VisualBlock } from "@/components/visual/spec";

/** show_visual: the artifact is the filled block (spec + rows); the content is a summary for the model. */
export const ShowVisualToolUI: ToolCallMessagePartComponent<Record<string, unknown>, string> = ({ artifact, result, isError }) => {
  const block = artifact as (VisualBlock & { error?: string }) | undefined;
  if (!block && result == null) {
    return <div className="my-3 h-40 animate-pulse rounded-xl bg-muted" />;
  }
  if (isError || !block || block.error) {
    return (
      <p className="my-2 text-xs text-muted-foreground">
        Visual not shown: {block?.error ?? String(result ?? "no data")}
      </p>
    );
  }
  return <Visual block={block} />;
};
