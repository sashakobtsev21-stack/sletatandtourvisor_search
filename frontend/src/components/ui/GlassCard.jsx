import { motion } from "framer-motion";

/**
 * GlassCard — базовая «стеклянная» карточка в стиле shadcn/ui.
 * Полупрозрачная подложка + размытие + мягкая тень и тонкая граница-блик сверху.
 *
 * props:
 *  - as: тег/компонент-обёртка (по умолчанию motion.div)
 *  - className: доп. классы
 *  - variants/initial/animate: пробрасываются в Framer Motion
 */
export default function GlassCard({
  children,
  className = "",
  as: Component = motion.div,
  ...motionProps
}) {
  return (
    <Component
      className={[
        "glass-surface relative overflow-hidden rounded-xl2 shadow-glass",
        // верхний световой блик — фирменная деталь glassmorphism
        "before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-px",
        "before:bg-gradient-to-r before:from-transparent before:via-white/40 before:to-transparent",
        className,
      ].join(" ")}
      {...motionProps}
    >
      {children}
    </Component>
  );
}
