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

interface CategoryDef {
  id: SettingsCategory;
  label: string;
  icon: ReactNode;
}

const CATEGORIES: CategoryDef[] = [
  { id: "api_key", label: "Clé API", icon: <KeyIcon className="h-4 w-4" /> },
  { id: "tavily", label: "Tavily", icon: <SearchIcon className="h-4 w-4" /> },
  { id: "model", label: "Modèle", icon: <CpuIcon className="h-4 w-4" /> },
  {
    id: "image_generation",
    label: "Génération d’images",
    icon: <ImageIcon className="h-4 w-4" />,
  },
  {
    id: "multi_agent_roles",
    label: "Rôles multi-agent",
    icon: <NetworkIcon className="h-4 w-4" />,
  },
  {
    id: "role_models",
    label: "Modèles des rôles",
    icon: <NetworkIcon className="h-4 w-4" />,
  },
  { id: "mcp", label: "Serveurs MCP", icon: <PlugIcon className="h-4 w-4" /> },
  {
    id: "scheduled_tasks",
    label: "Tâches récurrentes",
    icon: <ClockIcon className="h-4 w-4" />,
  },
  { id: "memory", label: "Mémoire", icon: <BrainIcon className="h-4 w-4" /> },
  { id: "logs", label: "Logs & coûts", icon: <ChartBarIcon className="h-4 w-4" /> },
  { id: "backup", label: "Sauvegarde", icon: <DownloadIcon className="h-4 w-4" /> },
];

const WEB_CATEGORY_IDS: SettingsCategory[] = [
  "tavily",
  "model",
  "image_generation",
  "mcp",
  "memory",
  "logs",
  "backup",
];
const WEB_REMOTE_WORKSPACE_CATEGORY_IDS: SettingsCategory[] = [
  "multi_agent_roles",
  "role_models",
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
  // le modele courant est tenu par App.tsx (apiModel) pour l'utiliser
  // ailleurs (composer, avatar...) - propage jusqu'a ModelSettings pour
  // qu'un changement se reflete tout de suite, sans attendre la fermeture
  // de la modale.
  onModelChanged: () => void;
  onImageModelChanged: () => void;
}

/** Modale de reglages a deux volets (recherche + categories a gauche,
 * contenu de la categorie a droite), style Claude Desktop/ChatGPT plutot
 * que des pages a part entiere : ferme au clic en dehors ou sur Echap
 * (Dialog purpose="info"), remplace SettingsPage/LogsPage/McpServersPage/
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
      width={880}
      maxHeight="80dvh"
      padding={0}
      aria-label="Paramètres"
    >
      <div className="flex h-[640px] max-h-[80dvh]">
        <div className="flex w-56 shrink-0 flex-col border-r border-border p-3">
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
          <Text size="2xs" color="secondary" className="mb-1 block px-2 uppercase tracking-wide">
            Paramètres
          </Text>
          <div className="flex flex-col gap-0.5">
            {filtered.map((c) => (
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
        </div>

        <div className="relative min-w-0 flex-1 overflow-y-auto p-6">
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
