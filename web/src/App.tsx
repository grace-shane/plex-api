import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ToolsPage } from "@/pages/ToolsPage";
import { ToolDetailPage } from "@/pages/ToolDetailPage";
import { LibrariesPage } from "@/pages/LibrariesPage";
import { RecentPage } from "@/pages/RecentPage";
import { ScriptsPage } from "@/pages/ScriptsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<ToolsPage />} />
          <Route path="tools/:id" element={<ToolDetailPage />} />
          <Route path="libraries" element={<LibrariesPage />} />
          <Route path="recent" element={<RecentPage />} />
          <Route path="scripts" element={<ScriptsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
