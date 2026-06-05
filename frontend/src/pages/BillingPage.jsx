import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CreditCard, CheckCircle2, Clock, ShieldCheck, Loader2 } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { apiFetch } from "../lib/api.js";

/**
 * BillingPage (#/billing) — подписка: текущий статус + тарифы + оплата.
 * Провайдер 'stub' — имитация: после checkout показываем шаг подтверждения, который
 * дёргает /confirm и сразу продлевает подписку (без денег). Для реального провайдера (Ф1)
 * checkout вернёт confirmation_url и мы сделаем redirect.
 */
function fmt(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso.slice(0, 10) : d.toLocaleDateString("ru-RU");
}

export default function BillingPage() {
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState(null); // {payment_id, plan, amount} — ждёт подтверждения (stub)
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    setError("");
    const r = await apiFetch("/api/billing/status");
    if (r.ok) setStatus(await r.json());
    else setError("Не удалось получить статус подписки");
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function checkout(plan) {
    setBusy(true);
    setError("");
    setDone(false);
    try {
      const r = await apiFetch("/api/billing/checkout", {
        method: "POST",
        body: new URLSearchParams({ plan }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Ошибка создания платежа");
      if (j.provider === "stub") {
        setPending({ payment_id: j.payment_id, plan, amount: j.amount, days: j.days });
      } else if (j.confirmation_url) {
        window.location.href = j.confirmation_url; // реальный провайдер (Ф1)
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmStub() {
    setBusy(true);
    setError("");
    try {
      const r = await apiFetch(`/api/billing/mock/${pending.payment_id}/confirm`, { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Не удалось подтвердить оплату");
      setPending(null);
      setDone(true);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!status) {
    return (
      <div className="grid place-items-center py-20">
        <Loader2 className="size-6 animate-spin text-muted" />
      </div>
    );
  }

  const plans = Object.entries(status.plans || {});

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
        <CreditCard className="size-5 text-brand-soft" /> Подписка
      </h1>

      {/* Текущий статус */}
      <GlassCard className="p-5" as={motion.div} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        {status.local ? (
          <p className="text-sm text-muted">Локальный режим — оплата не требуется, доступ открыт.</p>
        ) : status.is_admin ? (
          <p className="flex items-center gap-2 text-sm text-emerald-400">
            <ShieldCheck className="size-4" /> Администратор — полный доступ без подписки.
          </p>
        ) : status.active ? (
          <p className="flex items-center gap-2 text-emerald-400">
            <CheckCircle2 className="size-5" />
            <span className="text-ink">Подписка активна</span>
            <span className="text-muted">— до {fmt(status.paid_until)}</span>
          </p>
        ) : (
          <p className="flex items-center gap-2 text-amber-300">
            <Clock className="size-5" />
            <span>Подписка не активна — запуск анализа недоступен. Оформите ниже.</span>
          </p>
        )}
        {done && (
          <p className="mt-2 text-sm text-emerald-400">Оплата прошла — подписка продлена.</p>
        )}
      </GlassCard>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Шаг подтверждения имитации (stub) */}
      {pending ? (
        <GlassCard className="p-5" as={motion.div} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <p className="mb-3 text-sm text-muted">
            Имитация оплаты (тестовый режим, без списания). Тариф «{status.plans[pending.plan]?.title}» —{" "}
            {pending.amount} ₽ / {pending.days} дн.
          </p>
          <div className="flex gap-2">
            <button
              onClick={confirmStub}
              disabled={busy}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean px-4 py-2.5 text-sm font-semibold text-white shadow-glow hover:opacity-95 disabled:opacity-60"
            >
              {busy ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
              Подтвердить оплату (имитация)
            </button>
            <button
              onClick={() => setPending(null)}
              disabled={busy}
              className="rounded-xl border border-white/10 px-4 py-2.5 text-sm text-muted hover:bg-white/5 hover:text-ink"
            >
              Отмена
            </button>
          </div>
        </GlassCard>
      ) : (
        !status.local &&
        !status.is_admin && (
          <div className="grid gap-3 sm:grid-cols-2">
            {plans.map(([key, p]) => (
              <GlassCard key={key} className="flex flex-col gap-3 p-5">
                <div>
                  <div className="font-semibold text-ink">{p.title}</div>
                  <div className="text-2xl font-extrabold text-ink">
                    {p.amount} ₽ <span className="text-sm font-normal text-muted">/ {p.days} дн.</span>
                  </div>
                </div>
                <button
                  onClick={() => checkout(key)}
                  disabled={busy}
                  className="mt-auto flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean py-2.5 text-sm font-semibold text-white shadow-glow hover:opacity-95 disabled:opacity-60"
                >
                  <CreditCard className="size-4" /> Оплатить
                </button>
              </GlassCard>
            ))}
          </div>
        )
      )}
    </div>
  );
}
