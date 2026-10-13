import { useState, type ReactNode } from "react";
import { Dialog } from "@astryxdesign/core/Dialog";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Item } from "@astryxdesign/core/Item";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ApiKeySettings } from "./ApiKeySettings";
import { BackupSettings } from "./BackupSettings";
import { ImageGenerationSettings } from "./ImageGenerationSettings";
import {
  BrainIcon,
  ChartBarIcon,
  ClockIcon,
  CpuIcon,
  DownloadIcon,
  ImageIcon,
  KeyIcon,
  NetworkIcon,
  PlugIcon,
  SearchIcon,
  XIcon,
} from "./icons";
import { LogsSettings } from "./LogsSettings";
import { McpSettings } from "./McpSettings";
import { MemorySettings } from "./MemorySettings";
import { ModelSettings } from "./ModelSettings";
import { MultiAgentRolesSettings } from "./MultiAgentRolesSettings";
import { RoleModelsSettings } from "./RoleModelsSettings";
import { ScheduledTasksSettings } from "./ScheduledTasksSettings";
import { TavilySettings } from "./TavilySettings";

type SettingsCategory =
  | "api_key"
  | "tavily"
  | "model"
  | "image_generation"
  | "role_models"
  | "multi_agent_roles"
  | "mcp"
  | "scheduled_tasks"
  | "memory"
  | "logs"
  | "backup";

type CategoryGroup = "Général" | "Agents" | "Outils" | "Données";

const GROUPS: CategoryGroup[] = ["Général", "Agents", "Outils", "Données"];

interface CategoryDef {
  id: SettingsCategory;
  label: string;
  icon: ReactNode;
  group: CategoryGroup;
}

const CATEGORIES: CategoryDef[] = [
  { id: "api_key", label: "Clé API", icon: <KeyIcon className="h-4 w-4" />, group: "Général" },
  { id: "model", label: "Modèle", icon: <CpuIcon className="h-4 w-4" />, group: "Général" },
  { id: "memory", label: "Mémoire", icon: <BrainIcon className="h-4 w-4" />, group: "Général" },
  {
    id: "multi_agent_roles",
    label: "Rôles multi-agent",
    icon: <NetworkIcon className="h-4 w-4" />,
    group: "Agents",
  },
  {
    id: "role_models",
    label: "Modèles des rôles",
    icon: <NetworkIcon className="h-4 w-4" />,
    group: "Agents",
  },
  { id: "mcp", label: "Serveurs MCP", icon: <PlugIcon className="h-4 w-4" />, group: "Outils" },
  { id: "tavily", label: "Tavily", icon: <SearchIcon className="h-4 w-4" />, group: "Outils" },
  {
    id: "image_generation",
    label: "Génération d’images",
    icon: <ImageIcon className="h-4 w-4" />,
    group: "Outils",
  },
  {
    id: "scheduled_tasks",
    label: "Tâches récurrentes",
    icon: <ClockIcon className="h-4 w-4" />,
    group: "Données",
  },
  {
    id: "logs",
    label: "Logs & coûts",
    icon: <ChartBarIcon className="h-4 w-4" />,
    group: "Données",
  },
  {
    id: "backup",
    label: "Sauvegarde",
    icon: <DownloadIcon className="h-4 w-4" />,
    group: "Données",
  },
];

const WEB_CATEGORY_IDS: SettingsCategory[] = [
  "model",
  "image_generation",
  "memory",
  "logs",
  "backup",
];
const WEB_REMOTE_WORKSPACE_CATEGORY_IDS: SettingsCategory[] = [
  "multi_agent_roles",
  "role_models",
  "mcp",
  "scheduled_tasks",
];

function webCategories(remoteWorkspacesEnabled: boolean): CategoryDef[] {
  const ids = remoteWorkspacesEnabled
    ? [...WEB_CATEGORY_IDS, ...WEB_REMOTE_WORKSPACE_CATEGORY_IDS]
    : WEB_CATEGORY_IDS;
  return CATEGORIES.filter((category) => ids.includes(category.id));
}

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  isWebDeployment?: boolean;
  remoteWorkspacesEnabled?: boolean;
  // the current model is held by App.tsx (apiModel) for use elsewhere
  // (composer, avatar...) - propagated down to ModelSettings so a change
  // reflects right away, without waiting for the modal to close.
  onModelChanged: () => void;
  onImageModelChanged: () => void;
}

/** Two-pane settings modal (search + categories on the left, category
 * content on the right), Claude Desktop/ChatGPT-style rather than
 * standalone pages: closes on outside click or Escape (Dialog
 * purpose="info"), replaces SettingsPage/LogsPage/McpServersPage/
 * ModelPage. */
export function SettingsModal({
  isOpen,
  onClose,
  isWebDeployment = false,
  remoteWorkspacesEnabled = false,
  onModelChanged,
  onImageModelChanged,
}: SettingsModalProps) {
  const [category, setCategory] = useState<SettingsCategory>(
    isWebDeployment ? "model" : "api_key",
  );
  const [search, setSearch] = useState("");
  const categories = isWebDeployment ? webCategories(remoteWorkspacesEnabled) : CATEGORIES;

  const filtered = categories.filter((c) =>
    c.label.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      purpose="info"
      width={1040}
      maxHeight="80dvh"
      padding={0}
      aria-label="Paramètres"
    >
      <div className="flex h-[720px] max-h-[85dvh]">
        <div className="flex w-60 shrink-0 flex-col overflow-y-auto border-r border-border bg-body p-4">
          <h2 className="m-0 mb-3 px-2 text-lg font-semibold text-primary">Réglages</h2>
          <TextInput
            value={search}
            onChange={setSearch}
            placeholder="Rechercher"
            isLabelHidden
            label="Rechercher un réglage"
            size="sm"
            startIcon={<SearchIcon className="h-4 w-4 text-secondary" />}
            className="mb-4"
          />
          <div className="flex flex-col gap-4">
            {GROUPS.map((group) => {
              const items = filtered.filter((c) => c.group === group);
              if (items.length === 0) return null;
              return (
                <div key={group} className="flex flex-col gap-0.5">
                  <Text
                    size="2xs"
                    color="secondary"
                    weight="semibold"
                    className="mb-1 block px-2 uppercase tracking-wider"
                  >
                    {group}
                  </Text>
                  {items.map((c) => (
                    <Item
                      key={c.id}
                      label={c.label}
                      startContent={c.icon}
                      isSelected={category === c.id}
                      density="compact"
                      onClick={() => {
                        setCategory(c.id);
                      }}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        </div>

        <div className="relative min-w-0 flex-1 overflow-y-auto px-8 py-7">
          <IconButton
            label="Fermer"
            icon={<XIcon />}
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="absolute right-4 top-4"
          />
          <div key={category} className="animate-fade-in">
            {category === "api_key" && <ApiKeySettings />}
            {category === "tavily" && <TavilySettings />}
            {category === "model" && <ModelSettings onModelChanged={onModelChanged} />}
            {category === "image_generation" && (
              <ImageGenerationSettings onModelChanged={onImageModelChanged} />
            )}
            {category === "multi_agent_roles" && <MultiAgentRolesSettings />}
            {category === "role_models" && <RoleModelsSettings />}
            {category === "mcp" && <McpSettings />}
            {category === "scheduled_tasks" && <ScheduledTasksSettings />}
            {category === "memory" && <MemorySettings />}
            {category === "logs" && <LogsSettings />}
            {category === "backup" && <BackupSettings />}
          </div>
        </div>
      </div>
    </Dialog>
  );
}
