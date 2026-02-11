"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Bot, MessageSquare, FileText, Activity, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getAgents, checkHealth, type Agent } from "@/lib/api";
import Link from "next/link";

export default function Dashboard() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isHealthy, setIsHealthy] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [agentList, health] = await Promise.all([
          getAgents().catch(() => []),
          checkHealth(),
        ]);
        setAgents(agentList);
        setIsHealthy(health.status === "healthy");
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const stats = [
    {
      title: "Total Agents",
      value: agents.length,
      icon: Bot,
      color: "from-blue-500 to-cyan-500",
    },
    {
      title: "Total Documents",
      value: agents.reduce((acc, a) => acc + (a.document_count || 0), 0),
      icon: FileText,
      color: "from-purple-500 to-pink-500",
    },
    {
      title: "API Status",
      value: isHealthy ? "Online" : "Offline",
      icon: Activity,
      color: isHealthy ? "from-green-500 to-emerald-500" : "from-red-500 to-orange-500",
    },
    {
      title: "Active Webhooks",
      value: agents.filter((a) => a.webhook_url).length,
      icon: TrendingUp,
      color: "from-orange-500 to-yellow-500",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Dashboard</h1>
        <p className="text-neutral-400">
          Welcome to OmniCortex Admin. Manage your AI agents and monitor performance.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, index) => (
          <motion.div
            key={stat.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
          >
            <Card className="bg-neutral-900 border-neutral-800 hover:border-neutral-700 transition-colors">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-neutral-400">
                  {stat.title}
                </CardTitle>
                <div
                  className={`p-2 rounded-lg bg-gradient-to-br ${stat.color}`}
                >
                  <stat.icon className="w-4 h-4 text-white" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-white">
                  {loading ? "..." : stat.value}
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Agents */}
        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader>
            <CardTitle className="text-lg text-white flex items-center gap-2">
              <Bot className="w-5 h-5" />
              Recent Agents
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="text-neutral-500">Loading...</div>
            ) : agents.length === 0 ? (
              <div className="text-center py-8 text-neutral-500">
                <p>No agents yet</p>
                <Link
                  href="/agents"
                  className="text-blue-400 hover:underline text-sm"
                >
                  Create your first agent →
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {agents.slice(0, 5).map((agent) => (
                  <Link
                    key={agent.id}
                    href={`/agents/${agent.id}/chat`}
                    className="flex items-center justify-between p-3 rounded-lg bg-neutral-800/50 hover:bg-neutral-800 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
                        <span className="text-sm">🤖</span>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-white">
                          {agent.name}
                        </p>
                        <p className="text-xs text-neutral-500">
                          {agent.document_count || 0} documents
                        </p>
                      </div>
                    </div>
                    <MessageSquare className="w-4 h-4 text-neutral-500" />
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quick Start */}
        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader>
            <CardTitle className="text-lg text-white">Quick Start</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Link
              href="/agents"
              className="flex items-center gap-4 p-4 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 transition-colors border border-blue-500/30"
            >
              <div className="p-3 rounded-lg bg-blue-600">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="font-medium text-white">Create Agent</p>
                <p className="text-sm text-neutral-400">
                  Build a new AI agent with custom knowledge
                </p>
              </div>
            </Link>

            <div className="flex items-center gap-4 p-4 rounded-lg bg-neutral-800/50 border border-neutral-700">
              <div className="p-3 rounded-lg bg-neutral-700">
                <FileText className="w-5 h-5 text-neutral-300" />
              </div>
              <div>
                <p className="font-medium text-white">API Documentation</p>
                <p className="text-sm text-neutral-400">
                  Integrate OmniCortex with your apps
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
