import { ReactNode, useState } from "react";
import { NavLink, Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api/system";
import { useSystemInfo } from "../hooks/useSystemInfo";
import { useAuth } from "../context/AuthContext";
import { useActiveTenant } from "../context/ActiveTenantContext";
import { fetchTenants, Tenant } from "../api/tenants";
import zLogo from "../assets/z-logo.jpg";

interface LayoutProps {
  children: ReactNode;
}

function StatusIndicator() {
  const { data: health, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });
  const { data: sysInfo } = useSystemInfo();
  const connected = health?.status === "ok" && !isError;

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-t border-zs-600 text-xs text-blue-100">
      <span className={`h-2 w-2 rounded-full flex-shrink-0 ${connected ? "bg-green-400" : "bg-red-400"}`} />
      <span>{connected ? "Connected" : "Disconnected"}</span>
      {sysInfo?.version && (
        <span className="ml-auto text-blue-200">v{sysInfo.version}</span>
      )}
    </div>
  );
}

function TenantNavItem({ tenant, isActive, onClick }: {
  tenant: Tenant;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <Link
      to={`/tenant/${tenant.id}/zia`}
      onClick={onClick}
      className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors ${
        isActive
          ? "text-white font-medium"
          : "text-blue-200 hover:bg-zs-600 hover:text-white"
      }`}
    >
      <span
        className={`flex-shrink-0 h-2 w-2 rounded-full ${
          isActive ? "bg-white" : "bg-transparent border border-blue-400"
        }`}
      />
      <span className="truncate">{tenant.name}</span>
      {tenant.govcloud && (
        <span className="text-blue-400 text-xs flex-shrink-0">(GovCloud)</span>
      )}
      {tenant.last_validation_error && (
        <span className="text-red-400 text-xs flex-shrink-0 font-bold">(!)</span>
      )}
    </Link>
  );
}

const adminNavItems = [
  { to: "/admin/users", label: "Users" },
  { to: "/admin/entitlements", label: "Tenant Access" },
  { to: "/admin/settings", label: "Settings" },
];

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive
      ? "bg-white text-zs-500 font-semibold"
      : "text-blue-100 hover:bg-zs-600 hover:text-white"
  }`;

export default function Layout({ children }: LayoutProps) {
  const { logout, isAdmin, user } = useAuth();
  const { activeTenantId, setActiveTenantId } = useActiveTenant();
  const navigate = useNavigate();
  const [tenantsOpen, setTenantsOpen] = useState(true);
  const [adminOpen, setAdminOpen] = useState(true);

  const { data: tenants } = useQuery({
    queryKey: ["tenants"],
    queryFn: fetchTenants,
    staleTime: 60_000,
  });

  const sorted = tenants
    ? [...tenants].sort((a, b) => a.name.localeCompare(b.name))
    : [];

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  function handleTenantClick(tenant: Tenant) {
    setActiveTenantId(tenant.id);
    navigate(`/tenant/${tenant.id}/zia`);
  }

  const username = user?.username ?? "";
  const avatarLetter = username.charAt(0).toUpperCase() || "U";

  // Pick a deterministic color for the avatar based on username
  const avatarColors = [
    "bg-blue-500", "bg-purple-500", "bg-green-500", "bg-orange-500",
    "bg-pink-500", "bg-teal-500",
  ];
  const avatarColor = avatarColors[avatarLetter.charCodeAt(0) % avatarColors.length];

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-56 bg-zs-500 flex flex-col overflow-hidden">
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 flex-shrink-0">
          <img src={zLogo} alt="Z" className="h-8 w-8 rounded-md object-cover" />
          <span className="text-lg font-semibold text-white tracking-tight">zs-config</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 overflow-y-auto space-y-1">
          {/* Tenants section */}
          <div>
            {isAdmin ? (
              <NavLink
                to="/tenants"
                className={({ isActive }) =>
                  `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    isActive ? "bg-white text-zs-500 font-semibold" : "text-blue-100 hover:bg-zs-600 hover:text-white"
                  }`
                }
              >
                Tenants
              </NavLink>
            ) : (
              <>
                <div className="flex items-center rounded-md text-sm font-medium text-blue-100 hover:bg-zs-600 hover:text-white transition-colors">
                  <NavLink
                    to="/tenants"
                    className={({ isActive }) =>
                      `flex-1 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                        isActive ? "bg-white text-zs-500 font-semibold" : ""
                      }`
                    }
                  >
                    Tenants
                  </NavLink>
                  <button
                    onClick={() => setTenantsOpen((v) => !v)}
                    className="px-2 py-2 rounded-r-md hover:bg-zs-600 transition-colors"
                    title={tenantsOpen ? "Collapse" : "Expand"}
                  >
                    <svg
                      className={`h-3.5 w-3.5 transition-transform ${tenantsOpen ? "" : "-rotate-90"}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                </div>
                {tenantsOpen && (
                  <div className="mt-0.5 ml-2 space-y-0.5">
                    {sorted.map((tenant) => (
                      <TenantNavItem
                        key={tenant.id}
                        tenant={tenant}
                        isActive={activeTenantId === tenant.id}
                        onClick={() => handleTenantClick(tenant)}
                      />
                    ))}
                    {sorted.length === 0 && (
                      <p className="px-3 py-1 text-xs text-blue-300 italic">No tenants</p>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Divider */}
          <div className="border-t border-zs-600 my-1" />

          {/* Scheduled Tasks */}
          {!isAdmin && (
            <NavLink to="/scheduled-tasks" className={navLinkClass}>
              Scheduled Tasks
            </NavLink>
          )}

          {/* Templates */}
          {!isAdmin && (
            <NavLink to="/templates" className={navLinkClass}>
              Templates
            </NavLink>
          )}

          {/* Audit Log */}
          <NavLink to="/audit" className={navLinkClass}>
            Audit Log
          </NavLink>

          {/* Admin section */}
          {isAdmin && (
            <>
              <div className="border-t border-zs-600 my-1" />
              <button
                onClick={() => setAdminOpen((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2 rounded-md text-sm font-medium text-blue-100 hover:bg-zs-600 hover:text-white transition-colors"
              >
                <span>Admin</span>
                <svg
                  className={`h-3.5 w-3.5 transition-transform ${adminOpen ? "" : "-rotate-90"}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {adminOpen && (
                <div className="mt-0.5 ml-2 space-y-0.5">
                  {adminNavItems.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      className={({ isActive }) =>
                        `block px-3 py-1.5 rounded-md text-sm transition-colors ${
                          isActive
                            ? "bg-white text-zs-500 font-semibold"
                            : "text-blue-200 hover:bg-zs-600 hover:text-white"
                        }`
                      }
                    >
                      {item.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </>
          )}
        </nav>

        {/* User footer */}
        <div className="flex-shrink-0 border-t border-zs-600 px-2 py-3 space-y-1">
          <div className="flex items-center gap-2 px-3 py-1">
            <div
              className={`flex-shrink-0 h-7 w-7 rounded-full ${avatarColor} flex items-center justify-center text-white text-xs font-bold`}
            >
              {avatarLetter}
            </div>
            <div className="min-w-0">
              <p className="text-sm text-white font-medium truncate">{username}</p>
              {isAdmin && (
                <p className="text-xs text-blue-300 leading-none">Admin</p>
              )}
            </div>
          </div>
          <NavLink
            to="/profile"
            className={({ isActive }) =>
              `block px-3 py-1.5 rounded-md text-sm transition-colors ${
                isActive
                  ? "bg-white text-zs-500 font-semibold"
                  : "text-blue-200 hover:bg-zs-600 hover:text-white"
              }`
            }
          >
            Profile
          </NavLink>
          <button
            onClick={handleLogout}
            className="w-full text-left block px-3 py-1.5 rounded-md text-sm font-medium text-blue-100 hover:bg-zs-600 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>

        <StatusIndicator />
      </aside>
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
