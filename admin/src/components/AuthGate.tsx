"use client";

import { FormEvent, useEffect, useState } from "react";
import { KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  clearRuntimeApiKey,
  getRuntimeApiKey,
  setRuntimeApiKey,
  validateApiKey,
} from "@/lib/api";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  useEffect(() => {
    const bootstrap = async () => {
      const saved = getRuntimeApiKey();
      if (!saved) {
        setChecking(false);
        return;
      }

      const result = await validateApiKey(saved);
      if (result.valid) {
        setAuthenticated(true);
      } else {
        clearRuntimeApiKey();
      }
      setChecking(false);
    };

    void bootstrap();
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setValidating(true);
    setError(null);

    const result = await validateApiKey(apiKey);
    if (!result.valid) {
      setError(result.message || "Invalid API key");
      setValidating(false);
      return;
    }

    setRuntimeApiKey(apiKey);
    setAuthenticated(true);
    setValidating(false);
  }

  if (checking) {
    return (
      <div className="min-h-screen grid place-items-center">
        <div className="text-neutral-400 text-sm">Checking authentication...</div>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="min-h-screen grid place-items-center p-6">
        <form
          onSubmit={onSubmit}
          className="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-900 p-6 space-y-4"
        >
          <div className="flex items-center gap-2 text-white">
            <KeyRound className="w-5 h-5" />
            <h1 className="text-lg font-semibold">Admin Login</h1>
          </div>
          <p className="text-sm text-neutral-400">
            Enter your API key (Bearer token) to access agents and queries.
          </p>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste API key"
            className="bg-neutral-950 border-neutral-700 text-white"
            autoFocus
          />
          {error ? <p className="text-sm text-red-400">{error}</p> : null}
          <Button type="submit" disabled={validating} className="w-full">
            {validating ? "Validating..." : "Login"}
          </Button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}

