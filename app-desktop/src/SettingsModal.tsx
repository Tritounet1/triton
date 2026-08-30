import { useState, type ReactNode } from "react";
import { Dialog } from "@astryxdesign/core/Dialog";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Item } from "@astryxdesign/core/Item";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ApiKeySettings } from "./ApiKeySettings";
import { ChartBarIcon, CpuIcon, KeyIcon, PlugIcon, SearchIcon, XIcon } from "./icons";
import { LogsSettings } from "./LogsSettings";
import { McpSettings } from "./McpSettings";
import { ModelSettings } from "./ModelSettings";

type SettingsCategory = "api_key" | "model" | "mcp" | "logs";

interface CategoryDef {
  id: SettingsCategory;
  label: string;
  icon: ReactNode;
}

const CATEGORIES: CategoryDef[] = [
  { id: "api_key", label: "Clé API", icon: <KeyIcon className="h-4 w-4" /> },
  { id: "model", label: "Modèle", icon: <CpuIcon className="h-4 w-4" /> },
  { id: "mcp", label: "Serveurs MCP", icon: <PlugIcon className="h-4 w-4" /> },
  { id: "logs", label: "Logs & coûts", icon: <ChartBarIcon className="h-4 w-4" /> },
];

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  // le modele courant est tenu par App.tsx (apiModel) pour l'utiliser
  // ailleurs (composer, avatar...) - propage jusqu'a ModelSettings pour
  // qu'un changement se reflete tout de suite, sans attendre la fermeture
  // de la modale.
  onModelChanged: () => void;
}

/** Modale de reglages a deux volets (recherche + categories a gauche,
 * contenu de la categorie a droite), style Claude Desktop/ChatGPT plutot
 * que des pages a part entiere : ferme au clic en dehors ou sur Echap
 * (Dialog purpose="info"), remplace SettingsPage/LogsPage/McpServersPage/
 * ModelPage. */
export function SettingsModal({ isOpen, onClose, onModelChanged }: SettingsModalProps) {
  const [category, setCategory] = useState<SettingsCategory>("api_key");
  const [search, setSearch] = useState("");

  const filtered = CATEGORIES.filter((c) =>
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
            {category === "model" && <ModelSettings onModelChanged={onModelChanged} />}
            {category === "mcp" && <McpSettings />}
            {category === "logs" && <LogsSettings />}
          </div>
        </div>
      </div>
    </Dialog>
  );
}
