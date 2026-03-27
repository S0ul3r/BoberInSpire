/** Mirrors python_app/overlay_view_model.py payload (v1). */

export type OverlaySettingsPayload = {
  show_combat_summary: boolean;
  show_enemies: boolean;
  show_strategy: boolean;
  show_relics: boolean;
  show_merchant_relics: boolean;
  show_card_reward: boolean;
  alpha: number;
  click_through: boolean;
};

export type OverlayMeta = {
  status_text: string;
  turn: number | null;
  settings: OverlaySettingsPayload;
  debug: boolean;
};

export type NetBanner = {
  kind: "lethal" | "safe" | "warn" | "danger";
  text: string;
};

export type CombatSummary = {
  stats_line: string;
  net: NetBanner | null;
};

export type EnemyRow = {
  name: string;
  intent_kind: string;
  intent_text: string;
  hp_text: string;
  badges: string[];
};

export type EnemiesSection = {
  title: string;
  rows: EnemyRow[];
  block_line: string | null;
};

export type StrategySafety = {
  kind: string;
  text: string;
};

export type SuggestedCard = {
  name: string;
  role: string;
  value_text: string;
  energy_cost: number;
};

export type StrategySection = {
  hand_lines: string[];
  safety: StrategySafety;
  lethal_targets: string[];
  suggested: SuggestedCard[];
  summary_line: string;
};

export type RelicRow = {
  name: string;
  short: string;
  color: string;
};

export type RelicsSection = {
  title: string;
  with_short: RelicRow[];
  other_names: string[];
};

export type MerchantRelicRow = {
  name: string;
  rarity: string;
  cost: number;
  short: string;
  color: string;
};

export type MerchantRelicsSection = {
  title: string;
  rows: MerchantRelicRow[];
};

export type CardRecRow = {
  name: string;
  score: number;
  tier: string;
  reason: string;
  mobalytics_tier: string | null;
  wiki_tier: string | null;
  is_best: boolean;
};

export type CardAdvisorSection = {
  banner: string;
  wiki_build_title: string | null;
  recommendations: CardRecRow[];
  warnings: string[];
};

export type DebugSection = {
  lines: string[];
};

export type OverlayPayload = {
  v: number;
  meta: OverlayMeta;
  combat_summary: CombatSummary | null;
  enemies: EnemiesSection | null;
  strategy: StrategySection | null;
  relics: RelicsSection | null;
  merchant_relics: MerchantRelicsSection | null;
  card_advisor: CardAdvisorSection | null;
  debug: DebugSection | null;
};
