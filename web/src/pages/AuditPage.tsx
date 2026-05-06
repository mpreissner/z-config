import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAuditLog } from "../api/audit";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorMessage from "../components/ErrorMessage";
import { formatDateTime } from "../utils/time";

const PAGE_SIZE = 25;

export default function AuditPage() {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");

  const { data: entries, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["audit", { limit: 500 }],
    queryFn: () => fetchAuditLog({ limit: 500 }),
  });

  const filtered = entries
    ? (() => {
        const q = search.trim().toLowerCase();
        if (!q) return entries;
        return entries.filter((e) => {
          const details =
            e.details != null
              ? typeof e.details === "object"
                ? JSON.stringify(e.details)
                : String(e.details)
              : "";
          return [
            e.product,
            e.operation,
            e.action,
            e.status,
            e.resource_name,
            e.resource_type,
            e.error_message,
            details,
          ]
            .filter(Boolean)
            .some((f) => f!.toLowerCase().includes(q));
        });
      })()
    : [];

  const totalPages = filtered ? Math.ceil(filtered.length / PAGE_SIZE) : 0;
  const pageEntries = filtered
    ? filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
    : [];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold text-gray-900">Audit Log</h1>
        <button
          onClick={() => { setPage(0); refetch(); }}
          disabled={isFetching}
          title="Refresh"
          className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-40 transition-colors"
        >
          <svg
            className={`h-5 w-5 ${isFetching ? "animate-spin" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      <div className="mb-4">
        <input
          type="text"
          placeholder="Search audit log..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
          className="w-full max-w-sm rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      {isLoading && <LoadingSpinner />}
      {error && (
        <ErrorMessage
          message={error instanceof Error ? error.message : "Failed to load audit log"}
        />
      )}
      {entries && (
        <>
          <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 rounded-lg">
            <table className="min-w-full divide-y divide-gray-300 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {["Timestamp", "Product", "Operation", "Action", "Status", "Resource", "Details"].map(
                    (h) => (
                      <th
                        key={h}
                        className="py-3 px-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide"
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {pageEntries.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="py-8 text-center text-gray-500"
                    >
                      {search.trim() ? "No matching entries." : "No audit entries."}
                    </td>
                  </tr>
                )}
                {pageEntries.map((e) => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-3 py-2 text-gray-500">
                      {formatDateTime(e.timestamp)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                      {e.product}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                      {e.operation}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                      {e.action}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <span
                        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                          e.status === "success"
                            ? "bg-green-100 text-green-800"
                            : "bg-red-100 text-red-800"
                        }`}
                      >
                        {e.status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-gray-500">
                      {e.resource_name ?? e.resource_type ?? "-"}
                    </td>
                    <td className="max-w-xs truncate px-3 py-2 text-gray-500 font-mono text-xs">
                      {e.details != null
                        ? typeof e.details === "object"
                          ? JSON.stringify(e.details)
                          : e.details
                        : (e.error_message ?? "-")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
              <span>
                Page {page + 1} of {totalPages}
                {search.trim() && ` (${filtered.length} matching)`}
              </span>
              <div className="flex gap-2">
                <button
                  className="px-3 py-1 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-100"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <button
                  className="px-3 py-1 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-100"
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
