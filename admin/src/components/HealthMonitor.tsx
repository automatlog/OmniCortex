"use client";

import { useEffect, useState } from "react";
import { checkHealth, HealthResponse } from "@/lib/api";

interface HealthMonitorProps {
  pollingInterval?: number; // milliseconds, default 30000 (30 seconds)
}

export function HealthMonitor({ pollingInterval = 30000 }: HealthMonitorProps) {
  const [isHealthy, setIsHealthy] = useState<boolean>(true);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showBanner, setShowBanner] = useState<boolean>(false);

  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;
    let isTabVisible = true;
    let previousHealthStatus = true; // Track previous health status

    // Check health function
    const checkBackendHealth = async () => {
      // Only poll when tab is visible
      if (!isTabVisible) return;

      try {
        const health: HealthResponse = await checkHealth();
        const healthy = health.status === "healthy";

        // Update state
        setIsHealthy(healthy);
        setLastCheck(new Date());
        setError(null);

        // Show banner if backend becomes unhealthy (transition from healthy to unhealthy)
        if (!healthy && previousHealthStatus) {
          setShowBanner(true);
        }

        // Auto-dismiss banner if backend recovers (transition from unhealthy to healthy)
        if (healthy && !previousHealthStatus) {
          setShowBanner(false);
        }

        // Update previous status for next check
        previousHealthStatus = healthy;
      } catch (err) {
        setIsHealthy(false);
        setLastCheck(new Date());
        setError(err instanceof Error ? err.message : "Health check failed");
        
        // Show banner if backend becomes unhealthy (transition from healthy to unhealthy)
        if (previousHealthStatus) {
          setShowBanner(true);
        }
        
        // Update previous status
        previousHealthStatus = false;
      }
    };

    // Handle tab visibility changes
    const handleVisibilityChange = () => {
      isTabVisible = !document.hidden;
      
      // Resume polling when tab becomes visible
      if (isTabVisible && !intervalId) {
        checkBackendHealth(); // Immediate check
        intervalId = setInterval(checkBackendHealth, pollingInterval);
      }
      
      // Pause polling when tab is hidden
      if (!isTabVisible && intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };

    // Initial health check
    checkBackendHealth();

    // Start polling
    intervalId = setInterval(checkBackendHealth, pollingInterval);

    // Listen for visibility changes
    document.addEventListener("visibilitychange", handleVisibilityChange);

    // Cleanup
    return () => {
      if (intervalId) clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [pollingInterval]); // Removed isHealthy from dependencies

  // Don't render anything if healthy
  if (!showBanner) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-red-600 text-white px-4 py-3 shadow-lg">
      <div className="container mx-auto flex items-center justify-between">
        <div className="flex items-center gap-3">
          <svg
            className="w-6 h-6"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
          <div>
            <p className="font-semibold">Backend Connection Lost</p>
            <p className="text-sm opacity-90">
              {error || "Cannot connect to the backend server. Please check if the backend is running."}
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowBanner(false)}
          className="text-white hover:text-gray-200 transition-colors"
          aria-label="Dismiss"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
      {lastCheck && (
        <p className="text-xs opacity-75 mt-1 text-center">
          Last checked: {lastCheck.toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
