import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { ToolsPage } from "@/pages/ToolsPage";
import { ToolDetailPage } from "@/pages/ToolDetailPage";
import { LibrariesPage } from "@/pages/LibrariesPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<ToolsPage />} />
          <Route path="tools/:id" element={<ToolDetailPage />} />
          <Route path="libraries" element={<LibrariesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
