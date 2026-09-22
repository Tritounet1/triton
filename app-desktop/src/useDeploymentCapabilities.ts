import { useEffect, useState } from "react";
import { API_BASE, isWebDeployment } from "./api";

export interface DeploymentCapabilities {
  remote_workspaces: boolean;
  projects: boolean;
  background_tasks: boolean;
  subagents: boolean;
  snapshots: boolean;
  orchestrator: boolean;
}

const desktopCapabilities: DeploymentCapabilities = {
  remote_workspaces: false,
  projects: true,
  background_tasks: true,
  subagents: true,
  snapshots: true,
  orchestrator: true,
};

const webFallbackCapabilities: DeploymentCapabilities = {
  remote_workspaces: false,
  projects: false,
  background_tasks: false,
  subagents: false,
  snapshots: false,
  orchestrator: false,
};

export function useDeploymentCapabilities(): DeploymentCapabilities {
  const [capabilities, setCapabilities] = useState<DeploymentCapabilities>(
    isWebDeployment ? webFallbackCapabilities : desktopCapabilities,
  );

  useEffect(() => {
    if (!isWebDeployment) return;
    fetch(`${API_BASE}/deployment/capabilities`)
      .then((response) => (response.ok ? response.json() : webFallbackCapabilities))
      .then((data: DeploymentCapabilities) => {
        setCapabilities(data);
      })
      .catch(() => {
        setCapabilities(webFallbackCapabilities);
      });
  }, []);

  return capabilities;
}
