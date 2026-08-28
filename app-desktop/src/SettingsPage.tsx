import type { ReactNode } from "react";
import { Text } from "@astryxdesign/core/Text";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Item } from "@astryxdesign/core/Item";
import { ArrowLeftIcon, ChartBarIcon, ChevronRightIcon, CpuIcon, GearIcon, PlugIcon } from "./icons";

interface SettingsPageProps {
  onBack: () => void;
  onOpenLogs: () => void;
  onOpenMcp: () => void;
  onOpenModel: () => void;
}

interface SettingsGroupProps {
  title: string;
  children: ReactNode;
}

function SettingsGroup({ title, children }: SettingsGroupProps) {
  return (
    <div className="mb-8">
      <Text size="2xs" color="secondary" className="mb-2 block px-1 uppercase tracking-wide">
        {title}
      </Text>
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
        {children}
      </div>
    </div>
  );
}

export function SettingsPage({ onBack, onOpenLogs, onOpenMcp, onOpenModel }: SettingsPageProps) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <div className="mb-8 flex items-center gap-3">
        <IconButton
          label="Retour"
          icon={<ArrowLeftIcon />}
          variant="ghost"
          size="sm"
          onClick={onBack}
        />
        <div className="flex items-center gap-2">
          <GearIcon className="h-5 w-5 text-secondary" />
          <Text size="lg" weight="semibold">
            Paramètres
          </Text>
        </div>
      </div>

      <SettingsGroup title="Modèle">
        <Item
          label="Choisir le modèle"
          description="Parcourt les modèles OpenRouter avec leur prix par million de tokens"
          startContent={<CpuIcon className="h-5 w-5 text-secondary" />}
          endContent={<ChevronRightIcon className="h-4 w-4 text-secondary" />}
          onClick={onOpenModel}
          density="spacious"
        />
      </SettingsGroup>

      <SettingsGroup title="Outils">
        <Item
          label="Serveurs MCP"
          description="Connecte des serveurs d'outils externes pour étendre ce que le modèle peut faire"
          startContent={<PlugIcon className="h-5 w-5 text-secondary" />}
          endContent={<ChevronRightIcon className="h-4 w-4 text-secondary" />}
          onClick={onOpenMcp}
          density="spacious"
        />
      </SettingsGroup>

      <SettingsGroup title="Observabilité">
        <Item
          label="Historique des logs"
          description="Appels au modèle et exécutions d'outils enregistrés localement"
          startContent={<ChartBarIcon className="h-5 w-5 text-secondary" />}
          endContent={<ChevronRightIcon className="h-4 w-4 text-secondary" />}
          onClick={onOpenLogs}
          density="spacious"
        />
      </SettingsGroup>
    </div>
  );
}
