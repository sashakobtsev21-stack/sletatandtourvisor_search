import { motion } from "framer-motion";
import { fadeUp } from "../../lib/animations.js";

/**
 * Базовые стили инпута/селекта в стиле shadcn — тёмное стекло, кольцо фокуса бренда.
 * Иконка Lucide встраивается слева через absolute-позиционирование.
 */
const controlBase =
  "w-full rounded-xl border border-white/10 bg-white/[0.04] text-ink placeholder:text-muted/70 " +
  "text-sm outline-none transition-all duration-200 " +
  "focus:border-brand/60 focus:bg-white/[0.07] focus:ring-4 focus:ring-brand/20 " +
  "hover:border-white/20";

/**
 * Field — обёртка «лейбл + контрол» с иконкой и анимацией появления.
 * Каждое поле — motion-элемент c вариантом fadeUp, чтобы родитель мог
 * выстроить ступенчатое (stagger) появление всей формы.
 */
export function Field({ label, icon: Icon, htmlFor, children, className = "" }) {
  return (
    <motion.div variants={fadeUp} className={className}>
      {label && (
        <label
          htmlFor={htmlFor}
          className="mb-1.5 block text-xs font-medium tracking-wide text-muted"
        >
          {label}
        </label>
      )}
      <div className="group relative">
        {Icon && (
          <Icon
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted transition-colors group-focus-within:text-brand-soft"
            strokeWidth={2}
          />
        )}
        {children}
      </div>
    </motion.div>
  );
}

/** Текстовый / числовой инпут. icon=true добавляет левый отступ под иконку. */
export function Input({ icon = false, className = "", ...props }) {
  return (
    <input
      className={[controlBase, "py-2.5", icon ? "pl-9 pr-3" : "px-3", className].join(" ")}
      {...props}
    />
  );
}

/** Селект с кастомной стрелкой. icon=true — левый отступ под иконку. */
export function Select({ icon = false, className = "", children, ...props }) {
  return (
    <div className="relative">
      <select
        className={[
          controlBase,
          "appearance-none py-2.5 pr-9",
          icon ? "pl-9" : "pl-3",
          // тёмный фон у нативного выпадающего списка
          "[&>option]:bg-[#0c1230] [&>option]:text-ink",
          className,
        ].join(" ")}
        {...props}
      >
        {children}
      </select>
      {/* самодельная стрелка-шеврон */}
      <svg
        className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      >
        <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
