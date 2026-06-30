import React, { useEffect, useMemo, useState } from "react";
import { BookText, Check, Cpu, FolderOpen, Info, Loader2, Plug, ShieldCheck, X } from "lucide-react";
import type { AnyRecord, OverviewPayload, SettingsPayload } from "../types";
import { api } from "../api";
import { PERMISSION_TIERS, DEFAULT_PERMISSION_TIER, isPermissionTierId, type PermissionTierId } from "../permissionTiers";

type SectionId = "permission" | "workspace" | "model" | "tools" | "rules" | "about";

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: "permission", label: "Default permission", icon: <ShieldCheck size={15} /> },
  { id: "workspace", label: "Workspace", icon: <FolderOpen size={15} /> },
  { id: "model", label: "Model & provider", icon: <Cpu size={15} /> },
  { id: "tools", label: "Tools & skills", icon: <Plug size={15} /> },
  { id: "rules", label: "Project rules", icon: <BookText size={15} /> },
  { id: "about", label: "About", icon: <Info size={15} /> },
];

function workspaceBadges(profile: SettingsPayload["workspaceProfile"]): string[] {
  if (!profile) return [];
  return [
    profile.initialized ? "Asteria init" : "Needs init",
    profile.has_git ? "Git" : "No git",
    profile.has_agents_md ? "AGENTS.md" : "No AGENTS.md",
  ];
}

