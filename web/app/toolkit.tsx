"use generative";

import { defineToolkit, externalTool } from "@assistant-ui/react";
import { ShowVisualToolUI } from "@/components/tools/ShowVisualTool";

// Tools run in the LangGraph server; the UI only renders them. Data tools use the default view.
export default defineToolkit({
  show_visual: {
    execute: externalTool(),
    render: ShowVisualToolUI,
  },
});
