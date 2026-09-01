import { Link } from "react-router-dom";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import {
  executionModeBadgeClass,
  EXECUTION_MODE_LABELS,
  type ExecutionMode,
} from "../../lib/executionMode";
import {
  useExecutionModeQuery,
  useKillSwitchQuery,
} from "../../apis/safety/useSafety";

export default function ExecutionModeBadge() {
  const modeQ = useExecutionModeQuery();
  const ksQ = useKillSwitchQuery();

  const mode = (modeQ.data?.effective_mode ?? "—") as ExecutionMode | "—";
  const engaged = Boolean(ksQ.data?.kill_switch?.engaged);
  const simulated = modeQ.data?.is_simulated;

  return (
    <Link
      to="/settings"
      className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm hover:bg-slate-50"
      title="Open safety & execution settings"
    >
      {engaged ? (
        <ShieldAlert className="h-4 w-4 text-rose-600" aria-hidden />
      ) : (
        <ShieldCheck className="h-4 w-4 text-emerald-600" aria-hidden />
      )}
      <span
        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-bold ring-1 ${executionModeBadgeClass(String(mode))}`}
      >
        {mode !== "—" ? EXECUTION_MODE_LABELS[mode as ExecutionMode] ?? mode : "…"}
      </span>
      {simulated && (
        <span className="hidden text-xs text-slate-500 sm:inline">sim</span>
      )}
      {engaged && (
        <span className="text-xs font-semibold text-rose-600">KILL</span>
      )}
    </Link>
  );
}
