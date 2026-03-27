import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";
import type {
  CardAdvisorSection,
  CombatSummary,
  DebugSection,
  EnemiesSection,
  MerchantRelicsSection,
  OverlayPayload,
  OverlaySettingsPayload,
  RelicsSection,
  StrategySection,
} from "./overlayTypes";

const TIER_CLASS: Record<string, string> = {
  S: "tier-s",
  A: "tier-a",
  B: "tier-b",
  C: "tier-c",
  D: "tier-d",
};

function netClass(kind: string): string {
  switch (kind) {
    case "lethal":
    case "danger":
      return "net-danger";
    case "safe":
      return "net-safe";
    case "warn":
      return "net-warn";
    default:
      return "net-muted";
  }
}

function safetyClass(kind: string): string {
  switch (kind) {
    case "safe":
      return "strat-safe";
    case "lethal":
      return "strat-lethal";
    case "danger":
      return "strat-danger";
    default:
      return "strat-warn";
  }
}

function suggestedClass(role: string): string {
  if (role === "block") return "sug-block";
  if (role === "add_attack") return "sug-lethal";
  return "sug-atk";
}

function sendSettings(ws: WebSocket | null, s: OverlaySettingsPayload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(
    JSON.stringify({
      type: "set_settings",
      show_combat_summary: s.show_combat_summary,
      show_enemies: s.show_enemies,
      show_strategy: s.show_strategy,
      show_relics: s.show_relics,
      show_merchant_relics: s.show_merchant_relics,
      show_card_reward: s.show_card_reward,
      alpha: s.alpha,
      click_through: s.click_through,
    }),
  );
}

function CombatBlock({ data }: { data: CombatSummary }) {
  return (
    <section className="panel combat-summary">
      <div className="stats-line">{data.stats_line}</div>
      {data.net && (
        <div className={`net-banner ${netClass(data.net.kind)}`}>{data.net.text}</div>
      )}
    </section>
  );
}

function EnemiesBlock({ data }: { data: EnemiesSection }) {
  return (
    <section className="panel enemies">
      <div className="section-head enemies-head">{data.title}</div>
      {data.rows.map((r, i) => (
        <div key={i} className="enemy-row">
          <span className={`enemy-intent ${r.intent_kind === "attack" ? "is-atk" : ""}`}>
            {r.intent_text}
          </span>
          <span className="enemy-name">{r.name}</span>
          <span className="enemy-hp">{r.hp_text}</span>
          {r.badges.length > 0 && (
            <span className="enemy-badges">{r.badges.map((b) => `[${b}]`).join(" ")}</span>
          )}
        </div>
      ))}
      {data.block_line && <div className="block-line">{data.block_line}</div>}
    </section>
  );
}

function StrategyBlock({ data }: { data: StrategySection }) {
  return (
    <section className="panel strategy">
      <div className="section-head strategy-head">STRATEGY</div>
      {data.hand_lines.map((line, i) => (
        <div key={i} className="strat-line">
          {line}
        </div>
      ))}
      <div className="strat-divider" />
      <div className={`strat-safety ${safetyClass(data.safety.kind)}`}>{data.safety.text}</div>
      {data.lethal_targets.length > 0 && (
        <div className="strat-lethal-line">
          ☠ Can KILL: {data.lethal_targets.join(", ")}
        </div>
      )}
      <div className="strat-divider" />
      <div className="strat-hint">Suggested play:</div>
      {data.suggested.map((s, i) => (
        <div key={i} className={`sug-card ${suggestedClass(s.role)}`}>
          {i + 1}. {s.role === "block" ? "⛨" : "⚔"} {s.name} [{s.energy_cost}E] {s.value_text}
        </div>
      ))}
      <div className="strat-divider" />
      <div className="strat-total">{data.summary_line}</div>
    </section>
  );
}

