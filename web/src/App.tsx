import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import { PrivateRoute } from "./components/PrivateRoute";
import TenantsPage from "./pages/TenantsPage";
import TenantPage from "./pages/TenantPage";
import AuditPage from "./pages/AuditPage";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import AdminUsersPage from "./pages/AdminUsersPage";
import AdminEntitlementsPage from "./pages/AdminEntitlementsPage";
import AdminSettingsPage from "./pages/AdminSettingsPage";
import { useAuth } from "./context/AuthContext";

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();
  return isAdmin ? <>{children}</> : <Navigate to="/tenants" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/change-password" element={<ChangePasswordPage />} />
      <Route
        path="/*"
        element={
          <PrivateRoute>
            <Layout>
              <Routes>
                <Route path="/" element={<Navigate to="/tenants" replace />} />
                <Route path="/tenants" element={<TenantsPage />} />
                <Route path="/tenants/:id" element={<TenantPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/zia/:tenant" element={<Navigate to="/tenants" replace />} />
                <Route path="/zpa/:tenant" element={<Navigate to="/tenants" replace />} />
                <Route
                  path="/admin/users"
                  element={<AdminRoute><AdminUsersPage /></AdminRoute>}
                />
                <Route
                  path="/admin/entitlements"
                  element={<AdminRoute><AdminEntitlementsPage /></AdminRoute>}
                />
                <Route
                  path="/admin/settings"
                  element={<AdminRoute><AdminSettingsPage /></AdminRoute>}
                />
              </Routes>
            </Layout>
          </PrivateRoute>
        }
      />
    </Routes>
  );
}