function PermissionSection({
  settings,
  onSaved,
}: {
  settings: SettingsPayload | null;
  onSaved: (next: SettingsPayload) => void;
}) {
  const saved = isPermissionTierId(settings?.permissionMode) ? settings!.permissionMode : DEFAULT_PERMISSION_TIER;
  const [busy, setBusy] = useState<PermissionTierId | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function choose(id: PermissionTierId) {
    if (id === saved || busy) return;
    setBusy(id);
    setError(null);
    try {
      const result = await api.updateSettings({ permissionMode: id });
      if (!result.ok) {
        setError(result.error || "Could not save.");
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
      <h3 className="settingsSectionTitle">Default permission</h3>
      <p className="muted">
        How much the agent does on its own by default. You can still change it per message in the composer.
      </p>
      <div className="permTierList" role="radiogroup" aria-label="Default permission tier">
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
                {tier.id === DEFAULT_PERMISSION_TIER && <span className="permTierDefault">Recommended</span>}
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
        Saved here, this seeds new messages. Commands, and anything risky or irreversible, always pause for you —
        whatever the tier.
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
      <h3 className="settingsSectionTitle">Workspace</h3>
      <p className="muted">The project folder goals, plans and edits work in.</p>
      <div className="workspaceCurrent">
        <small>Current folder</small>
        <strong title={settings?.workspace}>{settings?.workspaceName ?? "Workspace"}</strong>
        <span className="muted" title={settings?.workspace}>{settings?.workspace ?? "—"}</span>
        {badges.length > 0 && (
          <div className="workspaceBadges">
            {badges.map((badge) => (
              <span key={badge} className="workspaceBadge">{badge}</span>
            ))}
          </div>
        )}
      </div>
      <button type="button" className="secondaryButton" onClick={onChangeWorkspace}>
        <FolderOpen size={15} /> Change workspace…
      </button>
    </div>
  );
}

function ModelSection({ overview }: { overview: OverviewPayload | null }) {
  const routes = (overview?.modelRoutes ?? []) as AnyRecord[];
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">Model &amp; provider</h3>
      <p className="muted">Decided by the runtime — these are the models it has actually used on recent tasks.</p>
      {routes.length === 0 ? (
        <p className="settingsStatusBlock muted">No model activity yet. Run a task and the routes the runtime chose will show here.</p>
      ) : (
        <div className="settingsRowList">
          {routes.slice(0, 8).map((route, index) => {
            const provider = String(route.provider ?? "unknown");
            const model = String(route.model ?? "unknown");
            const purpose = String(route.purpose ?? "task");
            const tier = String(route.tier ?? "");
            const total = Number(route.total ?? 0);
            const successRate = Number(route.successRate ?? 0);
            return (
              <div className="settingsRow" key={`${provider}/${model}/${purpose}/${index}`}>
                <div className="settingsRowMain">
                  <strong>{purpose}</strong>
                  <span className="muted">{provider}/{model}{tier ? ` · ${tier}` : ""}</span>
                </div>
                {total > 0 && (
                  <span className="settingsRowMeta muted">{Math.round(successRate * 100)}% ok · {total} calls</span>
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
      <h3 className="settingsSectionTitle">Tools &amp; skills</h3>
      <div className="settingsStatusBlock">
        <div className="settingsStatusHead"><Plug size={14} /> <strong>MCP tools</strong></div>
        <p className="muted">
          External MCP tool calls run through the real runtime connector. Per-task MCP activity (which server,
          which tool, the outcome) shows in the Inspector. A connected-server list isn&apos;t surfaced here yet.
        </p>
      </div>
      <div className="settingsStatusBlock">
        <div className="settingsStatusHead"><BookText size={14} /> <strong>Skills</strong></div>
        <p className="muted">
          Skills give the agent their written procedure as context when a task matches — they&apos;re guidance the
          agent follows, not sandboxed programs Studio runs on demand, so there&apos;s nothing to switch on or off.
        </p>
      </div>
    </div>
  );
}

function RulesSection({ settings }: { settings: SettingsPayload | null }) {
  const hasAgents = Boolean(settings?.workspaceProfile?.has_agents_md);
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">Project rules &amp; memory</h3>
      <p className="muted">
        Files in your workspace that shape how the agent behaves. Studio reads them; edit them in your editor.
      </p>
      <div className="settingsRowList">
        <div className="settingsRow">
          <div className="settingsRowMain">
            <strong>AGENTS.md</strong>
            <span className="muted">Project guidance &amp; guardrails</span>
          </div>
          <span className={hasAgents ? "settingsRowMeta good" : "settingsRowMeta muted"}>
            {hasAgents ? "Active" : "Not found"}
          </span>
        </div>
        <div className="settingsRow">
          <div className="settingsRowMain">
            <strong>CLAUDE.md</strong>
            <span className="muted">Tool-specific instructions, if present</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function AboutSection({ settings }: { settings: SettingsPayload | null }) {
  const rows: { label: string; value?: string }[] = [
    { label: "Workspace", value: settings?.workspace },
    { label: "Runtime root", value: settings?.runtimeRoot },
    { label: "Shell", value: settings?.shell },
  ];
  return (
    <div className="settingsSection">
      <h3 className="settingsSectionTitle">About</h3>
      <div className="settingsRowList">
        {rows.map((row) => (
          <div className="settingsRow" key={row.label}>
            <div className="settingsRowMain">
              <strong>{row.label}</strong>
              <span className="muted" title={row.value}>{row.value ?? "—"}</span>
            </div>
          </div>
        ))}
      </div>
      <p className="settingsNote muted">
        Raw run evidence — model calls, tool steps, MCP activity — lives in the Inspector.
      </p>
    </div>
  );
}

export function SettingsPanel({
  open,
  settings,
  overview,
  onClose,
  onChangeWorkspace,
  onSaved,
}: {
  open: boolean;
  settings: SettingsPayload | null;
  overview: OverviewPayload | null;
  onClose: () => void;
  onChangeWorkspace: () => void;
  onSaved: (next: SettingsPayload) => void;
}) {
  const [section, setSection] = useState<SectionId>("permission");

  useEffect(() => {
    if (open) setSection("permission");
  }, [open]);

  const body = useMemo(() => {
    switch (section) {
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
  }, [section, settings, overview, onChangeWorkspace, onSaved]);

  if (!open) return null;

  return (
    <div className="workspaceOverlay" role="presentation" onClick={onClose}>
      <div
        className="workspaceModal settingsModal"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="workspaceModalHeader">
          <div>
            <p className="eyebrow">Settings</p>
            <h2>Settings</h2>
          </div>
          <button className="iconButton" title="Close" aria-label="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="settingsLayout">
          <nav className="settingsNav" aria-label="Settings sections">
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
