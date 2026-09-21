import { IconButton } from "@astryxdesign/core/IconButton";
import { SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { formatSessionLabel } from "./chatMessages";
import { ChevronRightIcon, FolderIcon, PlusIcon } from "./icons";
import { ProjectActionsMenu, SessionActionsMenu } from "./SidebarMenus";

interface Session {
  id: string;
  title: string | null;
  project_id: string | null;
  pinned: boolean;
}

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

interface ProjectSidebarSectionProps {
  projects: Project[];
  sessions: Session[];
  activeProjectId: string | null;
  activeSessionId: string | null;
  sendingSessionIds: Set<string>;
  collapsedProjectIds: Set<string>;
  editingProjectId: string | null;
  editingProjectValue: string;
  editingSessionId: string | null;
  editingValue: string;
  onNewProject: () => void;
  onToggleCollapse: (projectId: string) => void;
  onNewProjectConversation: (projectId: string) => void;
  onStartRenameProject: (project: Project) => void;
  onDeleteProject: (project: Project) => void;
  onEditingProjectValueChange: (value: string) => void;
  onCommitRenameProject: (id: string) => void;
  onCancelRenameProject: () => void;
  onSwitchSession: (id: string) => void;
  onStartRenameSession: (session: Session) => void;
  onTogglePinSession: (session: Session) => void;
  onDeleteSession: (session: Session) => void;
  onEditingValueChange: (value: string) => void;
  onCommitRenameSession: (id: string) => void;
  onCancelRenameSession: () => void;
}

export function ProjectSidebarSection({
  projects,
  sessions,
  activeProjectId,
  activeSessionId,
  sendingSessionIds,
  collapsedProjectIds,
  editingProjectId,
  editingProjectValue,
  editingSessionId,
  editingValue,
  onNewProject,
  onToggleCollapse,
  onNewProjectConversation,
  onStartRenameProject,
  onDeleteProject,
  onEditingProjectValueChange,
  onCommitRenameProject,
  onCancelRenameProject,
  onSwitchSession,
  onStartRenameSession,
  onTogglePinSession,
  onDeleteSession,
  onEditingValueChange,
  onCommitRenameSession,
  onCancelRenameSession,
}: ProjectSidebarSectionProps) {
  return (
    <SideNavSection
      title="Projets"
      endContent={
        <IconButton
          label="Nouveau projet"
          icon={<PlusIcon />}
          variant="ghost"
          size="sm"
          onClick={onNewProject}
        />
      }
    >
      {projects.length === 0 && (
        <Text size="2xs" color="secondary" className="block px-2 py-1">
          Aucun projet.
        </Text>
      )}
      {projects.map((p) => {
        const isCollapsed = collapsedProjectIds.has(p.id);
        return (
          <div key={p.id}>
            {editingProjectId === p.id ? (
              <div className="px-2 py-1">
                <TextInput
                  value={editingProjectValue}
                  onChange={onEditingProjectValueChange}
                  isLabelHidden
                  label="Nom du projet"
                  size="sm"
                  hasAutoFocus
                  onEnter={() => {
                    onCommitRenameProject(p.id);
                  }}
                  onBlur={() => {
                    onCommitRenameProject(p.id);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") onCancelRenameProject();
                  }}
                />
              </div>
            ) : (
              <div className="group">
                <SideNavItem
                  label={p.name}
                  icon={<FolderIcon className="h-4 w-4" />}
                  isSelected={p.id === activeProjectId && activeSessionId === null}
                  onClick={() => {
                    onToggleCollapse(p.id);
                  }}
                  endContent={
                    <div className="flex items-center gap-0.5">
                      <ProjectActionsMenu
                        className="pointer-events-none opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
                        onNewConversation={() => {
                          onNewProjectConversation(p.id);
                        }}
                        onRename={() => {
                          onStartRenameProject(p);
                        }}
                        onDelete={() => {
                          onDeleteProject(p);
                        }}
                      />
                      <ChevronRightIcon
                        className={`h-4 w-4 shrink-0 text-secondary transition-transform ${isCollapsed ? "" : "rotate-90"}`}
                      />
                    </div>
                  }
                />
              </div>
            )}
            {!isCollapsed &&
              sessions
                .filter((s) => s.project_id === p.id)
                .sort((a, b) => Number(b.pinned) - Number(a.pinned))
                .map((s) =>
                  editingSessionId === s.id ? (
                    <div key={s.id} className="py-1 pl-4">
                      <TextInput
                        value={editingValue}
                        onChange={onEditingValueChange}
                        isLabelHidden
                        label="Titre de la conversation"
                        size="sm"
                        hasAutoFocus
                        onEnter={() => {
                          onCommitRenameSession(s.id);
                        }}
                        onBlur={() => {
                          onCommitRenameSession(s.id);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") onCancelRenameSession();
                        }}
                      />
                    </div>
                  ) : (
                    <div key={s.id} className="group">
                      <SideNavItem
                        label={s.title ?? formatSessionLabel(s.id)}
                        isSelected={s.id === activeSessionId}
                        onClick={() => {
                          onSwitchSession(s.id);
                        }}
                        className="pl-4"
                        endContent={
                          <div className="flex items-center gap-1">
                            {/* reponse en cours en arriere-plan (voir
                                    sendMessage) - jamais pour celle
                                    affichee, la vue principale montre
                                    deja son propre etat "en cours". */}
                            {s.id !== activeSessionId && sendingSessionIds.has(s.id) && (
                              <Spinner size="sm" shade="subtle" aria-label="Réponse en cours" />
                            )}
                            <SessionActionsMenu
                              className="pointer-events-none opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
                              session={s}
                              onRename={() => {
                                onStartRenameSession(s);
                              }}
                              onTogglePin={() => {
                                onTogglePinSession(s);
                              }}
                              onDelete={() => {
                                onDeleteSession(s);
                              }}
                            />
                          </div>
                        }
                      />
                    </div>
                  ),
                )}
          </div>
        );
      })}
    </SideNavSection>
  );
}
