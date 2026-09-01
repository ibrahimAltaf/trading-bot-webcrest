import {
  EXECUTION_MODES,
  EXECUTION_MODE_LABELS,
  executionModeBadgeClass,
  type ExecutionMode,
} from "../../lib/executionMode";

type Props = {
  value: ExecutionMode;
  onChange: (mode: ExecutionMode) => void;
  disabled?: boolean;
  size?: "sm" | "md";
};

export default function ModeSelector({
  value,
  onChange,
  disabled,
  size = "md",
}: Props) {
  const btn =
    size === "sm"
      ? "h-8 rounded-lg px-2.5 text-xs"
      : "h-9 rounded-lg px-3 text-sm";

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-semibold text-slate-500">Mode</span>
      {EXECUTION_MODES.map((m) => (
        <button
          key={m}
          type="button"
          disabled={disabled}
          onClick={() => onChange(m)}
          className={`${btn} font-semibold ring-1 transition-colors disabled:opacity-50 ${
            value === m
              ? executionModeBadgeClass(m)
              : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"
          }`}
        >
          {EXECUTION_MODE_LABELS[m]}
        </button>
      ))}
    </div>
  );
}
