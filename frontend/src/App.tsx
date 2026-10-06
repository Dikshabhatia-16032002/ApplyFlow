import { Navigate, Route, Routes } from "react-router-dom"
import { Layout } from "./components/Layout"
import { ProfilesPage } from "./pages/ProfilesPage"
import { ResumesPage } from "./pages/ResumesPage"
import { SheetPage } from "./pages/SheetPage"
import { TemplatesPage } from "./pages/TemplatesPage"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/sheet" replace />} />
        <Route path="/sheet" element={<SheetPage />} />
        <Route path="/profiles" element={<ProfilesPage />} />
        <Route path="/resumes" element={<ResumesPage />} />
        <Route path="/templates" element={<TemplatesPage />} />
      </Route>
    </Routes>
  )
}
