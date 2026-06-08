import { useEffect, useRef, useState } from "react";
import { Bell, CheckCheck, Layers } from "lucide-react";
import { apiFetch } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { formatShortDateTime } from "../lib/format.js";

/**
 * NotificationsBell — значок уведомлений в шапке (Ф2 батча). Поллит непрочитанные
 * (~30с), показывает бейдж; в панели — список «анализ готов/ошибка». Клик по уведомлению
 * помечает прочитанным и ведёт на связанный батч (#/jobs/{id}). Рендерится только в
 * мультиюзере (см. AppShell) — у гостя/локального режима уведомлений нет.
 */
export default function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef(null);

  const load = async () => {
    try {
      // P2-y: retry:false на polling — иначе apiFetch ретраит 503 до 3 раз
      // (~3.5с с backoff), а наш setInterval=30с может зацепить второй вызов.
      const r = await apiFetch("/api/notifications", { retry: false });
      if (!r.ok) return;
      const j = await r.json();
      setItems(j.items || []);
      setUnread(j.unread || 0);
    } catch {
      /* тихо — значок не критичен */
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000); // фоновый поллинг непрочитанных
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };  // a11y: Esc закрывает
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = () => {
    setOpen((o) => !o);
    if (!open) load(); // при открытии — свежий список
  };

  const onClickItem = async (n) => {
    if (!n.is_read) {
      await apiFetch(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(() => {});
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: 1 } : x)));
      setUnread((u) => Math.max(0, u - 1));
    }
    setOpen(false);
    if (n.job_id) navigate(`/jobs/${n.job_id}`);
  };

  const markAll = async () => {
    await apiFetch("/api/notifications/read-all", { method: "POST" }).catch(() => {});
    setItems((prev) => prev.map((x) => ({ ...x, is_read: 1 })));
    setUnread(0);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={toggle}
        aria-label={`Уведомления${unread > 0 ? ` (непрочитанных: ${unread})` : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Уведомления"
        className="relative flex items-center rounded-lg px-2.5 py-2 text-muted transition-colors hover:bg-white/5 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
      >
        <Bell aria-hidden="true" className="size-5" />
        {unread > 0 && (
          <span aria-hidden="true" className="absolute -right-0.5 -top-0.5 grid min-w-[1.1rem] place-items-center rounded-full bg-brand px-1 text-[10px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="false"
          aria-labelledby="notif-dialog-title"
          className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-xl border border-white/10 bg-[#0b1026] shadow-2xl ring-1 ring-black/40"
        >
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
            <span id="notif-dialog-title" className="text-sm font-semibold text-ink">Уведомления</span>
            {items.some((n) => !n.is_read) && (
              <button onClick={markAll} className="flex items-center gap-1 text-xs text-muted transition-colors hover:text-ink">
                <CheckCheck aria-hidden="true" className="size-3.5" /> прочитать все
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted">Пока нет уведомлений</div>
            ) : (
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => onClickItem(n)}
                  className={[
                    "flex w-full items-start gap-2.5 border-b border-white/5 px-4 py-3 text-left transition-colors hover:bg-white/[0.04]",
                    n.is_read ? "opacity-60" : "",
                  ].join(" ")}
                >
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg ${
                      n.kind === "batch_failed" ? "bg-rose-500/15 text-rose-300"
                      : n.kind === "batch_partial" ? "bg-amber-500/15 text-amber-300"
                      : "bg-emerald-500/15 text-emerald-300"
                    }`}
                  >
                    <Layers className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm text-ink">{n.text}</span>
                    <span className="block text-[11px] text-muted">{formatShortDateTime(n.created_at)}</span>
                  </span>
                  {!n.is_read && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-brand" />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
