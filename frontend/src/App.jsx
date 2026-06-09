import { lazy, Suspense } from "react";
import { LazyMotion, domAnimation } from "framer-motion";
import AppShell from "./components/AppShell.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import SearchPage from "./pages/SearchPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import LandingPage from "./pages/LandingPage.jsx";
import { useHashRoute, matchRun, matchJob } from "./lib/router.js";
import { useAuth } from "./lib/auth.jsx";

// Не-входные страницы — лениво (отдельные чанки): админка/тесты/биллинг/батч/история/результаты
// не нужны в стартовом бандле (гость на лендинге и обычный поиск их не открывают первыми).
const HistoryPage = lazy(() => import("./pages/HistoryPage.jsx"));
const TestsPage = lazy(() => import("./pages/TestsPage.jsx"));
const ResultsPage = lazy(() => import("./pages/ResultsPage.jsx"));
const AdminUsersPage = lazy(() => import("./pages/AdminUsersPage.jsx"));
const BillingPage = lazy(() => import("./pages/BillingPage.jsx"));
const BatchPage = lazy(() => import("./pages/BatchPage.jsx"));
const JobsPage = lazy(() => import("./pages/JobsPage.jsx"));
const JobPage = lazy(() => import("./pages/JobPage.jsx"));

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

// Заглушка на время подгрузки лениво-чанка страницы (внутри каркаса, не на весь экран).
function PageFallback() {
  return (
    <div className="grid place-items-center py-24">
      <div className="size-7 animate-spin rounded-full border-2 border-white/20 border-t-brand" />
    </div>
  );
}

function AppInner() {
  const route = useHashRoute();
  const { user, loading, can } = useAuth();

  if (loading) return <Splash />;
  if (!user) return <LoginPage />;
  // Гость (аноним с 2 поисками) может открыть форму входа/регистрации, не теряя доступ к поиску.
  if (user.mode === "guest" && (route.startsWith("/login") || route.startsWith("/register")))
    return <LoginPage guest />;
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

  return (
    <AppShell route={route}>
      <ErrorBoundary resetKey={route}>
        <Suspense fallback={<PageFallback />}>{page}</Suspense>
      </ErrorBoundary>
    </AppShell>
  );
}

/** App — корень с LazyMotion. `features={domAnimation}` бандлит только нужное
 * подмножество framer-motion (~ -45 KB gzip vs полный motion). strict=true бросает
 * warning если где-то осталось `motion.X` вместо `m.X` (P3 audit-final). */
export default function App() {
  return (
    <LazyMotion features={domAnimation} strict>
      <AppInner />
    </LazyMotion>
  );
}
