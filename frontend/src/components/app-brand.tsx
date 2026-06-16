"use client";

type AppBrandProps = {
  workspaceLabel?: string;
  compact?: boolean;
};

export function AppBrand({ workspaceLabel, compact = false }: AppBrandProps) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#2F5BEA]/15 font-manrope text-xs font-bold tracking-[0.16em] text-[#7E9BFF]">
        AI
      </div>
      {!compact && (
        <div className="leading-tight">
          <div className="font-manrope text-sm font-bold text-white">AI HR</div>
          {workspaceLabel && (
            <div className="text-[9.5px] font-semibold uppercase tracking-widest text-[#7f8595]">
              {workspaceLabel}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
