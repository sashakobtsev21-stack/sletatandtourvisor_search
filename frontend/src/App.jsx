import AppShell from "./components/AppShell.jsx";
import SearchPage from "./pages/SearchPage.jsx";
import HistoryPage from "./pages/HistoryPage.jsx";
import TestsPage from "./pages/TestsPage.jsx";
import ResultsPage from "./pages/ResultsPage.jsx";
import { useHashRoute, matchRun } from "./lib/router.js";

/**
 * App — корневой роутер дашборда. Все экраны (поиск, результаты, история,
 * автотесты) живут в одном SPA с общим стеклянным каркасом (AppShell) и
 * переключаются по hash-маршрутам — старые серверные страницы больше не нужны.
 */
export default function App() {
  const route = useHashRoute();
  const runId = matchRun(route);

  let page;
  if (runId != null) page = <ResultsPage key={route} runId={runId} />;
  else if (route.startsWith("/history")) page = <HistoryPage />;
  else if (route.startsWith("/tests")) page = <TestsPage />;
  else page = <SearchPage />;

  return <AppShell route={route}>{page}</AppShell>;
}
