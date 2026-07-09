import React, { useEffect, useMemo, useState } from "react";
import {
  BookText,
  Check,
  Cpu,
  FolderOpen,
  Info,
  Loader2,
  Monitor,
  Moon,
  Palette,
  Plug,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import type { AnyRecord, OverviewPayload, SettingsPayload } from "../types";
import { api } from "../api";
import {
  PERMISSION_TIERS,
  DEFAULT_PERMISSION_TIER,
  isPermissionTierId,
  type PermissionTierId,
} from "../permissionTiers";
import type { ThemeSetting } from "../hooks/useTheme";

type SectionId = "permission" | "appearance" | "workspace" | "model" | "tools" | "rules" | "about";

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: "permission", label: "默认权限", icon: <ShieldCheck size={15} /> },
  { id: "appearance", label: "外观", icon: <Palette size={15} /> },
  { id: "workspace", label: "工作区", icon: <FolderOpen size={15} /> },
  { id: "model", label: "模型与提供方", icon: <Cpu size={15} /> },
  { id: "tools", label: "工具与技能", icon: <Plug size={15} /> },
  { id: "rules", label: "项目规则", icon: <BookText size={15} /> },
  { id: "about", label: "关于", icon: <Info size={15} /> },
];

const THEME_OPTIONS: { id: ThemeSetting; label: string; icon: React.ReactNode; hint: string }[] = [
  { id: "system", label: "跟随系统", icon: <Monitor size={15} />, hint: "跟随你的操作系统设置" },
  { id: "light", label: "浅色", icon: <Sun size={15} />, hint: "始终浅色" },
  { id: "dark", label: "深色", icon: <Moon size={15} />, hint: "始终深色" },
];

function AppearanceSection({
  theme,
  onThemeChange,
}: {
  theme: ThemeSetting;
  onThemeChange: (next: ThemeSetting) => void;
}) {
  return (
    <div className="settingsSection">
      <h3>外观</h3>
      <p className="settingsSectionHint">
        选择 Studio 的外观。“跟随系统”会跟随你的操作系统，并在其变化时实时更新。
      </p>
      <div className="themeToggle" role="radiogroup" aria-label="主题">
        {THEME_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={theme === option.id}
            className={theme === option.id ? "themeOption active" : "themeOption"}
            title={option.hint}
            onClick={() => onThemeChange(option.id)}
          >
            {option.icon}
            <span>{option.label}</span>
            {theme === option.id && <Check size={13} className="themeOptionCheck" />}
          </button>
        ))}
      </div>
    </div>
  );
}

function workspaceBadges(profile: SettingsPayload["workspaceProfile"]): string[] {
  if (!profile) return [];
  return [
    profile.initialized ? "Asteria 已初始化" : "待初始化",
    profile.has_git ? "Git" : "无 Git",
    profile.has_agents_md ? "AGENTS.md" : "无 AGENTS.md",
  ];
}

