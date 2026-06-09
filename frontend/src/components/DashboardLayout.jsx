import { m } from "framer-motion";
import { slideIn } from "../lib/animations.js";

/**
 * DashboardLayout — раскладка экрана поиска (три колонки), без шапки/фона
 * (они общие и живут в AppShell).
 *
 *  - десктоп (xl): три колонки [live | форма по центру | терминал];
 *  - планшет (lg): две колонки (live уезжает под форму);
 *  - мобайл: одна колонка, всё вертикально.
 *
 * Колонки передаются как пропсы-слоты (left / center / right).
 */
export default function DashboardLayout({ left, center, right }) {
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 xl:grid-cols-[1fr_minmax(520px,560px)_minmax(360px,440px)]">
      {/* Левая колонка — live */}
      <m.section
        variants={slideIn("left")}
        initial="hidden"
        animate="show"
        className="order-2 lg:order-1 xl:sticky xl:top-24 xl:h-[calc(100vh-7rem)] xl:self-start"
      >
        {left}
      </m.section>

      {/* Центральная колонка — форма */}
      <section className="order-1 lg:order-2 lg:col-span-1">{center}</section>

      {/* Правая колонка — прогресс + терминал */}
      <m.section
        variants={slideIn("right")}
        initial="hidden"
        animate="show"
        className="order-3 lg:col-span-2 xl:col-span-1 xl:sticky xl:top-24 xl:h-[calc(100vh-7rem)] xl:self-start"
      >
        {right}
      </m.section>
    </div>
  );
}
