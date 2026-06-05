import { useState } from "react";
import { Layers, Info } from "lucide-react";
import GlassCard from "../components/ui/GlassCard.jsx";
import SearchForm from "../components/SearchForm.jsx";
import { apiFetch } from "../lib/api.js";
import { navigate } from "../lib/router.js";

/**
 * BatchPage (#/batch) — запуск батч-анализа: один набор параметров, много направлений.
 * Переиспользует SearchForm в режиме batch (мультивыбор стран чипами). По сабмиту
 * создаёт фоновое задание (POST /api/jobs) и уходит на страницу прогресса #/jobs/{id}.
 */
export default function BatchPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (payload) => {
    setBusy(true);
    setError("");
    const fd = new FormData();
    fd.append("mode", payload.mode);
    fd.append("departure_city", payload.departure_city ?? "Москва");
    (payload.destinations ?? []).forEach((d) => fd.append("destination", d));
    fd.append("date_from", payload.date_from);
    fd.append("date_to", payload.date_to);
    fd.append("nights_min", payload.nights_min);
    fd.append("nights_max", payload.nights_max);
    fd.append("adults", payload.adults);
    (payload.child_ages ?? []).forEach((a) => fd.append("child_age", a));
    (payload.operators ?? []).forEach((o) => fd.append("operator", o));
    (payload.providers ?? []).forEach((p) => fd.append("provider", p));
    if (payload.price_max) fd.append("price_max", payload.price_max);
    if (payload.charter_only) fd.append("charter_only", "on");
    if (payload.direct_only) fd.append("direct_only", "on");

    try {
      const resp = await apiFetch("/api/jobs", { method: "POST", body: fd });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setError(data.error || "Не удалось запустить анализ.");
        setBusy(false);
        return;
      }
      navigate(`/jobs/${data.job_id}`); // на страницу прогресса
    } catch (e) {
      setError(`Не удалось связаться с бэкендом: ${e}`);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <GlassCard className="flex items-start gap-3 p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand to-ocean shadow-glow">
          <Layers className="size-5 text-white" />
        </span>
        <div className="text-sm text-muted">
          <div className="font-semibold text-ink">Анализ по многим направлениям</div>
          Выберите минимум 2 страны — поиск пойдёт в фоне по каждой, прогресс увидите на
          странице анализа. Каждое направление расходует 1 поиск.
        </div>
      </GlassCard>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <Info className="size-4 shrink-0" /> {error}
        </div>
      )}

      <SearchForm batch onSubmit={handleSubmit} isSearching={busy} />
    </div>
  );
}
