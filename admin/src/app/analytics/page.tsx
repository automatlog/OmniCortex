"use client";

import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, Users, MessageSquare, Clock, Zap, Database } from "lucide-react";

export default function AnalyticsPage() {
  const metrics = [
    {
      title: "Total Queries",
      value: "12,847",
      change: "+12.5%",
      icon: MessageSquare,
      color: "from-blue-500 to-cyan-500",
    },
    {
      title: "Active Users",
      value: "342",
      change: "+8.2%",
      icon: Users,
      color: "from-purple-500 to-pink-500",
    },
    {
      title: "Avg Response Time",
      value: "1.2s",
      change: "-15.3%",
      icon: Clock,
      color: "from-green-500 to-emerald-500",
    },
    {
      title: "Cache Hit Rate",
      value: "78.4%",
      change: "+5.1%",
      icon: Zap,
      color: "from-orange-500 to-yellow-500",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Analytics</h1>
        <p className="text-neutral-400">
          Monitor your AI agents&apos; performance and usage metrics
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((metric, index) => (
          <motion.div
            key={metric.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
          >
            <Card className="bg-neutral-900 border-neutral-800">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-neutral-400">
                  {metric.title}
                </CardTitle>
                <div
                  className={`p-2 rounded-lg bg-gradient-to-br ${metric.color}`}
                >
                  <metric.icon className="w-4 h-4 text-white" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-white">
                  {metric.value}
                </div>
                <p
                  className={`text-xs mt-1 ${
                    metric.change.startsWith("+")
                      ? "text-green-400"
                      : "text-red-400"
                  }`}
                >
                  {metric.change} from last week
                </p>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Charts Placeholder */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader>
            <CardTitle className="text-lg text-white flex items-center gap-2">
              <TrendingUp className="w-5 h-5" />
              Query Volume
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64 flex items-center justify-center text-neutral-500 border border-dashed border-neutral-700 rounded-lg">
              <div className="text-center">
                <TrendingUp className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>Connect to ClickHouse for live metrics</p>
                <p className="text-sm text-neutral-600">
                  See docs/TESTING.md for setup
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-neutral-900 border-neutral-800">
          <CardHeader>
            <CardTitle className="text-lg text-white flex items-center gap-2">
              <Database className="w-5 h-5" />
              Database Stats
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-neutral-400">Total Chunks</span>
                <span className="text-white font-medium">24,891</span>
              </div>
              <div className="w-full h-2 bg-neutral-800 rounded-full overflow-hidden">
                <div className="w-3/4 h-full bg-gradient-to-r from-blue-500 to-purple-500" />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-400">Cache Entries</span>
                <span className="text-white font-medium">1,247</span>
              </div>
              <div className="w-full h-2 bg-neutral-800 rounded-full overflow-hidden">
                <div className="w-1/2 h-full bg-gradient-to-r from-green-500 to-emerald-500" />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-400">Vector Dimensions</span>
                <span className="text-white font-medium">384</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
