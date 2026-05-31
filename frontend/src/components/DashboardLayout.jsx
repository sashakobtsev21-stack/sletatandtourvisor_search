import { motion } from "framer-motion";
import { Palmtree } from "lucide-react";
import { slideIn, fadeUp } from "../lib/animations.js";

/**
 * DashboardLayout — каркас дашборда.
 *
 * Раскладка (CSS Grid):
 *  - десктоп (xl): три колонки [live | форма по центру | терминал];
 *  - планшет (lg): две колонки (live уезжает под форму);
 *  - мобайл: одна колонка, всё вертикально.
 *
 * Колонки передаются как пропсы-слоты (left / center / right), чтобы layout
 * не знал о логике конкретных панелей и легко переиспользовался/тестировался.
 *
 * Декоративные «плавающие пятна» фона объявлены здесь, чтобы glassmorphism
 * имел сквозь что просвечивать.
 */
export default function DashboardLayout({ left, center, right }) {
  return (
    <div className="relative min-h-screen">
      {/* Анимированный градиентный фон путешествий (мягкие световые пятна) */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 size-[42rem] animate-floatA rounded-full bg-brand/25 blur-[120px]" />
        <div className="absolute -right-40 top-1/4 size-[38rem] animate-floatB rounded-full bg-ocean/20 blur-[120px]" />
        <div className="absolute -bottom-48 left-1/3 size-[40rem] animate-floatA rounded-full bg-violet-500/15 blur-[120px]" />
      </div>

      {/* Шапка */}
      <motion.header
        variants={fadeUp}
        initial="hidden"
        animate="show"
        className="glass-surface sticky top-0 z-30 border-x-0 border-t-0"
      >
        <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-3 px-5">
          <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
            <Palmtree className="size-5 text-white" />
          </span>
          <div className="flex items-baseline gap-2">
            <span className="bg-gradient-to-r from-brand-soft to-ocean bg-clip-text text-lg font-extrabold tracking-tight text-transparent">
              ТурСравнение
            </span>
            <span className="hidden text-xs text-muted sm:inline">live-агрегатор туров</span>
          </div>
          <nav className="ml-auto flex items-center gap-1 text-sm font-semibold text-muted">
            {["Поиск", "История", "Автотесты"].map((item, i) => (
              <a
                key={item}
                href="#"
                className={`rounded-lg px-3 py-2 transition-colors hover:bg-white/5 hover:text-ink ${i === 0 ? "text-ink" : ""}`}
              >
                {item}
              </a>
            ))}
          </nav>
        </div>
      </motion.header>

      {/* Сетка трёх колонок */}
      <main className="mx-auto max-w-[1800px] px-4 py-6 md:px-6">
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2 xl:grid-cols-[1fr_minmax(520px,560px)_minmax(360px,440px)]">
          {/* Левая колонка — live */}
          <motion.section
            variants={slideIn("left")}
            initial="hidden"
            animate="show"
            className="order-2 lg:order-1 xl:sticky xl:top-24 xl:h-[calc(100vh-7rem)] xl:self-start"
          >
            {left}
          </motion.section>

          {/* Центральная колонка — форма (на десктопе всегда по центру) */}
          <section className="order-1 lg:order-2 lg:col-span-1">{center}</section>

          {/* Правая колонка — прогресс + терминал */}
          <motion.section
            variants={slideIn("right")}
            initial="hidden"
            animate="show"
            className="order-3 lg:col-span-2 xl:col-span-1 xl:sticky xl:top-24 xl:h-[calc(100vh-7rem)] xl:self-start"
          >
            {right}
          </motion.section>
        </div>
      </main>
    </div>
  );
}
