import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import {
  DownloadIcon,
  MoreIcon,
  PencilIcon,
  PinIcon,
  PlusIcon,
  TrashIcon,
} from "./icons";
import { API_BASE } from "./api";

export interface SidebarSession {
  id: string;
  pinned: boolean;
}

function exportSession(session: SidebarSession, format: "markdown" | "json") {
  const a = document.createElement("a");
  a.href = `${API_BASE}/sessions/${session.id}/export?export_format=${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/** A single, propagation-safe actions menu for every conversation row. */
export function SessionActionsMenu({
  session,
  onRename,
  onTogglePin,
  onDelete,
  className,
}: {
  session: SidebarSession;
  onRename: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
  className?: string;
}) {
  return (
    <div
      className={className}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <DropdownMenu
        button={{
          icon: <MoreIcon />,
          isIconOnly: true,
          variant: "ghost",
          size: "sm",
          label: "Actions",
        }}
        hasChevron={false}
        items={[
          { label: "Renommer", icon: <PencilIcon />, onClick: onRename },
          {
            label: "Exporter en Markdown",
            icon: <DownloadIcon />,
            onClick: () => {
              exportSession(session, "markdown");
            },
          },
          {
            label: "Exporter en JSON",
            icon: <DownloadIcon />,
            onClick: () => {
              exportSession(session, "json");
            },
          },
          {
            label: session.pinned ? "Désépingler" : "Épingler",
            icon: <PinIcon filled={session.pinned} />,
            onClick: onTogglePin,
          },
          { type: "divider" },
          {
            label: "Supprimer",
            icon: <TrashIcon />,
            variant: "destructive",
            onClick: onDelete,
          },
        ]}
      />
    </div>
  );
}

export function ProjectActionsMenu({
  onNewConversation,
  onRename,
  onDelete,
  className,
}: {
  onNewConversation: () => void;
  onRename: () => void;
  onDelete: () => void;
  className?: string;
}) {
  return (
    <div
      className={className}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <DropdownMenu
        button={{
          icon: <MoreIcon />,
          isIconOnly: true,
          variant: "ghost",
          size: "sm",
          label: "Actions du projet",
        }}
        hasChevron={false}
        items={[
          {
            label: "Nouvelle conversation",
            icon: <PlusIcon />,
            onClick: onNewConversation,
          },
          { label: "Renommer", icon: <PencilIcon />, onClick: onRename },
          { type: "divider" },
          {
            label: "Supprimer",
            icon: <TrashIcon />,
            variant: "destructive",
            onClick: onDelete,
          },
        ]}
      />
    </div>
  );
}
