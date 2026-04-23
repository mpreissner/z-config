import { Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import Layout from "./components/Layout";
import { PrivateRoute } from "./components/PrivateRoute";
import TenantsPage from "./pages/TenantsPage";
import TenantWorkspacePage from "./pages/TenantWorkspacePage";
import AuditPage from "./pages/AuditPage";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import MfaEnrollModal from "./components/MfaEnrollModal";
import AdminUsersPage from "./pages/AdminUsersPage";
import AdminEntitlementsPage from "./pages/AdminEntitlementsPage";
import AdminSettingsPage from "./pages/AdminSettingsPage";
import ProfilePage from "./pages/ProfilePage";
import { useAuth } from "./context/AuthContext";
import { fetchTenants } from "./api/tenants";

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { isAdmin } = useAuth();
  const { data: tenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
    enabled: !isAdmin,
  });
  if (isAdmin) return <>{children}</>;
  // Non-admin: redirect to first tenant
  if (tenants && tenants.length > 0) {
    return <Navigate to={`/tenant/${tenants[0].id}/zia`} replace />;
  }
  return <Navigate to="/tenants" replace />;
}

function RootRedirect() {
  return <Navigate to="/tenants" replace />;
}

export default function App() {
  const { mfaEnrollRequired } = useAuth();

  return (
    <>
      {mfaEnrollRequired && <MfaEnrollModal />}
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route
          path="/*"
          element={
            <PrivateRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<RootRedirect />} />
                  <Route path="/tenants" element={<TenantsPage />} />
                  <Route path="/tenants/:id" element={<Navigate to="/tenants" replace />} />
                  <Route path="/profile" element={<ProfilePage />} />
                  <Route path="/audit" element={<AuditPage />} />
                  {/* Tenant workspace routes */}
                  <Route path="/tenant/:id" element={<Navigate to="zia" replace />} />
                  <Route path="/tenant/:id/zia" element={<TenantWorkspacePage />} />
                  <Route path="/tenant/:id/zpa" element={<TenantWorkspacePage />} />
                  <Route path="/tenant/:id/zdx" element={<TenantWorkspacePage />} />
                  <Route path="/tenant/:id/zcc" element={<TenantWorkspacePage />} />
                  <Route path="/tenant/:id/zid" element={<TenantWorkspacePage />} />
                  {/* Legacy redirects */}
                  <Route path="/zia/:tenant" element={<Navigate to="/tenants" replace />} />
                  <Route path="/zpa/:tenant" element={<Navigate to="/tenants" replace />} />
                  {/* Admin routes */}
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
    </>
  );
}