function PermissionSection({
  settings,
  onSaved,
}: {
  settings: SettingsPayload | null;
  onSaved: (next: SettingsPayload) => void;
}) {
  const saved = isPermissionTierId(settings?.permissionMode)
    ? settings!.permissionMode
    : DEFAULT_PERMISSION_TIER;
  const [busy, setBusy] = useState<PermissionTierId | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function choose(id: PermissionTierId) {
    if (id === saved || busy) return;
    setBusy(id);
    setError(null);
    try {
      const result = await api.updateSettings({ permissionMode: id });
      if (!result.ok) {
        setError(result.error || "无法保存。");
        return;
      }
      onSaved(result.settings);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">默认权限</h3>
      <p className="muted">默认情况下 agent 自主执行的程度。你仍可在输入框中按每条消息单独更改。</p>
      <div className="permTierList" role="radiogroup" aria-label="默认权限档">
        {PERMISSION_TIERS.map((tier) => {
          const active = saved === tier.id;
          return (
            <button
              key={tier.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={active ? "permTierOption active" : "permTierOption"}
              disabled={Boolean(busy)}
              onClick={() => void choose(tier.id)}
            >
              <span className="permTierHead">
                <strong>{tier.label}</strong>
                {tier.id === DEFAULT_PERMISSION_TIER && (
                  <span className="permTierDefault">推荐</span>
                )}
                {busy === tier.id ? (
                  <Loader2 size={14} className="spinning" />
                ) : active ? (
                  <Check size={15} className="permTierCheck" />
                ) : null}
              </span>
              <small>{tier.detail}</small>
            </button>
          );
        })}
      </div>
      {error && <p className="settingsError">{error}</p>}
      <p className="settingsNote muted">
        在此保存后，将作为新消息的初始设置。命令，以及任何有风险或不可逆的操作，都会为你暂停——
        无论选择哪一档。
      </p>
    </div>
  );
}

function WorkspaceSection({
  settings,
  onChangeWorkspace,
}: {
  settings: SettingsPayload | null;
  onChangeWorkspace: () => void;
}) {
  const badges = workspaceBadges(settings?.workspaceProfile);
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">工作区</h3>
      <p className="muted">目标、计划和编辑所在的项目文件夹。</p>
      <div className="workspaceCurrent">
        <small>当前文件夹</small>
        <strong title={settings?.workspace}>{settings?.workspaceName ?? "工作区"}</strong>
        <span className="muted" title={settings?.workspace}>
          {settings?.workspace ?? "—"}
        </span>
        {badges.length > 0 && (
          <div className="workspaceBadges">
            {badges.map((badge) => (
              <span key={badge} className="workspaceBadge">
                {badge}
              </span>
            ))}
          </div>
        )}
      </div>
      <button type="button" className="secondaryButton" onClick={onChangeWorkspace}>
        <FolderOpen size={15} /> 更改工作区…
      </button>
    </div>
  );
}

function ModelSection({ overview }: { overview: OverviewPayload | null }) {
  const routes = (overview?.modelRoutes ?? []) as AnyRecord[];
  const doctor = (overview?.doctor ?? {}) as AnyRecord;
  const routeHealth = (doctor.routes ?? {}) as AnyRecord;
  const routeReqs = (doctor.route_requirements ?? {}) as AnyRecord;
  const tiers = Object.keys(routeHealth);
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">模型与提供方</h3>
      {tiers.length > 0 && (
        <div className="settingsProviderReadiness">
          <p className="muted">提供方就绪状态——设置下面的环境变量，然后重新打开 Studio。</p>
          <div className="settingsRowList">
            {tiers.map((tier) => {
              const route = (routeHealth[tier] ?? {}) as AnyRecord;
              const missing = (Array.isArray(route.missing) ? route.missing : []) as string[];
              const configured = route.configured !== false && missing.length === 0;
              const provider = String(route.provider ?? "");
              const reqs = (Array.isArray(routeReqs[tier]) ? routeReqs[tier] : []) as string[];
              const need = (missing.length ? missing : reqs).join(", ");
              return (
                <div className="settingsRow" key={tier}>
                  <div className="settingsRowMain">
                    <strong>{tier}</strong>
                    <span className="muted">{provider || (configured ? "已配置" : "未配置")}</span>
                  </div>
                  <span className={configured ? "settingsRowMeta good" : "settingsRowMeta warn"}>
                    {configured ? "就绪" : `请设置 ${need || "提供方环境变量"}`}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <p className="muted">近期活动——运行时在近期任务中实际使用的模型。</p>
      {routes.length === 0 ? (
        <p className="settingsStatusBlock muted">
          暂无模型活动。运行一个任务，运行时选择的路由将显示在这里。
        </p>
      ) : (
        <div className="settingsRowList">
          {routes.slice(0, 8).map((route, index) => {
            const provider = String(route.provider ?? "未知");
            const model = String(route.model ?? "未知");
            const purpose = String(route.purpose ?? "任务");
            const tier = String(route.tier ?? "");
            const total = Number(route.total ?? 0);
            const successRate = Number(route.successRate ?? 0);
            return (
              <div className="settingsRow" key={`${provider}/${model}/${purpose}/${index}`}>
                <div className="settingsRowMain">
                  <strong>{purpose}</strong>
                  <span className="muted">
                    {provider}/{model}
                    {tier ? ` · ${tier}` : ""}
                  </span>
                </div>
                {total > 0 && (
                  <span className="settingsRowMeta muted">
                    {Math.round(successRate * 100)}% 成功 · {total} 次调用
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ToolsSection() {
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">工具与技能</h3>
      <div className="settingsStatusBlock">
        <div className="settingsStatusHead">
          <Plug size={14} /> <strong>MCP 工具</strong>
        </div>
        <p className="muted">
          外部 MCP 工具调用通过真实的运行时连接器执行。每个任务的 MCP 活动（哪个服务器、
          哪个工具、结果如何）会显示在 Inspector 中。已连接的服务器列表目前尚未在此展示。
        </p>
      </div>
      <div className="settingsStatusBlock">
        <div className="settingsStatusHead">
          <BookText size={14} /> <strong>技能</strong>
        </div>
        <p className="muted">
          当任务匹配时，技能会把它们的书面流程作为上下文提供给 agent——它们是 agent 遵循的 指引，而非
          Studio 按需运行的沙箱程序，因此没有可开关的开关项。
        </p>
      </div>
    </div>
  );
}

function RulesSection({ settings }: { settings: SettingsPayload | null }) {
  const hasAgents = Boolean(settings?.workspaceProfile?.has_agents_md);
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">项目规则与记忆</h3>
      <p className="muted">
        工作区中影响 agent 行为的文件。Studio 会读取它们；请在你的编辑器中修改。
      </p>
      <div className="settingsRowList">
        <div className="settingsRow">
          <div className="settingsRowMain">
            <strong>AGENTS.md</strong>
            <span className="muted">项目指引与护栏</span>
          </div>
          <span className={hasAgents ? "settingsRowMeta good" : "settingsRowMeta muted"}>
            {hasAgents ? "已启用" : "未找到"}
          </span>
        </div>
        <div className="settingsRow">
          <div className="settingsRowMain">
            <strong>CLAUDE.md</strong>
            <span className="muted">工具专属指令（如有）</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function AboutSection({ settings }: { settings: SettingsPayload | null }) {
  const rows: { label: string; value?: string }[] = [
    { label: "工作区", value: settings?.workspace },
    { label: "运行时根目录", value: settings?.runtimeRoot },
    { label: "Shell", value: settings?.shell },
  ];
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">关于</h3>
      <div className="settingsRowList">
        {rows.map((row) => (
          <div className="settingsRow" key={row.label}>
            <div className="settingsRowMain">
              <strong>{row.label}</strong>
              <span className="muted" title={row.value}>
                {row.value ?? "—"}
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="settingsNote muted">
        原始运行证据——模型调用、工具步骤、MCP 活动——都在 Inspector 中。
      </p>
    </div>
  );
}

export function SettingsPanel({
  open,
  settings,
  overview,
  theme,
  onThemeChange,
  onClose,
  onChangeWorkspace,
  onSaved,
}: {
  open: boolean;
  settings: SettingsPayload | null;
  overview: OverviewPayload | null;
  theme: ThemeSetting;
  onThemeChange: (next: ThemeSetting) => void;
  onClose: () => void;
  onChangeWorkspace: () => void;
  onSaved: (next: SettingsPayload) => void;
}) {
  const [section, setSection] = useState<SectionId>("permission");

  useEffect(() => {
    if (open) setSection("permission");
  }, [open]);

  // Escape closes the modal (was only dismissable by clicking the backdrop).
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const body = useMemo(() => {
    switch (section) {
      case "appearance":
        return <AppearanceSection theme={theme} onThemeChange={onThemeChange} />;
      case "workspace":
        return <WorkspaceSection settings={settings} onChangeWorkspace={onChangeWorkspace} />;
      case "model":
        return <ModelSection overview={overview} />;
      case "tools":
        return <ToolsSection />;
      case "rules":
        return <RulesSection settings={settings} />;
      case "about":
        return <AboutSection settings={settings} />;
      default:
        return <PermissionSection settings={settings} onSaved={onSaved} />;
    }
  }, [section, settings, overview, theme, onThemeChange, onChangeWorkspace, onSaved]);

  if (!open) return null;

  return (
    <div className="workspaceOverlay" role="presentation" onClick={onClose}>
      <div
        className="workspaceModal settingsModal"
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="workspaceModalHeader">
          <div>
            <p className="eyebrow">设置</p>
            <h2>设置</h2>
          </div>
          <button className="iconButton" title="关闭" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="settingsLayout">
          <nav className="settingsNav" aria-label="设置分区">
            {SECTIONS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={section === item.id ? "settingsTab active" : "settingsTab"}
                onClick={() => setSection(item.id)}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            ))}
          </nav>
          <div className="settingsBody">{body}</div>
        </div>
      </div>
    </div>
  );
}
