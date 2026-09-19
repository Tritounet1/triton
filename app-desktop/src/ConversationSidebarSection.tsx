import { SideNavItem, SideNavSection } from "@astryxdesign/core/SideNav";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { formatSessionLabel } from "./chatMessages";
import { SessionActionsMenu } from "./SidebarMenus";

interface Session {
  id: string;
  title: string | null;
  project_id: string | null;
  pinned: boolean;
}

interface ConversationSidebarSectionProps {
  sessions: Session[];
  activeSessionId: string | null;
  sendingSessionIds: Set<string>;
  editingSessionId: string | null;
  editingValue: string;
  onSwitchSession: (id: string) => void;
  onStartRename: (session: Session) => void;
  onTogglePin: (session: Session) => void;
  onDelete: (session: Session) => void;
  onEditingValueChange: (value: string) => void;
  onCommitRename: (id: string) => void;
  onCancelRename: () => void;
}

/** Top-level (non-project) conversations in the app sidebar. */
export function ConversationSidebarSection({
  sessions,
  activeSessionId,
  sendingSessionIds,
  editingSessionId,
  editingValue,
  onSwitchSession,
  onStartRename,
  onTogglePin,
  onDelete,
  onEditingValueChange,
  onCommitRename,
  onCancelRename,
}: ConversationSidebarSectionProps) {
  const orderedSessions = [...sessions].sort(
    (left, right) => Number(right.pinned) - Number(left.pinned),
  );

  return (
    <SideNavSection title="Conversations">
      {orderedSessions.length === 0 && (
        <Text size="2xs" color="secondary" className="block px-2 py-1">
          Aucune conversation.
        </Text>
      )}
      {orderedSessions.map((session) =>
        editingSessionId === session.id ? (
          <div key={session.id} className="px-2 py-1">
            <TextInput
              value={editingValue}
              onChange={onEditingValueChange}
              isLabelHidden
              label="Titre de la conversation"
              size="sm"
              hasAutoFocus
              onEnter={() => { onCommitRename(session.id); }}
              onBlur={() => { onCommitRename(session.id); }}
              onKeyDown={(event) => {
                if (event.key === "Escape") onCancelRename();
              }}
            />
          </div>
        ) : (
          <div key={session.id} className="group">
            <SideNavItem
              label={session.title ?? formatSessionLabel(session.id)}
              isSelected={session.id === activeSessionId}
              onClick={() => { onSwitchSession(session.id); }}
              endContent={
                <div className="flex items-center gap-1">
                  {session.id !== activeSessionId && sendingSessionIds.has(session.id) && (
                    <Spinner size="sm" shade="subtle" aria-label="Réponse en cours" />
                  )}
                  <SessionActionsMenu
                    className="pointer-events-none opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"
                    session={session}
                    onRename={() => { onStartRename(session); }}
                    onTogglePin={() => { onTogglePin(session); }}
                    onDelete={() => { onDelete(session); }}
                  />
                </div>
              }
            />
          </div>
        ),
      )}
    </SideNavSection>
  );
}
