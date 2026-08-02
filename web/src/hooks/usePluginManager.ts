import { useQuery } from "@tanstack/react-query";
import { probePluginManager, fetchEntitledPlugins, EntitledPlugin } from "../api/plugins";
import { useAuth } from "../context/AuthContext";

/**
 * Whether to show the plugin manager to the current user.
 *
 * Answered by probing the API rather than by a field on /system/info, which
 * every account can read — a flag there would tell all of them the feature
 * exists. The probe itself only runs for admins, so an ordinary session never
 * touches a /plugins path.
 *
 * Cached for the session: the switch behind it is an environment variable read
 * at process start, so it cannot change while the tab is open.
 */
export function usePluginManagerAvailable(): boolean {
  return usePluginManagerProbe().available;
}

/**
 * The same answer plus whether it has arrived yet.
 *
 * The nav can simply omit an item it is not yet sure about, but a route has to
 * wait: redirecting on the pending `false` would bounce an admin straight back
 * out of a page they are entitled to.
 */
export function usePluginManagerProbe(): { available: boolean; resolved: boolean } {
  const { isAdmin } = useAuth();
  const { data, isFetched } = useQuery({
    queryKey: ["plugin-manager-available"],
    queryFn: probePluginManager,
    enabled: isAdmin,
    staleTime: Infinity,
    retry: false,
  });
  return { available: isAdmin && data === true, resolved: !isAdmin || isFetched };
}

/**
 * The plugins this account may open — the source of the per-plugin nav items.
 *
 * Separate from the probe above, which asks an admin-only question and so
 * answers false for the ordinary users this is for. /plugins/entitled is
 * readable by any session, tells the caller only about itself, and comes back
 * empty on a deployment that never switched the manager on, so the nav needs no
 * feature flag of its own.
 *
 * Not cached for the session like the probe: an admin can grant or revoke while
 * the tab is open, and the nav should catch up on the next window focus.
 */
export function useEntitledPlugins(): { plugins: EntitledPlugin[]; resolved: boolean } {
  const { isAuthenticated } = useAuth();
  const { data, isFetched } = useQuery({
    queryKey: ["entitled-plugins"],
    queryFn: fetchEntitledPlugins,
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
    retry: false,
  });
  return { plugins: data ?? [], resolved: isFetched };
}
