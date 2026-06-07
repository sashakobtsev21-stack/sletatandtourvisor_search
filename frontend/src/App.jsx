import AppShell from "./components/AppShell.jsx";
import SearchPage from "./pages/SearchPage.jsx";
import HistoryPage from "./pages/HistoryPage.jsx";
import TestsPage from "./pages/TestsPage.jsx";
import ResultsPage from "./pages/ResultsPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import AdminUsersPage from "./pages/AdminUsersPage.jsx";
import BillingPage from "./pages/BillingPage.jsx";
import BatchPage from "./pages/BatchPage.jsx";
import JobsPage from "./pages/JobsPage.jsx";
import JobPage from "./pages/JobPage.jsx";
import LandingPage from "./pages/LandingPage.jsx";
import { useHashRoute, matchRun, matchJob } from "./lib/router.js";
import { useAuth } from "./lib/auth.jsx";

/**
 * App — корневой роутер дашборда. Все экраны (поиск, результаты, история,
 * автотесты) живут в одном SPA с общим стеклянным каркасом (AppShell) и
 * переключаются по hash-маршрутам.
 *
 * Гард авторизации: пока тянем /api/me — заставка; нет пользователя (мультиюзер без
 * сессии) — экран входа; иначе дашборд. В локальном режиме /api/me отдаёт полный доступ,
 * поэтому вход не показывается. Доступ к экранам дополнительно режется правами в AppShell
 * и на бэкенде (тут — только маршрутизация).
 */
function Splash() {
  return (
    <div className="grid min-h-screen place-items-center">
      <div className="size-8 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const { user, loading, can } = useAuth();

  if (loading) return <Splash />;
  if (!user) return <LoginPage />;
  // Гость (аноним с 2 поисками) может открыть форму входа/регистрации, не теряя доступ к поиску.
  if (user.mode === "guest" && (route.startsWith("/login") || route.startsWith("/register")))
    return <LoginPage />;
  // Гость на корне видит публичный лендинг (продающая стартовая); приложение — на #/search.
  if (user.mode === "guest" && route === "/") return <LandingPage />;

  const runId = matchRun(route);
  const jobId = matchJob(route);
  let page;
  if (route.startsWith("/admin/users")) {
    page = can("users.manage") ? <AdminUsersPage /> : <SearchPage />;
  } else if (route.startsWith("/billing")) page = <BillingPage />;
  else if (runId != null) page = <ResultsPage key={route} runId={runId} />;
  else if (jobId != null) page = <JobPage key={route} jobId={jobId} />;
  else if (route.startsWith("/batch")) page = <BatchPage />;
  else if (route.startsWith("/jobs")) page = <JobsPage />;
  else if (route.startsWith("/history")) page = <HistoryPage />;
  else if (route.startsWith("/tests")) page = <TestsPage />;
  else page = <SearchPage />;

  return <AppShell route={route}>{page}</AppShell>;
}
