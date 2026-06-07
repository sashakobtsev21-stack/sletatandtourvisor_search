import { motion } from "framer-motion";
import {
  Palmtree, Search, Layers, Zap, TrendingDown, Trophy, Globe2, Clock,
  Check, ArrowRight, ShieldCheck, Sparkles, LogIn, Gauge,
} from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { fadeUp, staggerContainer } from "../lib/animations.js";
import { navigate } from "../lib/router.js";

/**
 * LandingPage — публичная продающая страница (показывается гостю на корне «/»).
 * Структура: hero → площадки → выгоды → как это работает → тарифы → финальный CTA → футер.
 * CTA ведут в приложение (#/search — попробовать гостем) или к регистрации/входу.
 * Стиль — тот же glassmorphism, что во всём дашборде (бренд-градиенты, GlassCard, framer-motion).
 */

const PLATFORMS = ["Слетать.ру", "Турвизор", "Travelata", "Level.Travel", "Островок"];

const BENEFITS = [
  { icon: Layers, title: "Один поиск вместо пяти вкладок",
    text: "Запрос уходит сразу на 5 систем параллельно. Не нужно вручную открывать и сравнивать каждую — всё в одном окне." },
  { icon: TrendingDown, title: "Видно, где дешевле",
    text: "По каждой площадке — лучший оператор, отель и цена. Сразу понятно, где выгоднее забронировать для клиента." },
  { icon: Globe2, title: "Батч по многим направлениям",
    text: "Запустите сравнение сразу по десяткам стран — анализ идёт в фоне, по готовности приходит уведомление." },
  { icon: Zap, title: "Скорость и операторы",
    text: "Живой прогресс по каждой площадке, кто из туроператоров ответил и у кого есть туры — со скриншотами выдачи." },
];

const STEPS = [
  { icon: Search, title: "Задайте параметры", text: "Направление, даты, состав туристов, фильтры по операторам и звёздности." },
  { icon: Gauge, title: "Запустите сравнение", text: "5 площадок ищут параллельно — виден живой прогресс и трансляция выдачи." },
  { icon: Trophy, title: "Получите лучший вариант", text: "Оператор, отель и цена по каждой системе + ссылка и скриншот для проверки." },
];

// Тарифы — держать в синхроне с billing.py (CREDIT_PLANS / SUB_PLANS / FREE_CREDITS / ANON_CREDITS).
const PACKS = [
  { credits: 30, price: 499 },
  { credits: 100, price: 999 },
  { credits: 500, price: 1999, popular: true },
  { credits: 1000, price: 2999 },
];

const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

