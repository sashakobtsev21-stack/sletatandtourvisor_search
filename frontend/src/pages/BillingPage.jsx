import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CreditCard, CheckCircle2, Infinity as InfinityIcon, Loader2 } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { apiFetch } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";

/**
 * BillingPage (#/billing) — кредитная модель: остаток поисков + пакеты на покупку.
 * Провайдер 'stub' — имитация: после checkout показываем шаг подтверждения, который дёргает
 * /confirm и сразу начисляет поиски (без денег). Для реального провайдера (Ф1) checkout вернёт
 * confirmation_url и мы сделаем redirect.
 */
export default function BillingPage() {
  const { refresh } = useAuth();
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState(null); // {payment_id, amount, credits} — ждёт подтверждения (stub)
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(0);

  const load = useCallback(async () => {
    setError("");
    const r = await apiFetch("/api/billing/status");
    if (r.ok) setStatus(await r.json());
    else setError("Не удалось получить статус");
    refresh(); // обновить счётчик в шапке
  }, [refresh]);

  useEffect(() => {
    load();
  }, [load]);

  async function checkout(plan) {
    setBusy(true);
    setError("");
    setDone(0);
    try {
      const r = await apiFetch("/api/billing/checkout", { method: "POST", body: new URLSearchParams({ plan }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Ошибка создания платежа");
      if (j.provider === "stub") setPending({ payment_id: j.payment_id, amount: j.amount, credits: j.credits });
      else if (j.confirmation_url) window.location.href = j.confirmation_url; // реальный провайдер (Ф1)
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
      setDone(pending.credits);
      setPending(null);
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

  const plans = Object.entries(status.plans || {}).sort((a, b) => a[1].credits - b[1].credits);
  const left = status.searches_left;

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
        <CreditCard className="size-5 text-brand-soft" /> Поиски и оплата
      </h1>

      <GlassCard className="p-5" as={motion.div} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        {status.local ? (
          <p className="text-sm text-muted">Локальный режим — поиски без ограничений.</p>
        ) : status.unlimited ? (
          <p className="flex items-center gap-2 text-emerald-400">
            <InfinityIcon className="size-5" /> <span className="text-ink">Без ограничений</span>{" "}
            <span className="text-muted">(администратор)</span>
          </p>
        ) : (
          <p className="text-ink">
            Осталось поисков: <span className="text-2xl font-extrabold">{left}</span>
            {left === 0 && <span className="ml-2 text-amber-300">— пополните, чтобы запускать анализ</span>}
          </p>
        )}
        {done > 0 && <p className="mt-2 text-sm text-emerald-400">Оплата прошла — начислено +{done} поисков.</p>}
      </GlassCard>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      {pending ? (
        <GlassCard className="p-5" as={motion.div} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <p className="mb-3 text-sm text-muted">
            Имитация оплаты (тестовый режим, без списания): +{pending.credits} поисков за {pending.amount} ₽.
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
        !status.unlimited && (
          <div className="grid gap-3 sm:grid-cols-2">
            {plans.map(([key, p]) => (
              <GlassCard key={key} className="flex flex-col gap-3 p-5">
                <div>
                  <div className="font-semibold text-ink">{p.title}</div>
                  <div className="text-2xl font-extrabold text-ink">
                    {p.amount} ₽{" "}
                    <span className="text-sm font-normal text-muted">
                      ({(p.amount / p.credits).toFixed(p.amount / p.credits < 10 ? 1 : 0)} ₽/поиск)
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => checkout(key)}
                  disabled={busy}
                  className="mt-auto flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean py-2.5 text-sm font-semibold text-white shadow-glow hover:opacity-95 disabled:opacity-60"
                >
                  <CreditCard className="size-4" /> Купить {p.credits} поисков
                </button>
              </GlassCard>
            ))}
          </div>
        )
      )}
    </div>
  );
}
