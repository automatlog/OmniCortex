import { JetBrains_Mono, Space_Mono } from "next/font/google";

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const spaceMono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
});

type TagTone =
  | "ok"
  | "info"
  | "warn"
  | "err"
  | "check"
  | "http"
  | "vec";

function LogLine({
  ts,
  tag,
  tone,
  children,
}: {
  ts?: string;
  tag: string;
  tone: TagTone;
  children: React.ReactNode;
}) {
  return (
    <div className="line">
      <span className="ts">{ts || ""}</span>
      <span className={`tag tag-${tone}`}>{tag}</span>
      <span className="msg">{children}</span>
    </div>
  );
}

function SectionBanner({ title }: { title: string }) {
  return <div className="sectionBanner">{title}</div>;
}

export default function LogsPage() {
  return (
    <div className={`logsPage ${jetbrainsMono.className}`}>
      <header className="header">
        <div className={`logo ${spaceMono.className}`}>
          Omni<span>Cortex</span> / backend
        </div>
        <div className="badgeReady">RUNNING</div>
      </header>

      <div className="window">
        <div className="titlebar">
          <div className="dots">
            <div className="dot red" />
            <div className="dot yellow" />
            <div className="dot green" />
          </div>
          <div className="tabTitle">omnicortex-backend - uvicorn - localhost:8000</div>
        </div>

        <div className="logBody">
          <SectionBanner title="initialization" />

          <LogLine tag="OK" tone="ok">
            OmniCortex database tables created
          </LogLine>
          <LogLine tag="OK" tone="ok">
            Performance indexes created <span className="hiMuted">(HNSW + GIN)</span>
          </LogLine>
          <LogLine tag="INFO" tone="info">
            Started server process <span className="hiCyan">[37540]</span>
          </LogLine>
          <LogLine tag="INFO" tone="info">
            Waiting for application startup...
          </LogLine>

          <div className="valBox">
            <div className="valHeader">OmniCortex Backend - Startup Validation</div>
            <div className="valLine">
              <div className="dotG" />
              <b>[1/2]</b> PostgreSQL connected
            </div>
            <div className="valLine">
              <div className="dotG" />
              <b>[2/2]</b> vLLM at{" "}
              <span className="hiCyan">http://localhost:11434/v1</span> reachable, model{" "}
              <span className="hiPurple">llama3.1:8b</span>
            </div>
            <div className="valLine strong">All dependencies validated. Backend ready on http://localhost:8000</div>
            <div className="valLine">API docs: http://localhost:8000/docs</div>
          </div>

          <SectionBanner title="agent cleanup - 16:20" />

          <LogLine ts="2026-03-03 16:20:01" tag="HTTP" tone="http">
            <span className="methodGet">GET</span> /health <span className="status200">200 OK</span> x 2
          </LogLine>
          <LogLine ts="2026-03-03 16:20:01" tag="CORS" tone="info">
            Preflight localhost:3000 -&gt; <span className="hiCyan">/agents/o010m517...</span>
          </LogLine>
          <LogLine tag="VEC" tone="vec">
            Deleted vector store <span className="hiMuted">omni_agent_o010m517...</span>
          </LogLine>
          <LogLine tag="OK" tone="ok">
            Deleted agent <span className="hiYellow">Personal_15</span>
          </LogLine>
          <LogLine tag="VEC" tone="vec">
            Deleted vector store <span className="hiMuted">omni_agent_k010m517...</span>
          </LogLine>
          <LogLine tag="OK" tone="ok">
            Deleted agent <span className="hiYellow">Personal_16</span>
          </LogLine>
          <LogLine ts="2026-03-03 16:20:57" tag="HTTP" tone="http">
            <span className="methodDelete">DELETE</span> /agents/a010m517...{" "}
            <span className="status200">200 OK</span>
          </LogLine>

          <SectionBanner title="agent creation - 16:29" />

          <LogLine ts="2026-03-03 16:29:00" tag="OK" tone="ok">
            Created agent <span className="hiGreen">Personal_20</span>, role{" "}
            <span className="hiPurple">HealthWellness</span>
          </LogLine>
          <LogLine tag="HTTP" tone="http">
            <span className="methodPost">POST</span> /agents <span className="status200">200 OK</span>
          </LogLine>

          <SectionBanner title="url ingestion - agent h010w010" />

          <LogLine ts="2026-03-03 16:29:13" tag="SCRAPE" tone="info">
            Processing <span className="hiCyan">5 URLs</span> for agent{" "}
            <span className="hiMuted">h010w010-l4b3-0j2d-esa9...</span>
          </LogLine>
          <LogLine tag="OK" tone="ok">
            https://www.w3schools.com/sql/
          </LogLine>
          <LogLine tag="OK" tone="ok">
            https://www.w3schools.com/python/
          </LogLine>
          <LogLine tag="FAIL" tone="err">
            ncert.nic.in/.../keip103.pdf - ConnectionResetError(10054)
          </LogLine>
          <LogLine tag="FAIL" tone="err">
            github.com/.../github.txt - 404 Not Found
          </LogLine>
          <LogLine tag="CHUNK" tone="info">
            Ingesting 3 scraped pages, split: 109 parents -&gt; 690 children
          </LogLine>
          <LogLine tag="OK" tone="ok">
            Batch saved 109 parent chunks
          </LogLine>
          <LogLine tag="VEC" tone="vec">
            Vector store created <span className="hiCyan">omni_agent_h010w010-l4b3-0j2d...</span>
          </LogLine>

          <div className="statRow">
            <div className="statChip">
              <span>chunks </span>690
            </div>
            <div className="statChip">
              <span>parents </span>109
            </div>
            <div className="statChip">
              <span>urls ok </span>3 / 5
            </div>
            <div className="statChip">
              <span>model </span>BAAI/bge-large-en-v1.5
            </div>
          </div>
        </div>
      </div>

      <footer className="footer">
        <span>OmniCortex - 2026-03-03</span>
        <span>pid 37540 - uvicorn - localhost:8000</span>
      </footer>

      <style jsx>{`
        .logsPage {
          --bg: #0d0f11;
          --surface: #131619;
          --border: #1e2329;
          --green: #39d353;
          --green-dim: #1a6b2a;
          --cyan: #58d6e8;
          --yellow: #f0c060;
          --red: #f0614e;
          --blue: #6eb6ff;
          --purple: #b58dff;
          --muted: #4a5568;
          --text: #c9d1d9;
          --text-dim: #8b949e;
          --glow-g: rgba(57, 211, 83, 0.12);

          min-height: 100vh;
          background: var(--bg);
          color: var(--text);
          padding: 24px 20px 60px;
        }

        .header {
          max-width: 920px;
          margin: 0 auto 24px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding-bottom: 16px;
          border-bottom: 1px solid var(--border);
        }

        .logo {
          font-size: 15px;
          font-weight: 700;
          color: var(--cyan);
          letter-spacing: 0.06em;
          text-transform: uppercase;
        }

        .logo span {
          color: var(--muted);
        }

        .badgeReady {
          font-size: 11px;
          background: var(--green-dim);
          color: var(--green);
          border: 1px solid var(--green);
          border-radius: 4px;
          padding: 3px 10px;
          letter-spacing: 0.08em;
          animation: pulse 2.5s ease-in-out infinite;
        }

        .window {
          max-width: 920px;
          margin: 0 auto;
          border: 1px solid var(--border);
          border-radius: 10px;
          overflow: hidden;
          box-shadow: 0 0 60px rgba(0, 0, 0, 0.6), 0 0 0 1px #000;
        }

        .titlebar {
          background: #1a1d22;
          padding: 10px 16px;
          display: flex;
          align-items: center;
          gap: 12px;
          border-bottom: 1px solid var(--border);
        }

        .dots {
          display: flex;
          gap: 6px;
        }

        .dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
        }

        .dot.red {
          background: #ff5f57;
        }
        .dot.yellow {
          background: #ffbd2e;
        }
        .dot.green {
          background: #28c940;
        }

        .tabTitle {
          font-size: 12px;
          color: var(--text-dim);
          letter-spacing: 0.04em;
        }

        .logBody {
          background: var(--surface);
          padding: 20px 24px 28px;
          overflow-x: auto;
          line-height: 1.7;
          font-size: 13px;
        }

        .sectionBanner {
          display: flex;
          align-items: center;
          gap: 10px;
          margin: 22px 0 12px;
          color: var(--cyan);
          font-weight: 600;
          font-size: 12px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }

        .sectionBanner::before,
        .sectionBanner::after {
          content: "";
          flex: 1;
          height: 1px;
          background: linear-gradient(90deg, var(--border), transparent);
        }

        .sectionBanner::before {
          background: linear-gradient(90deg, transparent, var(--border));
        }

        .line {
          display: flex;
          align-items: flex-start;
          gap: 10px;
          padding: 1px 0;
          animation: fadeIn 0.25s ease both;
        }

        .ts {
          color: var(--muted);
          font-size: 11px;
          white-space: nowrap;
          padding-top: 2px;
          min-width: 172px;
          flex-shrink: 0;
        }

        .tag {
          font-size: 11px;
          font-weight: 700;
          border-radius: 3px;
          padding: 1px 7px;
          white-space: nowrap;
          flex-shrink: 0;
          letter-spacing: 0.04em;
        }

        .tag-ok {
          background: #0f2a16;
          color: var(--green);
          border: 1px solid var(--green-dim);
        }
        .tag-info {
          background: #0d1f2d;
          color: var(--blue);
          border: 1px solid #1d3a55;
        }
        .tag-warn {
          background: #2a1e08;
          color: var(--yellow);
          border: 1px solid #5a3f0a;
        }
        .tag-err {
          background: #2a0e0e;
          color: var(--red);
          border: 1px solid #5a1a1a;
        }
        .tag-check {
          background: #1a1030;
          color: var(--purple);
          border: 1px solid #3a2060;
        }
        .tag-http {
          background: #111418;
          color: var(--muted);
          border: 1px solid var(--border);
        }
        .tag-vec {
          background: #0d1f2d;
          color: var(--cyan);
          border: 1px solid #1d3a55;
        }

        .msg {
          color: var(--text);
          flex: 1;
          word-break: break-word;
        }

        .hiGreen {
          color: var(--green);
        }
        .hiCyan {
          color: var(--cyan);
        }
        .hiYellow {
          color: var(--yellow);
        }
        .hiRed {
          color: var(--red);
        }
        .hiPurple {
          color: var(--purple);
        }
        .hiMuted {
          color: var(--text-dim);
        }
        .hiBlue {
          color: var(--blue);
        }

        .valBox {
          border: 1px solid var(--green-dim);
          border-radius: 6px;
          background: #0a1a0f;
          padding: 12px 18px;
          margin: 14px 0;
          box-shadow: inset 0 0 30px var(--glow-g);
        }

        .valHeader {
          color: var(--green);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.1em;
          margin-bottom: 8px;
          text-align: center;
          text-transform: uppercase;
        }

        .valLine {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 12.5px;
          color: var(--text-dim);
          padding: 2px 0;
        }

        .valLine.strong {
          color: var(--green);
          font-weight: 600;
        }

        .dotG {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: var(--green);
          flex-shrink: 0;
        }

        .statRow {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
          margin: 8px 0;
        }

        .statChip {
          background: #0d1825;
          border: 1px solid #1d3a55;
          border-radius: 5px;
          padding: 5px 12px;
          font-size: 11.5px;
          color: var(--cyan);
        }

        .statChip span {
          color: var(--text-dim);
        }

        .methodGet {
          color: var(--green);
        }
        .methodPost {
          color: var(--blue);
        }
        .methodDelete {
          color: var(--red);
        }
        .status200 {
          color: var(--green);
        }

        .footer {
          max-width: 920px;
          margin: 20px auto 0;
          font-size: 11px;
          color: var(--muted);
          display: flex;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
        }

        @keyframes pulse {
          0%,
          100% {
            opacity: 1;
          }
          50% {
            opacity: 0.5;
          }
        }

        @keyframes fadeIn {
          from {
            opacity: 0;
            transform: translateX(-6px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        @media (max-width: 768px) {
          .logsPage {
            padding: 16px 12px 40px;
          }

          .header {
            margin-bottom: 16px;
            padding-bottom: 12px;
          }

          .logBody {
            padding: 14px 12px 20px;
            font-size: 12px;
          }

          .ts {
            min-width: 120px;
            font-size: 10px;
          }

          .footer {
            font-size: 10px;
          }
        }
      `}</style>
    </div>
  );
}