export default function LandingPage() {
  return (
    <div className="relative min-h-screen overflow-x-hidden">
      {/* Анимированный фон — фирменные световые пятна */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 size-[44rem] animate-floatA rounded-full bg-brand/25 blur-[130px]" />
        <div className="absolute -right-40 top-1/4 size-[40rem] animate-floatB rounded-full bg-ocean/20 blur-[130px]" />
        <div className="absolute -bottom-56 left-1/3 size-[42rem] animate-floatA rounded-full bg-violet-500/15 blur-[130px]" />
      </div>

      {/* Шапка */}
      <header className="glass-surface sticky top-0 z-30 border-x-0 border-t-0">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-5">
          <button onClick={() => scrollTo("top")} className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
              <Palmtree className="size-5 text-white" />
            </span>
            <span className="bg-gradient-to-r from-brand-soft to-ocean bg-clip-text text-lg font-extrabold tracking-tight text-transparent">
              Tour Search
            </span>
          </button>
          <nav className="ml-auto hidden items-center gap-1 text-sm font-semibold text-muted md:flex">
            <button onClick={() => scrollTo("features")} className="rounded-lg px-3 py-2 transition-colors hover:bg-white/5 hover:text-ink">Возможности</button>
            <button onClick={() => scrollTo("how")} className="rounded-lg px-3 py-2 transition-colors hover:bg-white/5 hover:text-ink">Как это работает</button>
            <button onClick={() => scrollTo("pricing")} className="rounded-lg px-3 py-2 transition-colors hover:bg-white/5 hover:text-ink">Тарифы</button>
          </nav>
          <button onClick={() => navigate("/login")} className="ml-2 flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold text-muted transition-colors hover:bg-white/5 hover:text-ink">
            <LogIn className="size-4" /> Войти
          </button>
          <button onClick={() => navigate("/search")} className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-brand to-ocean px-3.5 py-2 text-sm font-semibold text-white shadow-glow transition-opacity hover:opacity-95">
            Попробовать <ArrowRight className="size-4" />
          </button>
        </div>
      </header>

      <main id="top" className="mx-auto max-w-6xl px-5">
        {/* HERO */}
        <motion.section variants={staggerContainer} initial="hidden" animate="show" className="py-16 text-center md:py-24">
          <motion.div variants={fadeUp} className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-4 py-1.5 text-xs font-semibold text-muted">
            <Sparkles className="size-3.5 text-brand-soft" /> Агрегатор поиска туров для агентств и операторов
          </motion.div>
          <motion.h1 variants={fadeUp} className="mx-auto max-w-4xl text-4xl font-extrabold leading-tight tracking-tight text-white md:text-6xl">
            Сравните туры по{" "}
            <span className="bg-gradient-to-r from-brand-soft via-brand to-ocean bg-clip-text text-transparent">5 системам</span>{" "}
            за один поиск
          </motion.h1>
          <motion.p variants={fadeUp} className="mx-auto mt-5 max-w-2xl text-lg text-muted">
            Слетать.ру, Турвизор, Travelata, Level.Travel и Островок — в одном окне. Находите
            лучшую цену, оператора и отель быстрее, чем открываете пять вкладок.
          </motion.p>
          <motion.div variants={fadeUp} className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <button onClick={() => navigate("/search")} className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand-deep via-brand to-ocean px-6 py-3.5 text-base font-bold text-white shadow-glow transition-transform hover:scale-[1.02]">
              Попробовать бесплатно <ArrowRight className="size-5" />
            </button>
            <button onClick={() => scrollTo("pricing")} className="rounded-xl border border-white/10 bg-white/[0.04] px-6 py-3.5 text-base font-semibold text-ink transition-colors hover:bg-white/[0.08]">
              Смотреть тарифы
            </button>
          </motion.div>
          <motion.p variants={fadeUp} className="mt-4 flex items-center justify-center gap-1.5 text-sm text-muted">
            <ShieldCheck className="size-4 text-emerald-400" /> 2 поиска бесплатно — без регистрации
          </motion.p>
        </motion.section>

        {/* Площадки */}
        <section className="pb-8">
          <p className="mb-4 text-center text-xs font-semibold uppercase tracking-wider text-muted/70">Сравниваем выдачу систем</p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {PLATFORMS.map((p) => (
              <span key={p} className="rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-semibold text-ink">{p}</span>
            ))}
          </div>
        </section>

        {/* Выгоды */}
        <section id="features" className="scroll-mt-20 py-16">
          <SectionHead eyebrow="Возможности" title="Почему это быстрее и выгоднее" />
          <motion.div variants={staggerContainer} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} className="grid gap-5 sm:grid-cols-2">
            {BENEFITS.map(({ icon: Icon, title, text }) => (
              <GlassCard key={title} variants={fadeUp} className="p-6">
                <span className="mb-4 grid size-11 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
                  <Icon className="size-5 text-white" />
                </span>
                <h3 className="mb-1.5 text-lg font-bold text-white">{title}</h3>
                <p className="text-sm leading-relaxed text-muted">{text}</p>
              </GlassCard>
            ))}
          </motion.div>
        </section>

        {/* Как это работает */}
        <section id="how" className="scroll-mt-20 py-16">
          <SectionHead eyebrow="Как это работает" title="Три шага до лучшей цены" />
          <motion.div variants={staggerContainer} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} className="grid gap-5 md:grid-cols-3">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <GlassCard key={title} variants={fadeUp} className="p-6">
                <div className="mb-3 flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-lg border border-white/10 bg-white/[0.04] text-sm font-bold text-brand-soft">{i + 1}</span>
                  <Icon className="size-5 text-ocean" />
                </div>
                <h3 className="mb-1.5 text-base font-bold text-white">{title}</h3>
                <p className="text-sm leading-relaxed text-muted">{text}</p>
              </GlassCard>
            ))}
          </motion.div>
        </section>

        {/* Тарифы */}
        <section id="pricing" className="scroll-mt-20 py-16">
          <SectionHead eyebrow="Тарифы" title="Платите за поиски — или берите безлимит" />

          <div className="grid gap-5 md:grid-cols-2">
            {/* Бесплатно */}
            <GlassCard initial="hidden" whileInView="show" viewport={{ once: true }} variants={fadeUp} className="flex flex-col p-6">
              <div className="text-sm font-semibold text-muted">Для старта</div>
              <div className="mt-1 text-3xl font-extrabold text-white">Бесплатно</div>
              <ul className="mt-4 space-y-2 text-sm text-muted">
                <Li>2 поиска без регистрации</Li>
                <Li>5 поисков после регистрации</Li>
                <Li>Все 5 площадок и сравнение</Li>
              </ul>
              <button onClick={() => navigate("/register")} className="mt-6 rounded-xl border border-white/10 bg-white/[0.05] py-3 text-sm font-semibold text-ink transition-colors hover:bg-white/[0.09]">
                Зарегистрироваться
              </button>
            </GlassCard>

            {/* Подписка */}
            <GlassCard initial="hidden" whileInView="show" viewport={{ once: true }} variants={fadeUp} className="flex flex-col p-6 ring-1 ring-brand/30">
              <div className="flex items-center gap-2 text-sm font-semibold text-brand-soft">
                <Sparkles className="size-4" /> Подписка — безлимит
              </div>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-white">1 490 ₽</span>
                <span className="text-sm text-muted">/ месяц</span>
              </div>
              <ul className="mt-4 space-y-2 text-sm text-muted">
                <Li>Безлимитные поиски на весь срок</Li>
                <Li>Батч по многим направлениям</Li>
                <Li>Год — 14 900 ₽ (2 месяца в подарок)</Li>
              </ul>
              <button onClick={() => navigate("/register")} className="mt-6 rounded-xl bg-gradient-to-r from-brand to-ocean py-3 text-sm font-bold text-white shadow-glow transition-opacity hover:opacity-95">
                Оформить подписку
              </button>
            </GlassCard>
          </div>

          {/* Пакеты поисков */}
          <div className="mt-6">
            <div className="mb-3 text-center text-sm font-semibold text-muted">Или разовые пакеты поисков</div>
            <motion.div variants={staggerContainer} initial="hidden" whileInView="show" viewport={{ once: true }} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {PACKS.map(({ credits, price, popular }) => (
                <GlassCard key={credits} variants={fadeUp} className={`relative p-5 text-center ${popular ? "ring-1 ring-ocean/40" : ""}`}>
                  {popular && (
                    <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full bg-ocean px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                      выгодно
                    </span>
                  )}
                  <div className="text-2xl font-extrabold text-white">{credits}</div>
                  <div className="text-xs text-muted">поисков</div>
                  <div className="mt-3 text-lg font-bold text-ink">{price.toLocaleString("ru-RU")} ₽</div>
                  <div className="text-[11px] text-muted">≈ {Math.round(price / credits)} ₽ / поиск</div>
                  <button onClick={() => navigate("/register")} className="mt-4 w-full rounded-lg border border-white/10 bg-white/[0.05] py-2 text-xs font-semibold text-ink transition-colors hover:bg-white/[0.09]">
                    Выбрать
                  </button>
                </GlassCard>
              ))}
            </motion.div>
          </div>
        </section>

        {/* Финальный CTA */}
        <section className="py-16">
          <GlassCard initial="hidden" whileInView="show" viewport={{ once: true }} variants={fadeUp} className="overflow-hidden p-10 text-center">
            <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-brand/10 via-transparent to-ocean/10" />
            <Clock className="mx-auto mb-4 size-8 text-brand-soft" />
            <h2 className="text-2xl font-extrabold text-white md:text-3xl">Перестаньте сравнивать вручную</h2>
            <p className="mx-auto mt-3 max-w-xl text-muted">Один запрос — пять систем — лучшая цена. Первые 2 поиска бесплатно, без регистрации.</p>
            <button onClick={() => navigate("/search")} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand-deep via-brand to-ocean px-7 py-3.5 text-base font-bold text-white shadow-glow transition-transform hover:scale-[1.02]">
              Попробовать бесплатно <ArrowRight className="size-5" />
            </button>
          </GlassCard>
        </section>
      </main>

      {/* Футер */}
      <footer className="border-t border-white/5">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-5 py-6 text-sm text-muted sm:flex-row">
          <div className="flex items-center gap-2">
            <Palmtree className="size-4 text-brand-soft" /> Tour Search · сравнение туров по 5 системам
          </div>
          <div className="flex items-center gap-4 text-xs">
            <button onClick={() => navigate("/login")} className="hover:text-ink">Войти</button>
            <button onClick={() => navigate("/register")} className="hover:text-ink">Регистрация</button>
            <span className="text-muted/50">© Александр Кобцев</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function SectionHead({ eyebrow, title }) {
  return (
    <motion.div initial="hidden" whileInView="show" viewport={{ once: true }} variants={staggerContainer} className="mb-8 text-center">
      <motion.div variants={fadeUp} className="mb-2 text-xs font-semibold uppercase tracking-wider text-brand-soft">{eyebrow}</motion.div>
      <motion.h2 variants={fadeUp} className="text-2xl font-extrabold tracking-tight text-white md:text-3xl">{title}</motion.h2>
    </motion.div>
  );
}

function Li({ children }) {
  return (
    <li className="flex items-start gap-2">
      <Check className="mt-0.5 size-4 shrink-0 text-emerald-400" />
      <span>{children}</span>
    </li>
  );
}
