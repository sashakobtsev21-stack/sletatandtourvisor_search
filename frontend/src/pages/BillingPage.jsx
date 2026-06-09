import { useCallback, useEffect, useState } from "react";
import { m } from "framer-motion";
import { CreditCard, CheckCircle2, Infinity as InfinityIcon, CalendarClock, Loader2 } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import { apiFetch } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";

/**
 * BillingPage (#/billing) — гибрид: ПОДПИСКА (безлимит на срок) + ПАКЕТЫ поисков (кредиты).
 * Провайдер 'stub' — имитация: checkout → шаг подтверждения → начисление (поиски или подписка).
 * Реальный провайдер (позже) → redirect на confirmation_url.
 */
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso.slice(0, 10) : d.toLocaleDateString("ru-RU");
}

export default function BillingPage() {
  const { refresh } = useAuth();
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState(null); // {payment_id, kind, title, amount, credits, days}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [doneMsg, setDoneMsg] = useState("");

  const load = useCallback(async () => {
    setError("");
    const r = await apiFetch("/api/billing/status");
    if (r.ok) setStatus(await r.json());
    else setError("Не удалось получить статус");
    refresh();
  }, [refresh]);

  useEffect(() => {
    load();
  }, [load]);

  async function checkout(plan) {
    setBusy(true);
    setError("");
    setDoneMsg("");
    try {
      const r = await apiFetch("/api/billing/checkout", { method: "POST", body: new URLSearchParams({ plan }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Ошибка создания платежа");
      if (j.provider === "stub") setPending(j);
      else if (j.confirmation_url) window.location.href = j.confirmation_url;
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
      setDoneMsg(j.kind === "subscription" ? `Подписка активирована на ${j.days} дн.` : `Начислено +${j.credits} поисков.`);
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

  const entries = Object.entries(status.plans || {});
  const subPlans = entries.filter(([, p]) => p.kind === "subscription");
  const creditPlans = entries.filter(([, p]) => p.kind === "credits").sort((a, b) => a[1].credits - b[1].credits);
  const showBuy = !status.local && !status.is_admin;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
        <CreditCard className="size-5 text-brand-soft" /> Поиски и оплата
      </h1>

      <GlassCard className="p-5" as={m.div} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        {status.local ? (
          <p className="text-sm text-muted">Локальный режим — поиски без ограничений.</p>
        ) : status.is_admin ? (
          <p className="flex items-center gap-2 text-emerald-400">
            <InfinityIcon className="size-5" /> <span className="text-ink">Без ограничений</span>{" "}
            <span className="text-muted">(администратор)</span>
          </p>
        ) : status.subscription_active ? (
          <p className="flex items-center gap-2 text-emerald-400">
            <CalendarClock className="size-5" />
            <span className="text-ink">Подписка активна</span>
            <span className="text-muted">— безлимит до {fmtDate(status.subscription_until)}</span>
          </p>
        ) : (
          <p className="text-ink">
            Осталось поисков: <span className="text-2xl font-extrabold">{status.searches_left}</span>
            {status.searches_left === 0 && <span className="ml-2 text-amber-300">— оформите подписку или пакет</span>}
          </p>
        )}
        {doneMsg && <p className="mt-2 text-sm text-emerald-400">Оплата прошла — {doneMsg}</p>}
      </GlassCard>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>
      )}

      {pending ? (
        <GlassCard className="p-5" as={m.div} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <p className="mb-3 text-sm text-muted">
            Имитация оплаты (тестовый режим, без списания):{" "}
            {pending.kind === "subscription"
              ? `${pending.title} (${pending.days} дн.)`
              : `+${pending.credits} поисков`}{" "}
            за {pending.amount} ₽.
          </p>
          <div className="flex gap-2">
            <button onClick={confirmStub} disabled={busy}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean px-4 py-2.5 text-sm font-semibold text-white shadow-glow hover:opacity-95 disabled:opacity-60">
              {busy ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
              Подтвердить оплату (имитация)
            </button>
            <button onClick={() => setPending(null)} disabled={busy}
              className="rounded-xl border border-white/10 px-4 py-2.5 text-sm text-muted hover:bg-white/5 hover:text-ink">
              Отмена
            </button>
          </div>
        </GlassCard>
      ) : (
        showBuy && (
          <>
            {/* Подписка (flat-fee, безлимит) */}
            <div>
              <div className="mb-2 text-sm font-semibold text-muted">Подписка — безлимит поисков</div>
              <div className="grid gap-3 sm:grid-cols-2">
                {subPlans.map(([key, p]) => (
                  <GlassCard key={key} className="flex flex-col gap-3 p-5">
                    <div>
                      <div className="font-semibold text-ink">{p.title}</div>
                      <div className="text-2xl font-extrabold text-ink">{p.amount} ₽</div>
                    </div>
                    <button onClick={() => checkout(key)} disabled={busy}
                      className="mt-auto flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-ocean py-2.5 text-sm font-semibold text-white shadow-glow hover:opacity-95 disabled:opacity-60">
                      <CalendarClock className="size-4" /> Оформить
                    </button>
                  </GlassCard>
                ))}
              </div>
            </div>

            {/* Пакеты поисков (кредиты, pay-as-you-go) */}
            <div>
              <div className="mb-2 text-sm font-semibold text-muted">Пакеты поисков — разовая оплата</div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {creditPlans.map(([key, p]) => (
                  <GlassCard key={key} className="flex flex-col gap-3 p-4">
                    <div>
                      <div className="text-sm font-semibold text-ink">{p.credits} поисков</div>
                      <div className="text-xl font-extrabold text-ink">{p.amount} ₽</div>
                      <div className="text-xs text-muted">{(p.amount / p.credits).toFixed(p.amount / p.credits < 10 ? 1 : 0)} ₽/поиск</div>
                    </div>
                    <button onClick={() => checkout(key)} disabled={busy}
                      className="mt-auto flex items-center justify-center gap-1.5 rounded-xl border border-white/10 py-2 text-sm font-semibold text-ink hover:bg-white/5 disabled:opacity-60">
                      <CreditCard className="size-4" /> Купить
                    </button>
                  </GlassCard>
                ))}
              </div>
            </div>
          </>
        )
      )}
    </div>
  );
}
