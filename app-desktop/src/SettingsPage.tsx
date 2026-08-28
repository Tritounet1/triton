import { Text } from "@astryxdesign/core/Text";
import { IconButton } from "@astryxdesign/core/IconButton";
import { ArrowLeftIcon, GearIcon } from "./icons";

interface SettingsPageProps {
  onBack: () => void;
  onOpenLogs: () => void;
  onOpenMcp: () => void;
}

export function SettingsPage({ onBack, onOpenLogs, onOpenMcp }: SettingsPageProps) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <div className="mb-6 flex items-center gap-3">
        <IconButton
          label="Retour"
          icon={<ArrowLeftIcon />}
          variant="ghost"
          size="sm"
          onClick={onBack}
        />
        <div className="flex items-center gap-2">
          <GearIcon className="h-5 w-5" />
          <Text size="lg" weight="semibold">
            Paramètres
          </Text>
        </div>
      </div>

      <Text size="2xs" color="secondary" className="mb-2 block px-1 uppercase tracking-wide">
        Outils
      </Text>
      <button
        onClick={onOpenMcp}
        className="mb-6 w-full rounded-xl border border-default bg-surface px-4 py-3 text-left hover:bg-muted"
      >
        <Text weight="medium" className="block">
          Serveurs MCP
        </Text>
        <Text size="2xs" color="secondary" className="block">
          Connecte des serveurs d'outils externes pour étendre ce que le modèle peut faire
        </Text>
      </button>

      <Text size="2xs" color="secondary" className="mb-2 block px-1 uppercase tracking-wide">
        Observabilité
      </Text>
      <button
        onClick={onOpenLogs}
        className="w-full rounded-xl border border-default bg-surface px-4 py-3 text-left hover:bg-muted"
      >
        <Text weight="medium" className="block">
          Historique des logs
        </Text>
        <Text size="2xs" color="secondary" className="block">
          Appels au modèle et exécutions d'outils enregistrés localement
        </Text>
      </button>
    </div>
  );
}
