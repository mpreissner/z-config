import { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import Layout from "./components/Layout";
import { PrivateRoute } from "./components/PrivateRoute";
import TenantsPage from "./pages/TenantsPage";
import TenantWorkspacePage from "./pages/TenantWorkspacePage";
import AuditPage from "./pages/AuditPage";
import ScheduledTasksPage from "./pages/ScheduledTasksPage";
import TemplatesPage from "./pages/TemplatesPage";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import SsoCompletePage from "./pages/SsoCompletePage";
import MfaEnrollModal from "./components/MfaEnrollModal";
import AdminUsersPage from "./pages/AdminUsersPage";
import AdminGroupsPage from "./pages/AdminGroupsPage";
import AdminEntitlementsPage from "./pages/AdminEntitlementsPage";
import AdminSettingsPage from "./pages/AdminSettingsPage";
import ProfilePage from "./pages/ProfilePage";
import LoadingSpinner from "./components/LoadingSpinner";
import { useAuth } from "./context/AuthContext";
import { usePluginManagerProbe } from "./hooks/usePluginManager";
import { fetchTenants } from "./api/tenants";

// Split out so the manager's code lands in its own chunk instead of the bundle
// every deployment serves.
const AdminPluginsPage = lazy(() => import("./pages/AdminPluginsPage"));

// Likewise for the page entitled users see. A deployment with no plugins never
// fetches either chunk.
const PluginPage = lazy(() => import("./pages/PluginPage"));

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

/** Admin, and only on a deployment that registered the plugin API. */
function PluginRoute({ children }: { children: React.ReactNode }) {
  const { available, resolved } = usePluginManagerProbe();
  if (!resolved) return <LoadingSpinner />;
  if (!available) return <Navigate to="/tenants" replace />;
  return <>{children}</>;
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
        <Route path="/sso/complete" element={<SsoCompletePage />} />
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
                  <Route path="/scheduled-tasks" element={<ScheduledTasksPage />} />
                  <Route path="/templates" element={<TemplatesPage />} />
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
                    path="/admin/groups"
                    element={<AdminRoute><AdminGroupsPage /></AdminRoute>}
                  />
                  <Route
                    path="/admin/entitlements"
                    element={<AdminRoute><AdminEntitlementsPage /></AdminRoute>}
                  />
                  <Route
                    path="/admin/settings"
                    element={<AdminRoute><AdminSettingsPage /></AdminRoute>}
                  />
                  {/* One route for every plugin. Entitlement is enforced by
                      the API — a package the account was not granted answers
                      404 exactly as an uninstalled one does. */}
                  <Route
                    path="/plugins/:pkg"
                    element={
                      <Suspense fallback={<LoadingSpinner />}>
                        <PluginPage />
                      </Suspense>
                    }
                  />
                  <Route
                    path="/admin/plugins"
                    element={
                      <PluginRoute>
                        <Suspense fallback={<LoadingSpinner />}>
                          <AdminPluginsPage />
                        </Suspense>
                      </PluginRoute>
                    }
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
