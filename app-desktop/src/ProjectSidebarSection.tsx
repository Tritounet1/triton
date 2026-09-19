import { IconButton } from "@astryxdesign/core/IconButton";
import { SideNavSection } from "@astryxdesign/core/SideNav";
import type { ReactNode } from "react";
import { PlusIcon } from "./icons";

interface ProjectSidebarSectionProps {
  children: ReactNode;
  onNewProject: () => void;
}

/** Sidebar project container; mutations remain owned by App while its list is migrated. */
export function ProjectSidebarSection({ children, onNewProject }: ProjectSidebarSectionProps) {
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
      {children}
    </SideNavSection>
  );
}