function RelicsBlock({ data }: { data: RelicsSection }) {
  return (
    <section className="panel relics">
      <div className="section-head relics-head">{data.title}</div>
      {data.with_short.map((r, i) => (
        <div key={i} className="relic-line" style={{ color: r.color }}>
          {r.name} • {r.short}
        </div>
      ))}
      {data.other_names.length > 0 && (
        <div className="relic-other">Other: {data.other_names.join(", ")}</div>
      )}
    </section>
  );
}

function MerchantBlock({ data }: { data: MerchantRelicsSection }) {
  return (
    <section className="panel merchant">
      <div className="section-head merchant-head">{data.title}</div>
      {data.rows.map((r, i) => (
        <div key={i} className="merchant-line" style={{ color: r.color }}>
          {r.name} • {r.rarity} • {r.cost}g
          {r.short ? ` • ${r.short}` : ""}
        </div>
      ))}
    </section>
  );
}

function CardAdvisorBlock({ data }: { data: CardAdvisorSection }) {
  return (
    <section className="panel card-advisor">
      <div className="reward-banner">{data.banner}</div>
      <div className="reward-sub">CARD REWARD</div>
      {data.wiki_build_title && (
        <div className="wiki-hint">Deck fit (wiki builds): {data.wiki_build_title}</div>
      )}
      {data.recommendations.map((r, i) => (
        <div key={i} className="rec-block">
          <div
            className={`rec-line ${r.is_best ? "is-best" : ""} ${TIER_CLASS[r.tier] ?? "tier-low"}`}
          >
            {r.is_best ? "✔ BEST  " : `${r.tier}  `}
            {r.name} (score {r.score})
            {r.mobalytics_tier || r.wiki_tier
              ? `  [${[r.mobalytics_tier ? `M:${r.mobalytics_tier}` : "", r.wiki_tier ? `W:${r.wiki_tier}` : ""].filter(Boolean).join(" ")}]`
              : ""}
          </div>
          {r.reason ? <div className="rec-reason">• {r.reason}</div> : <div className="rec-spacer" />}
        </div>
      ))}
      {data.warnings.map((w, i) => (
        <div key={i} className="rec-warn">
          ⚠ {w}
        </div>
      ))}
    </section>
  );
}

function DebugBlock({ data }: { data: DebugSection }) {
  return (
    <section className="panel debug">
      <div className="section-head debug-head">DEBUG</div>
      <pre className="debug-pre">{data.lines.join("\n")}</pre>
    </section>
  );
}

function SettingsModal({
  draft,
  onChange,
  onSave,
  onCancel,
}: {
  draft: OverlaySettingsPayload;
  onChange: (next: OverlaySettingsPayload) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const row = (label: string, key: keyof OverlaySettingsPayload) => (
    <label className="set-row">
      <input
        type="checkbox"
        checked={Boolean(draft[key])}
        onChange={(e) => onChange({ ...draft, [key]: e.target.checked })}
      />
      <span>{label}</span>
    </label>
  );

  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div className="modal" role="dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">BoberInSpire — Settings</h2>
        <p className="modal-section">Visible panels</p>
        {row("Combat summary (HP / energy / net damage & block)", "show_combat_summary")}
        {row("Enemies (intents, per-enemy line)", "show_enemies")}
        {row("Strategy (hand summary, suggested play)", "show_strategy")}
        {row("Relics (combat)", "show_relics")}
        {row("Merchant relics (shop)", "show_merchant_relics")}
        {row("Card reward advisor (pick / merchant cards)", "show_card_reward")}
        <p className="modal-section">Transparency</p>
        <input
          type="range"
          min={0.35}
          max={1}
          step={0.05}
          value={draft.alpha}
          onChange={(e) => onChange({ ...draft, alpha: Number(e.target.value) })}
        />
        <p className="modal-section">Overlay</p>
        <label className="set-row">
          <input
            type="checkbox"
            checked={draft.click_through}
            onChange={(e) => onChange({ ...draft, click_through: e.target.checked })}
          />
          <span>Click-through (mouse passes to the game)</span>
        </label>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={onSave}>
            Save &amp; apply
          </button>
        </div>
      </div>
    </div>
  );
}

