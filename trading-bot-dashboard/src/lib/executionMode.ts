/** Matches backend ExecutionMode for query params and UI. */
export type ExecutionMode = "live" | "paper" | "shadow" | "backtest";

export const EXECUTION_MODES: ExecutionMode[] = [
  "paper",
  "shadow",
  "live",
];

export const EXECUTION_MODE_LABELS: Record<ExecutionMode, string> = {
  paper: "Paper",
  shadow: "Shadow",
  live: "Live",
  backtest: "Backtest",
};

export function executionModeBadgeClass(mode: string): string {
  switch (mode) {
    case "live":
      return "bg-rose-50 text-rose-700 ring-rose-200";
    case "shadow":
      return "bg-violet-50 text-violet-700 ring-violet-200";
    case "paper":
      return "bg-sky-50 text-sky-700 ring-sky-200";
    default:
      return "bg-slate-100 text-slate-700 ring-slate-200";
  }
}
