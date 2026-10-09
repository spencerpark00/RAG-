// shadcn/ui 스타일의 작은 기본 부품. 외부 컴포넌트 라이브러리 없이 Tailwind 클래스로만 만든다.
import type { ButtonHTMLAttributes, ReactNode } from "react";

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");

type Variant = "primary" | "outline" | "ghost";
export function Button({
  variant = "outline",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "icon" }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors whitespace-nowrap",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:opacity-40 disabled:pointer-events-none cursor-pointer",
        variant === "primary" && "bg-brand text-white hover:opacity-90 dark:text-canvas",
        variant === "outline" && "border border-line bg-surface hover:bg-subtle",
        variant === "ghost" && "text-muted hover:bg-subtle hover:text-ink",
        size === "sm" && "h-7 px-2 text-xs",
        size === "md" && "h-9 px-3 text-sm",
        size === "icon" && "h-9 w-9",
        className,
      )}
      {...props}
    />
  );
}

export function StatusBadge({ status }: { status: string }) {
  if (status === "현행") return <Badge tone="ok">현행</Badge>;
  if (status === "폐지") return <Badge tone="bad">폐지</Badge>;
  return <Badge tone="neutral">상태 미표기</Badge>;
}

export function Badge({ tone, children }: { tone: "ok" | "bad" | "neutral" | "brand"; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-px text-[11.5px] font-semibold",
        tone === "ok" && "bg-ok-soft text-ok",
        tone === "bad" && "bg-bad-soft text-bad",
        tone === "neutral" && "bg-subtle text-muted",
        tone === "brand" && "bg-brand-soft text-brand",
      )}
    >
      {children}
    </span>
  );
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <div
      className="grid shrink-0 place-items-center rounded-[9px] bg-gradient-to-br from-[#3a5ccc] to-[#8b5cf6] font-extrabold text-white"
      style={{ width: size, height: size, fontSize: size * 0.48 }}
    >
      한
    </div>
  );
}

export { cx };
