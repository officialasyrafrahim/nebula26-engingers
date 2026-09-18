export type LampTone = "ok" | "warn" | "danger" | "info" | "idle";

interface SignalLampProps {
  tone: LampTone;
  label?: string;
  pulse?: boolean;
  size?: "sm" | "md";
}

// A control-panel indicator lamp. The colour carries meaning, so it is always
// paired with a visible text label by the caller.
export default function SignalLamp({
  tone,
  label,
  pulse = false,
  size = "md",
}: SignalLampProps) {
  return (
    <span
      className={`lamp lamp--${tone} lamp--${size}${pulse ? " lamp--pulse" : ""}`}
      role="img"
      aria-label={label ?? tone}
      title={label ?? tone}
    />
  );
}