function defaultPayload(): OverlayPayload {
  const settings: OverlaySettingsPayload = {
    show_combat_summary: true,
    show_enemies: false,
    show_strategy: false,
    show_relics: true,
    show_merchant_relics: true,
    show_card_reward: true,
    alpha: 0.9,
    click_through: false,
  };
  return {
    v: 1,
    meta: {
      status_text: "Connecting to Python bridge…",
      turn: null,
      settings,
      debug: false,
    },
    combat_summary: null,
    enemies: null,
    strategy: null,
    relics: null,
    merchant_relics: null,
    card_advisor: null,
    debug: null,
  };
}

function App() {
  const [payload, setPayload] = useState<OverlayPayload>(defaultPayload);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<OverlaySettingsPayload | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(0);

  const applyClickThrough = useCallback(async (enabled: boolean) => {
    try {
      await invoke("set_click_through", { enabled });
    } catch {
      /* dev without Tauri */
    }
  }, []);

  const connectWs = useCallback(() => {
    void (async () => {
      let url = "ws://127.0.0.1:18765";
      try {
        url = await invoke<string>("get_ws_url");
      } catch {
        /* plain web */
      }
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const p = JSON.parse(String(ev.data)) as OverlayPayload;
          if (p && p.meta) setPayload(p);
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        wsRef.current = null;
        const t = Math.min(10_000, 500 + reconnectRef.current * 500);
        reconnectRef.current += 1;
        window.setTimeout(() => connectWs(), t);
      };
      ws.onopen = () => {
        reconnectRef.current = 0;
      };
    })();
  }, []);

  useEffect(() => {
    connectWs();
    return () => {
      wsRef.current?.close();
    };
  }, [connectWs]);

  useEffect(() => {
    void applyClickThrough(payload.meta.settings.click_through);
  }, [payload.meta.settings.click_through, applyClickThrough]);

  const openSettings = () => {
    setDraft({ ...payload.meta.settings });
    setSettingsOpen(true);
  };

  const saveSettings = () => {
    if (draft) {
      sendSettings(wsRef.current, draft);
      setSettingsOpen(false);
      setDraft(null);
    }
  };

  const cancelSettings = () => {
    setSettingsOpen(false);
    setDraft(null);
  };

  const closeApp = async () => {
    try {
      await getCurrentWindow().close();
    } catch {
      window.close();
    }
  };

  const s = payload.meta.settings;

  return (
    <div className="app-root" style={{ opacity: s.alpha }}>
      <header className="title-bar" data-tauri-drag-region>
        <span className="title-text" data-tauri-drag-region>
          ⚔ BOBER IN SPIRE
        </span>
        <div className="title-actions">
          <button type="button" className="icon-btn" title="Settings" onClick={openSettings}>
            ⚙
          </button>
          <button type="button" className="icon-btn close" title="Close" onClick={closeApp}>
            ✕
          </button>
        </div>
      </header>

      <div className="scroll-area">
        {payload.card_advisor && <CardAdvisorBlock data={payload.card_advisor} />}
        {payload.combat_summary && <CombatBlock data={payload.combat_summary} />}
        {payload.enemies && <EnemiesBlock data={payload.enemies} />}
        {payload.strategy && <StrategyBlock data={payload.strategy} />}
        {payload.relics && <RelicsBlock data={payload.relics} />}
        {payload.merchant_relics && <MerchantBlock data={payload.merchant_relics} />}
        {payload.meta.debug && payload.debug && <DebugBlock data={payload.debug} />}
      </div>

      <footer className="status-bar">{payload.meta.status_text}</footer>

      {settingsOpen && draft && (
        <SettingsModal
          draft={draft}
          onChange={setDraft}
          onSave={saveSettings}
          onCancel={cancelSettings}
        />
      )}
    </div>
  );
}

export default App;
